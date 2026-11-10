"""Purpose-oriented ports that Xorchestrate adapters implement.

No port exposes SQL, subprocesses, MCP packets, vendor model names, or a
prescribed organizational hierarchy. A host selects implementations by
configuration (see ``xcontracts.factories``) and calls them only through these
ports.

Every port is a ``typing.Protocol``: an adapter conforms structurally and need
not inherit from it. The ports are ``runtime_checkable`` so ``isinstance`` can
check that the members exist; it does not check signatures or behavior. The
conformance kit (``xcontracts.testing``) checks behavior.

Ports fall into four groups:

- application state and observation: ``StateStore``/``Transaction`` and
  ``TelemetrySink``;
- capabilities, sessions and judgment: ``CapabilityProvider``, the
  ``SessionDriver`` family with ``ApplicationToolCallback``, ``Evaluator``,
  ``Guardrail`` and ``AcceptancePolicy``;
- routing and delivery policy: ``RoutingPolicy``, ``SessionSelection``,
  ``DeliveryScheduling``, ``DeliveryRetry``, ``ReceiptPolicy``, and the
  injected ``Clock``/``Identifier`` callables;
- operator ports, used by project setup and never by the application core:
  ``VersionControl``, ``Companion``/``CompanionRecords`` and
  ``RepositoryHosting``.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import JSON, Assessment, Capability, Record, Verdict

# -- application state and observation --------------------------------------------


@runtime_checkable
class Transaction(Protocol):
    """One serializable unit of record and event changes, committed together or not at all.

    Records are JSON objects addressed by a ``kind`` and ``key``, nonempty
    strings that encode as UTF-8 (others are refused with ``OrchestrationError``);
    versions start at 1 and increase by one per replacement. Inputs are copied
    on the way in and every returned record or event is a detached copy, so
    neither side can change the other's data afterwards. Data that is not a
    JSON object of JSON values (strings as object keys, finite numbers, no
    tuples or cycles) is refused with ``OrchestrationError`` and writes nothing.

    A transaction is usable only inside its context manager and on the thread
    that opened it; any other use raises ``RuntimeError``. Leaving the context
    by an exception (including ``KeyboardInterrupt``) discards every change.
    """

    def abort(self) -> None:
        """Mark the whole transaction for rollback, even if its caller catches an error."""
        ...

    def get(self, kind: str, key: str) -> Record | None:
        """The current record, or ``None``."""
        ...

    def list(self, kind: str) -> list[Record]:
        """Every record of ``kind``, sorted by key; empty for an unknown kind."""
        ...

    def put(self, kind: str, key: str, data: JSON, expected_version: int | None = None) -> Record:
        """Create if expected_version is None; otherwise compare and replace.

        Creating an existing record, or replacing a missing one or one at
        another version, raises ``Conflict``. ``expected_version`` must be a
        positive ``int`` (not ``bool``); anything else raises ``OrchestrationError``.
        """
        ...

    def delete(self, kind: str, key: str, expected_version: int) -> None:
        """Delete the record at exactly ``expected_version``; otherwise raise ``Conflict``."""
        ...

    def emit(self, event: JSON) -> int:
        """Append an event and return its sequence number (1, 2, ... in commit order)."""
        ...

    def events(self, after: int = 0, limit: int = 100) -> list[JSON]:
        """At most ``limit`` events with sequence greater than ``after``, in order.

        Each event carries its sequence as ``seq``, replacing any ``seq`` the
        emitter supplied. ``after`` and ``limit`` are nonnegative ``int`` values.
        """
        ...


@runtime_checkable
class StateStore(Protocol):
    """Durable or process-local application state with optimistic concurrency.

    Concurrent transactions behave as if run one at a time: of two writers that
    read the same version, exactly one replacement commits and the other gets
    ``Conflict``. Opening a transaction inside another on the same store raises
    ``RuntimeError``, as does ``close`` inside a transaction. ``close`` is
    idempotent and a closed store refuses new transactions with ``RuntimeError``.
    """

    def transaction(self) -> AbstractContextManager[Transaction]: ...
    def close(self) -> None: ...


@runtime_checkable
class TelemetrySink(Protocol):
    """Optional observations; capture receipts do not establish action success.

    Rows have stable event identities, collection sequences, protected payloads
    and their explicit source context. Reads do not initialize absent storage.
    Bundle operations authorize every row of their complete closure through the
    supplied callback before returning a receipt.

    This port is provisional in the 0.x series: its result shapes follow
    Xorchestrate's built-in local collector and may be narrowed in a later minor
    release (see the compatibility policy in the README).
    """

    project_id: str | None

    def new_id(self) -> str: ...
    def record(self, event_type: str, payload: JSON, context: JSON, **metadata: object) -> JSON: ...
    def scan(self, *, after: int = 0, limit: int = 100, **filters: object) -> JSON:
        """Filter one bounded raw batch.

        Returns matching ``events``, raw ``next_after`` and ``scanned`` progress,
        and ``exhausted``. At most ``limit`` repository rows may be read,
        including rows rejected by resource filters. Empty matches may advance.
        """
        ...
    def get_event(self, event_id: str, *, hydrate: bool = True) -> JSON | None: ...
    def resolve_scope(self, row: JSON, *, database_path: object | None = None) -> JSON | None:
        """Recover typed work/session/operation scope for an unscoped row, if known."""
        ...
    def view_observation(self, row: JSON, *, hydrate: bool = True, artifact_store: object | None = None) -> JSON: ...
    def status(self) -> JSON: ...
    def read_payload(self, event_id: str, digest: str | None = None, offset: int = 0, limit: int = 65536) -> JSON: ...
    def snapshot_source(self) -> JSON: ...
    def bundle_source(self, destination: str) -> JSON: ...
    def snapshot(self, destination: str, *, authorize: Callable[[JSON], bool] | None = None,
                 receipt: bool = False) -> JSON: ...
    def verify(self, destination: str, *, authorize: Callable[[JSON], bool] | None = None,
               receipt: bool = False) -> JSON: ...
    def restore(self, bundle: str, destination: str, *, authorize: Callable[[JSON], bool] | None = None,
                receipt: bool = False) -> JSON: ...
    def close(self) -> None: ...


# -- capabilities, sessions and judgment --------------------------------------------


@runtime_checkable
class CapabilityProvider(Protocol):
    """Discovery and invocation of external tools; tool output never grants authority."""

    def discover(self) -> list[Capability]: ...
    def invoke(self, name: str, arguments: JSON, context: JSON) -> JSON:
        """Invoke the descriptor in context['capability']; reject changed metadata.

        The descriptor is the detached discovery snapshot selected by the caller,
        so a concurrent discovery must not silently change this invocation.
        """
        ...
    def close(self) -> None: ...


@runtime_checkable
class SessionDriver(Protocol):
    """Start and communicate with an agent session.

    The returned session handle (``start``) is opaque JSON the host stores and
    hands back. Sending acknowledges submission only; progress and completion
    are reported separately through ``poll``. Process lifetime, resume support
    and reconnect behavior belong to the driver and must be reported accurately.
    """

    def start(self, specification: JSON) -> JSON: ...
    def send(self, session: JSON, message: JSON) -> JSON: ...
    def poll(self, session: JSON) -> list[JSON]: ...
    def stop(self, session: JSON) -> JSON: ...
    def close(self) -> None: ...


@runtime_checkable
class ResumableSessionDriver(SessionDriver, Protocol):
    """Optional port for drivers that can resume a session from their own earlier receipt."""

    def resume(self, source_backend: JSON, specification: JSON) -> JSON:
        """Resume a verified application session using its opaque driver receipt.

        The application authorizes source control and destination creation before
        calling this optional port. Native identity stays inside the adapter.
        """
        ...


@runtime_checkable
class ApplicationToolCallback(Protocol):
    """The callback a host binds into an ``ApplicationToolSessionDriver``."""

    def __call__(self, action: str, arguments: JSON, context: JSON,
                 idempotency_key: str | None = None) -> JSON:
        """Call an application action using the owned session's trusted context.

        Adapters decode native arguments and supply a stable invocation key from
        their verified session identity, never a claimed identity in tool input.
        The host namespaces that key by configured driver and requires it when
        the action schema requires ``idempotency_key``. Context and arguments
        are detached JSON objects; incoming arguments cannot choose the caller.
        """
        ...


@runtime_checkable
class ApplicationToolSessionDriver(SessionDriver, Protocol):
    """Optional port for drivers that expose application actions as native tools.

    Native tool descriptions, requests and response envelopes belong to the
    adapter. Ordinary session drivers need not implement this port.

    A driver that answers repeated native calls from its own call ledger may
    also define ``bind_application_replay(callback)``, with the same callback
    signature. The host then validates each completed cache hit through it
    without invoking a new effect: the callback retains the original native
    call identity, rechecks current authorization and result applicability,
    and rejects a missing/unresolved durable call. Drivers without a replay
    ledger omit it and keep their own cache-only replay contract.
    """

    def bind_application_tools(self, capabilities: list[Capability], callback: ApplicationToolCallback) -> None:
        """Bind application actions before starting sessions."""
        ...


@runtime_checkable
class Evaluator(Protocol):
    """An assessment with rationale, confidence and evidence; never permission to override policy."""

    def assess(self, question: str, context: JSON) -> Assessment: ...
    def close(self) -> None: ...


@runtime_checkable
class Guardrail(Protocol):
    """Whether a requested action is allowed under explicit policy."""

    def evaluate(self, action: str, context: JSON) -> Verdict: ...


@runtime_checkable
class AcceptancePolicy(Protocol):
    """Decisions over current owner requirements and bound measurements.

    ``identity`` names the material policy configuration, so a decision can be
    bound to the policy that made it. Missing or failed required evidence is
    never replaced by confidence.
    """

    identity: str
    def evaluate(self, snapshot: JSON) -> JSON: ...


# -- routing and delivery policy ---------------------------------------------------------


@runtime_checkable
class RoutingPolicy(Protocol):
    """Recipients for a destination in the current actor and relationship context."""

    def recipients(self, sender: str, destination: JSON, actors: list[JSON], relations: list[JSON]) -> list[str]: ...


@runtime_checkable
class Clock(Protocol):
    """The current time as an ISO 8601 string."""

    def __call__(self) -> str: ...


Identifier = Callable[[], str]
"""Returns a new unique identifier on each call."""


@runtime_checkable
class SessionSelection(Protocol):
    """The eligible native session for one recipient, or ``None``."""

    def select(self, message: JSON, recipient: str, sessions: list[JSON]) -> str | None: ...


@runtime_checkable
class DeliveryScheduling(Protocol):
    """When a queued delivery is ready, and whether to dispatch as soon as it is enqueued."""

    dispatch_on_enqueue: bool
    def ready(self, delivery: JSON, session: JSON, now: str) -> bool: ...


@runtime_checkable
class DeliveryRetry(Protocol):
    """Whether another attempt is permitted after a definite failed attempt."""

    def permit(self, delivery: JSON, history: list[JSON]) -> bool: ...


@runtime_checkable
class ReceiptPolicy(Protocol):
    """Verification of complete exchange evidence; submission is not receipt."""

    def evaluate(self, snapshot: JSON, recipient: str, expectation: JSON) -> JSON: ...


# -- operator ports ---------------------------------------------------------------------
# Used by the operator layer to set up projects; the application core never calls
# them. Adapters are selected by name and options from the user's home.


@dataclass(frozen=True)
class WorktreeLocation:
    """One version-controlled working tree: its root, its private and shared metadata directories and branch.

    ``common_dir`` is shared by every working tree of one repository, so it
    identifies a repository on a machine.
    """

    root: str
    private_dir: str
    common_dir: str
    branch: str | None = None


@runtime_checkable
class VersionControl(Protocol):
    """Local version-control queries and the few operations the operator layer performs."""

    def worktree(self, path: str) -> WorktreeLocation | None:
        """The working tree containing ``path``, or ``None`` outside any repository."""
        ...

    def root_commits(self, path: str) -> frozenset[str]:
        """The history roots of the repository at ``path``; empty without history.

        Two repositories that share a root are clones of one project.
        """
        ...

    def remote_url(self, path: str, name: str = "origin") -> str | None:
        """The URL of remote ``name`` of the repository at ``path``, or ``None``."""
        ...

    def initialize(self, path: str) -> None:
        """Create an empty repository at ``path``."""
        ...


@runtime_checkable
class CompanionRecords(Protocol):
    """The records of one project in a companion, or the project-independent ones (``project`` is ``None``).

    Records are opaque bytes addressed by ``kind`` and ``key``. A kind is a
    collection owned by one operator capability (overlays, approvals, policies
    and launchers today; snapshots and telemetry archives later), which
    defines and versions its records' format. A new capability adds a kind;
    neither this port nor its adapters change. Kinds, keys and project names
    are names of letters, digits, ``.``, ``_`` and ``-``, not starting with a
    dot; any other name is refused with an ``OrchestrationError`` coded
    ``invalid_arguments``.
    """

    project: str | None

    def keys(self, kind: str) -> list[str]:
        """The keys present in ``kind``, sorted."""
        ...

    def read(self, kind: str, key: str) -> bytes | None:
        """The record ``kind/key``, or ``None`` when absent."""
        ...

    def write(self, kind: str, key: str, data: bytes, *, create_only: bool = False) -> bool:
        """Store ``kind/key`` atomically; with ``create_only`` an existing record is kept. Return whether it was written."""
        ...


@runtime_checkable
class Companion(Protocol):
    """The user's private companion: what they capture about their projects, kept away from the projects.

    The adapter chooses the storage and validates its location. Content is
    reached through scoped records (``records``); typed meaning belongs to the
    operator capabilities that own each kind.
    """

    location: str
    """A human-readable location, for reports."""

    def validate_location(self) -> str | None:
        """Why this location is unsafe (for example writable by the agents approvals guard against), or ``None``."""
        ...

    def exists(self) -> bool:
        """Whether a companion is present at the location."""
        ...

    def initialize(self) -> list[str]:
        """Create the companion if absent; return what was created. Existing content is never overwritten."""
        ...

    def records(self, project: str | None) -> CompanionRecords:
        """The records of ``project``, or the project-independent records for ``None``."""
        ...

    def remote(self) -> str | None:
        """Where the companion is published (a repository URL), or ``None``."""
        ...


@dataclass(frozen=True)
class HostingVisibility:
    """Whether a hosted repository is private: ``private``, ``public`` or ``unknown`` (with a reason)."""

    visibility: str
    repository: str | None = None
    reason: str | None = None


@runtime_checkable
class RepositoryHosting(Protocol):
    """Questions about where a repository is hosted. Never fails: unanswerable questions are ``unknown``."""

    def visibility(self, remote_url: str) -> HostingVisibility: ...
