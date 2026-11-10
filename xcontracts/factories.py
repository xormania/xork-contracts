"""The adapter factory convention: how a host selects and constructs an adapter.

Selection
---------
A configuration selects an adapter for one *kind* (a configuration section or
operator setting) with an object::

    {"adapter": "<alias or reference>", "options": {...}, "enabled": true}

``adapter`` is either a built-in alias the host defines (for Xorchestrate,
``sqlite``, ``rules``, ``codex`` and so on) or a *reference* to a trusted,
installed factory: ``"package.module:Name"``. The host imports
``package.module`` and reads its top-level attribute ``Name`` (the text after
the first ``:``; dotted attribute paths are not followed). ``options`` is a JSON
object, ``{}`` when omitted. ``enabled`` is a boolean; ``false`` leaves a named
entry (of ``providers``, ``sessions`` or ``evaluators``) or the ``telemetry``
section unconstructed, while the other single-adapter sections are always
constructed. Operator settings (``companion``, ``version_control``,
``repository_hosting``) take only ``adapter`` and ``options``.

Configuration is trusted local input. Tool arguments and provider output never
choose a factory.

Construction
------------
The host calls the factory with a private deep copy of the options as its only
positional argument and returns what it builds as the adapter::

    adapter = factory(options)

Exceptions to that rule, exactly:

- ``companion``: ``factory(options, *, version_control=...)`` receives the
  host's selected ``VersionControl`` as a keyword argument (see
  ``CompanionFactory``).
- Some of the host's own built-in aliases receive host internals (in Xorchestrate,
  the built-in ``local`` telemetry collector receives ``resolve=`` and the
  built-in ``tool`` evaluator receives the constructed providers). A
  ``module:Name`` reference never receives them.

Options reach a referenced factory exactly as written: the host resolves
relative paths only for its own built-in aliases, so a factory that accepts
paths should require absolute ones or document what they are relative to. A
factory validates its own options and raises ``OrchestrationError`` (code
``configuration_error`` or ``invalid_request``) with a public message for
invalid ones; any other exception is reported without its text.

Xorchestrate closes each project adapter that has ``close()`` when its runtime
ends, in reverse construction order.

Host hooks
----------
Xorchestrate also calls a few optional ``bind_*`` methods when an adapter has
them (``bind_telemetry``, ``bind_observer``, ``bind_state_engine``). Their
arguments are host internals; they are not part of this contract and may change
with the host. ``bind_application_tools`` and ``bind_application_replay`` are
part of ``ApplicationToolSessionDriver``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, Protocol, Required, TypedDict, TypeVar, runtime_checkable

from . import ports
from .model import JSON

AdapterT_co = TypeVar("AdapterT_co", covariant=True)

SEPARATOR = ":"


class AdapterSelection(TypedDict):
    """``{"adapter": ..., "options": {...}, "enabled": ...}`` as written in configuration."""

    adapter: Required[str]
    options: NotRequired[JSON]
    enabled: NotRequired[bool]


@runtime_checkable
class AdapterFactory(Protocol[AdapterT_co]):
    """A factory for every kind except ``companion``: ``factory(options) -> adapter``.

    A class whose ``__init__`` takes ``options`` is a factory, as is a function.
    """

    def __call__(self, options: JSON, /) -> AdapterT_co: ...


@runtime_checkable
class CompanionFactory(Protocol):
    """``factory(options, *, version_control) -> Companion``."""

    def __call__(self, options: JSON, /, *, version_control: ports.VersionControl) -> ports.Companion: ...


@dataclass(frozen=True)
class AdapterKind:
    """One selectable kind: the port its adapters implement and how it is selected.

    ``scope`` is ``project`` for a project configuration section and
    ``operator`` for a setting in the user's home. ``named`` kinds are maps of
    names to selections; the others select one adapter. ``dependencies`` lists
    the keyword arguments the factory receives besides ``options``.
    """

    name: str
    port: type
    scope: Literal["project", "operator"]
    named: bool = False
    dependencies: tuple[str, ...] = ()


KINDS: dict[str, AdapterKind] = {kind.name: kind for kind in (
    AdapterKind("store", ports.StateStore, "project"),
    AdapterKind("telemetry", ports.TelemetrySink, "project"),
    AdapterKind("providers", ports.CapabilityProvider, "project", named=True),
    AdapterKind("sessions", ports.SessionDriver, "project", named=True),
    AdapterKind("evaluators", ports.Evaluator, "project", named=True),
    AdapterKind("guardrail", ports.Guardrail, "project"),
    AdapterKind("routing", ports.RoutingPolicy, "project"),
    AdapterKind("acceptance", ports.AcceptancePolicy, "project"),
    AdapterKind("session_selection", ports.SessionSelection, "project"),
    AdapterKind("delivery_scheduler", ports.DeliveryScheduling, "project"),
    AdapterKind("retry_policy", ports.DeliveryRetry, "project"),
    AdapterKind("receipt_policy", ports.ReceiptPolicy, "project"),
    AdapterKind("companion", ports.Companion, "operator", dependencies=("version_control",)),
    AdapterKind("version_control", ports.VersionControl, "operator"),
    AdapterKind("repository_hosting", ports.RepositoryHosting, "operator"),
)}
"""Every kind a third-party factory may implement, by name."""


def split_reference(reference: str) -> tuple[str, str]:
    """Split ``"package.module:Name"`` into ``("package.module", "Name")``.

    Raises ``ValueError`` unless both parts are nonempty. Only the first ``:``
    separates them, as the host splits it.
    """
    if not isinstance(reference, str) or SEPARATOR not in reference:
        raise ValueError(f"Adapter reference {reference!r} is not 'module:Name'.")
    module, name = reference.split(SEPARATOR, 1)
    if not module or not name:
        raise ValueError(f"Adapter reference {reference!r} is not 'module:Name'.")
    return module, name
