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
  `StateStore`/`Transaction`, `TelemetrySink` (provisional, not selectable), `CapabilityProvider`,
  `SessionDriver`, `ResumableSessionDriver`, `ApplicationToolSessionDriver`,
  `ApplicationToolCallback`, `Evaluator`, `Guardrail`, `AcceptancePolicy`,
  `RoutingPolicy`, `Clock`, `Identifier`, `SessionSelection`,
  `DeliveryScheduling`, `DeliveryRetry`, `ReceiptPolicy`, `VersionControl`,
  `WorktreeLocation`, `Companion`, `CompanionRecords`, `RepositoryHosting` and
  `HostingVisibility`.
- The values and errors they exchange, moved from `xorchestrate.model`: `JSON`,
  `Record`, `Capability`, `Assessment`, `Verdict`, `OrchestrationError` and
  `Conflict`.
- The adapter factory convention (`xcontracts.factories`): selection format
  (`SelectionSpec`), `AdapterFactory`, `CompanionFactory`, the selectable `KINDS` and
  `split_reference`.
- The conformance kit (`xcontracts.testing`): `StateStore` checks (serialized
  and optimistic stores alike), operator port checks, factory construction
  checks and reference fakes. Every check has a fault witness.

### Compatibility

- First release. `TelemetrySink` is provisional: it passes host internals, is
  not in `KINDS`, and will be narrowed in a later 0.x minor release.
