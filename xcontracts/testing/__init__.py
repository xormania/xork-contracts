"""Conformance kit: checks that adapters behave as their ports require.

Modules:

- ``state_store``: ``StateStore``/``Transaction`` checks (``state_store.CHECKS``);
- ``operator``: ``Companion``, ``VersionControl`` and ``RepositoryHosting`` checks;
- ``factory``: constructing an adapter through the factory convention and
  checking it has its port's members;
- ``fakes``: reference implementations that pass the kit.

Checks are plain callables that raise ``ContractViolation`` (an
``AssertionError``), so they work under pytest, unittest or a plain script and
do not import pytest. ``run`` collects results without a test framework.

Ports without a behavioral kit in this release (the session, capability,
policy and telemetry ports) can still be checked structurally with
``factory.missing_members``.
"""

from ._core import Check, ContractViolation, Result, expect, raises, run

__all__ = ["Check", "ContractViolation", "Result", "expect", "raises", "run"]
