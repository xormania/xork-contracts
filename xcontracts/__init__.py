"""Port contracts for Xorchestrate adapters.

``xcontracts.ports`` holds the ports, ``xcontracts.model`` the values and
errors they exchange, ``xcontracts.factories`` the adapter factory convention
and ``xcontracts.testing`` the conformance kit. The names below are re-exported
for convenience.
"""

from .factories import KINDS, AdapterFactory, AdapterKind, AdapterSelection, CompanionFactory, split_reference
from .model import JSON, Assessment, Capability, Conflict, OrchestrationError, Record, Verdict
from .ports import (
    AcceptancePolicy,
    ApplicationToolCallback,
    ApplicationToolSessionDriver,
    CapabilityProvider,
    Clock,
    Companion,
    CompanionRecords,
    DeliveryRetry,
    DeliveryScheduling,
    Evaluator,
    Guardrail,
    HostingVisibility,
    Identifier,
    ReceiptPolicy,
    RepositoryHosting,
    ResumableSessionDriver,
    RoutingPolicy,
    SessionDriver,
    SessionSelection,
    StateStore,
    TelemetrySink,
    Transaction,
    VersionControl,
    WorktreeLocation,
)

__version__ = "0.1.0"

__all__ = [
    "JSON", "AcceptancePolicy", "AdapterFactory", "AdapterKind", "AdapterSelection", "ApplicationToolCallback",
    "ApplicationToolSessionDriver", "Assessment", "Capability", "CapabilityProvider", "Clock", "Companion",
    "CompanionFactory", "CompanionRecords", "Conflict", "DeliveryRetry", "DeliveryScheduling", "Evaluator",
    "Guardrail", "HostingVisibility", "Identifier", "KINDS", "OrchestrationError", "ReceiptPolicy", "Record",
    "RepositoryHosting", "ResumableSessionDriver", "RoutingPolicy", "SessionDriver", "SessionSelection",
    "StateStore", "TelemetrySink", "Transaction", "Verdict", "VersionControl", "WorktreeLocation",
    "__version__", "split_reference",
]
