# Changelog

Each release has an entry headed `## X.Y.Z`. Its **Compatibility** section says
which changes are additive, which are breaking (major releases only) and what
is deprecated, with the release in which it will be removed. See the
[compatibility policy](README.md#compatibility-policy) and
[releases](docs/releases.md).

## Unreleased

### Compatibility

- None yet.

## 0.1.0

The date is set when the release is tagged.

### Added

- The public ports of Xorchestrate, moved from `xorchestrate.ports`:
  `StateStore`/`Transaction`, `TelemetrySink` (provisional), `CapabilityProvider`,
  `SessionDriver`, `ResumableSessionDriver`, `ApplicationToolSessionDriver`,
  `ApplicationToolCallback`, `Evaluator`, `Guardrail`, `AcceptancePolicy`,
  `RoutingPolicy`, `Clock`, `Identifier`, `SessionSelection`,
  `DeliveryScheduling`, `DeliveryRetry`, `ReceiptPolicy`, `VersionControl`,
  `WorktreeLocation`, `Companion`, `CompanionRecords`, `RepositoryHosting` and
  `HostingVisibility`.
- The values and errors they exchange, moved from `xorchestrate.model`: `JSON`,
  `Record`, `Capability`, `Assessment`, `Verdict`, `OrchestrationError` and
  `Conflict`.
- The adapter factory convention (`xcontracts.factories`): selection format,
  `AdapterFactory`, `CompanionFactory`, the selectable `KINDS` and
  `split_reference`.
- The conformance kit (`xcontracts.testing`): `StateStore` checks, operator
  port checks, factory construction checks and reference fakes.

### Compatibility

- First release. `TelemetrySink` is provisional: its result shapes may be
  narrowed in a later 0.x minor release.
