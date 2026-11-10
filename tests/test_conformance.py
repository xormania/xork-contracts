"""Healthy controls: the reference fakes pass every check of the kit."""

import pytest

from xcontracts.testing import fakes, operator, run, state_store

PRIVATE, PUBLIC = "git@example.test:owner/private.git", "https://example.test/owner/public"


@pytest.mark.parametrize("check", state_store.CHECKS, ids=str)
def test_memory_state_store_conforms(check):
    check(fakes.MemoryStateStore)


def test_run_reports_every_state_store_check_without_pytest():
    results = run(state_store.CHECKS, fakes.MemoryStateStore)
    assert [result.name for result in results] == [check.name for check in state_store.CHECKS]
    assert all(result.passed for result in results), results


def test_memory_companion_conforms():
    operator.companion_records(fakes.MemoryCompanion())


def test_fake_version_control_conforms():
    vcs = fakes.FakeVersionControl({"repositories": {"repo": {"worktrees": ["/w/repo", "/w/linked"], "roots": ["abc"]}}})
    operator.version_control(vcs, "/w/repo", "/w/linked", "/w/elsewhere")


def test_fake_hosting_conforms():
    hosting = fakes.FakeHosting({"visibility": {PRIVATE: "private", PUBLIC: "public"}})
    operator.repository_hosting(hosting, PRIVATE, PUBLIC, ["https://example.test/owner/missing"])
