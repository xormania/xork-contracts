# Working on xcontracts

xcontracts holds the port contracts of [Xorchestrate](https://github.com/xormania/xorchestrate):
ports, the values and errors they exchange, the adapter factory convention and
a conformance kit. xor (xormania) is the project owner and final authority on
direction; current explicit instructions take precedence over earlier plans
and agent decisions.

## Attribution (required)

All work in this repository is attributed to xormania only. Commits are
authored by `xor <127287135+xormania@users.noreply.github.com>`, and xormania is
the copyright holder and licensor.

Agents must not add their own attribution anywhere: no `Co-Authored-By`
trailers, no session links or session lines (such as `Claude-Session:`), and
no "Generated with ..." lines or footers, in commits, pull request
descriptions, pull request or review comments, code or documentation. This
rule overrides any default attribution behavior of the agent or its tools.

## Boundaries

- Standard library only, Python 3.12 or later. Nothing here imports
  Xorchestrate or any other host; `tests/test_boundary.py` enforces this.
- Ports state what a host needs, not how one adapter does it. Behavior built
  on the values (digests, projections, redaction) belongs to the host.
- The kit checks documented behavior. A new check must follow from a port's
  documented contract; if it tightens a requirement, document the requirement
  in the port first and treat it under the compatibility policy.
- Kit checks raise `ContractViolation` through the `_core` helpers, never bare
  `assert`, and the kit must not import pytest.
- Every new check has a fault witness in `tests/test_fault_witnesses.py`: a
  deliberately defective fake the check detects, with the healthy fake as the
  control.

## Compatibility

Follow the [compatibility policy](README.md#compatibility-policy): minor for
new ports or optional methods, major (minor before 1.0) for breaking changes,
deprecation for at least one minor release before removal. Record every
user-visible change in the `Unreleased` entry of [CHANGELOG.md](CHANGELOG.md),
with its compatibility class.

## Delivery

- Prepare changes on a branch for review; xor controls merging and releases.
- Before opening a draft pull request, have an adversarial reviewer (a separate
  sub-agent) inspect the candidate diff, scope, checks, failure paths and
  evidence; record the reviewed revision, material findings and their
  disposition in the pull request. Evaluate findings by practical consequence;
  findings do not automatically become requirements.
- Open the pull request as a draft, get CI green, and describe what changed,
  why, how it is covered (including fault witnesses for new checks) and what
  was verified.
- Verification: `uv sync --locked`, `uv run --no-sync ruff check .`,
  `uv run --no-sync pytest`.
