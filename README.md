# xcontracts

Port contracts for [Xorchestrate](https://github.com/xormania/xorchestrate):
the interfaces, value types, errors and adapter factory convention that
adapters implement, plus a conformance test kit.

```sh
pip install xcontracts            # or: uv add xcontracts
```

Python 3.12 or later. No dependencies beyond the standard library.

## What is in it

| Module | Contents |
| --- | --- |
| `xcontracts.ports` | The ports, as `typing.Protocol` classes (runtime-checkable for member presence) |
| `xcontracts.model` | Values and errors the ports exchange: `JSON`, `Record`, `Capability`, `Assessment`, `Verdict`, `OrchestrationError`, `Conflict` |
| `xcontracts.factories` | How a host selects and constructs adapters: the `{"adapter": "module:Name", "options": {...}}` selection (`SelectionSpec`), `AdapterFactory`, `CompanionFactory` and the selectable `KINDS` |
| `xcontracts.testing` | Conformance checks for adapter authors, and reference fakes that pass them |

The ports by purpose:

| Purpose | Ports |
| --- | --- |
| State and observation | `StateStore`, `Transaction`, `TelemetrySink` (provisional: published for typing, not yet implementable by third parties) |
| Capabilities, sessions, judgment | `CapabilityProvider`, `SessionDriver`, `ResumableSessionDriver`, `ApplicationToolSessionDriver`, `ApplicationToolCallback`, `Evaluator`, `Guardrail`, `AcceptancePolicy` |
| Routing and delivery | `RoutingPolicy`, `SessionSelection`, `DeliveryScheduling`, `DeliveryRetry`, `ReceiptPolicy`, `Clock`, `Identifier` |
| Operator (project setup) | `VersionControl` (`WorktreeLocation`), `Companion`, `CompanionRecords`, `RepositoryHosting` (`HostingVisibility`) |

## Writing an adapter

An adapter is a class or function that takes an options dict and returns
something implementing one port. It does not need to inherit from the port:

```python
from xcontracts import Verdict


class DenyActions:
    """Deny the configured actions; allow everything else."""

    def __init__(self, options):
        self.denied = frozenset(options.get("actions", []))

    def evaluate(self, action, context):
        if action in self.denied:
            return Verdict(False, f"{action} is disabled by policy")
        return Verdict(True)
```

Install it next to the host and select it by reference in configuration:

```json
{"guardrail": {"adapter": "my_package.policies:DenyActions", "options": {"actions": ["start_session"]}}}
```

The factory receives a private copy of `options` as its only argument
(`companion` factories also receive `version_control=`). Xorchestrate renders
placeholders such as `${data}` in option strings first and refuses a
non-string `cwd` for providers and evaluators; see the docstring of
[`xcontracts/factories.py`](xcontracts/factories.py) for the exact rules,
including which options a host resolves and what it closes.

## Checking an adapter

Run the kit from your own tests. The checks do not import pytest, and raise
`ContractViolation` (an `AssertionError`) with a stable code:

```python
import pytest
from xcontracts.testing import factory, operator, state_store


@pytest.mark.parametrize("check", state_store.CHECKS, ids=str)
def test_store_conforms(check, tmp_path):
    check(lambda: MyStore({"path": str(tmp_path / "state.db")}))


def test_companion_conforms(tmp_path):
    operator.companion_records(MyCompanion({"path": str(tmp_path / "c")}, version_control=MyVCS({})))


def test_selectable_by_reference():
    factory.construct("guardrail", {"adapter": "my_package.policies:DenyActions", "options": {}})
```

Every check raises `ContractViolation`; an unexpected exception from the
adapter is reported as `UNEXPECTED_EXCEPTION` naming the check. Every check
has a fault witness in this repository: a deliberately defective fake it
detects, next to the reference fake it accepts.

Behavioral checks exist for `StateStore`/`Transaction`, `Companion`,
`VersionControl` and `RepositoryHosting`. For the other ports,
`factory.construct` and `factory.missing_members` check structure; their
behavior is exercised by the host's own tests. `xcontracts.testing.fakes` has
reference implementations (`MemoryStateStore`, `MemoryCompanion`,
`FakeVersionControl`, `FakeHosting`) usable as test doubles.

## Compatibility policy

Versions follow [Semantic Versioning](https://semver.org/):

- **Patch** (`x.y.Z`): documentation, kit fixes that do not tighten a
  requirement, bug fixes in the fakes.
- **Minor** (`x.Y.0` from 1.0 on): additive changes. New ports, new optional
  ports or optional methods (a host must keep working with adapters that lack
  them), new value fields with defaults, new kit checks for already-documented
  behavior, deprecations.
- **Major** (`X.0.0` from 1.0 on): breaking changes. Removing or renaming a port, method,
  field or error code; adding a required method to an existing port; changing
  a signature or a documented guarantee.

Before 1.0, both additive and breaking changes bump the minor version (0.1 to
0.2), and fixes bump the patch. A host therefore pins one minor series,
`xcontracts>=0.N,<0.N+1` (today `>=0.1,<0.2`), and widens it deliberately after
reading the changelog's **Compatibility** section.

Anything removed is deprecated first for at least one minor release: the
deprecation is listed in the changelog's **Compatibility** section, with the
release that removes it, and where practical emits `DeprecationWarning`.
`TelemetrySink` is provisional in 0.x and may change in a minor release with a
changelog note.

## Development

```sh
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync pytest
```

See [releases](docs/releases.md) for publishing and [AGENTS.md](AGENTS.md) for
contribution rules.

Copyright 2026 xormania. Licensed under the [Apache License, Version 2.0](LICENSE);
see [NOTICE](NOTICE).
