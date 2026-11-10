"""Healthy controls: the reference fakes pass every check of the kit."""

import os

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


def test_version_control_roots_compare_after_resolving_symlinks(tmp_path):
    """An adapter may report a worktree's resolved root; the check accepts it for a symlinked path."""
    (tmp_path / "real" / "repo").mkdir(parents=True)
    (tmp_path / "real" / "linked").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    real = str((tmp_path / "real").resolve())
    vcs = fakes.FakeVersionControl({"repositories": {"r": {"worktrees": [f"{real}/repo", f"{real}/linked"],
                                                           "roots": ["abc"]}}})

    class Resolving(fakes.FakeVersionControl):
        def worktree(self, path):
            return vcs.worktree(os.path.realpath(path))

        def root_commits(self, path):
            return vcs.root_commits(os.path.realpath(path))
    alias = tmp_path / "alias"
    operator.version_control(Resolving(), alias / "repo", alias / "linked", tmp_path)
