"""Values and errors exchanged across the ports; independent of infrastructure.

These are plain values: an adapter receives and returns them, and a host
(Xorchestrate) relies on their shape. Behavior built on top of them, such as
canonical digests, public record projection or error redaction, belongs to the
host, not to this contract.

Error codes used by the public ports:

``conflict``
    A compare-and-replace version did not match (``Conflict``). With
    ``details["retry_safe"]`` true, repeating the same operation is safe.
``invalid_arguments``
    A companion record kind, key or project name is not a valid name.
``invalid_request``
    The default code for any other expected failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JSON = dict[str, Any]
"""A JSON object: string keys, JSON-compatible values, finite numbers."""


class OrchestrationError(ValueError):
    """An expected failure with a machine-readable ``code`` and JSON ``details``.

    Its message is public: a host may show it to callers. Adapters raise it (or
    a subclass) for failures a caller can act on; any other exception is treated
    as an unverified external failure whose text is not shown.
    """

    def __init__(self, message: str, code: str = "invalid_request", details: JSON | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class Conflict(OrchestrationError):
    """A stale or missing compare-and-replace version; code ``conflict``."""

    def __init__(self, message: str = "The record changed; read its current version before retrying.", *,
                 retry_safe: bool = False):
        super().__init__(message, "conflict", {"retry_safe": True} if retry_safe else None)


@dataclass(frozen=True)
class Record:
    """One stored record: its ``kind``, ``key``, JSON object ``data`` and positive ``version``."""

    kind: str
    key: str
    data: JSON
    version: int


@dataclass(frozen=True)
class Capability:
    """A discoverable operation: its name, description, JSON Schema input and annotations.

    Annotations are supplied metadata (for example ``readOnlyHint``), not proof
    of what the implementation does.
    """

    name: str
    description: str
    input_schema: JSON = field(default_factory=lambda: {"type": "object"})
    annotations: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class Assessment:
    """An evaluator's judgment: an outcome, optional confidence, rationale and evidence.

    Missing confidence stays ``None``; it is never read as certainty.
    """

    outcome: str
    confidence: float | None = None
    rationale: str = ""
    evidence: tuple[Any, ...] = ()
    details: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """A guardrail decision. ``review`` marks an action blocked pending explicit review."""

    allowed: bool
    reason: str = ""
    review: bool = False
    details: JSON = field(default_factory=dict)
