# Working on xcontracts

xcontracts holds the port contracts of [Xorchestrate](https://github.com/xormania/xorchestrate):
ports, the values and errors they exchange, the adapter factory convention and
a conformance kit. xor (xormania) is the project owner and final authority on
direction; current explicit instructions take precedence over earlier plans
and agent decisions.

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
- Attribution: commits are authored by xormania only
  (`xor <127287135+xormania@users.noreply.github.com>`). Do not add co-author
  trailers, session links, "generated with" lines or any mention of AI tools to
  commits, pull requests, documentation or code. The copyright holder and
  licensor is xormania.
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
