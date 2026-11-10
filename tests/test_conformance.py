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
    operator.companion_scopes_are_isolated(fakes.MemoryCompanion())


def test_memory_companion_refuses_a_kind_in_the_other_scope():
    companion = fakes.MemoryCompanion()
    companion.records("alpha").write("archive", "a", b"x")
    for call in (lambda: companion.records(None).read("archive", "a"),
                 lambda: companion.records(None).keys("archive"),
                 lambda: companion.records(None).write("archive", "a", b"y")):
        try:
            call()
        except Exception as error:  # noqa: BLE001
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("cross-scope use accepted")


def test_fake_version_control_conforms():
    vcs = fakes.FakeVersionControl({"repositories": {"repo": {"worktrees": ["/w/repo", "/w/linked"], "roots": ["abc"],
                                                              "head": "abc"}}})
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
                                                           "roots": ["abc"], "head": "abc"}}})

    class Resolving(fakes.FakeVersionControl):
        def worktree(self, path):
            return vcs.worktree(os.path.realpath(path))

        def root_commits(self, path):
            return vcs.root_commits(os.path.realpath(path))

        def revision(self, path):
            return vcs.revision(os.path.realpath(path))
    alias = tmp_path / "alias"
    operator.version_control(Resolving(), alias / "repo", alias / "linked", tmp_path)


def test_hosting_may_omit_the_repository_name():
    """``HostingVisibility.repository`` is optional, so an adapter that does not name it conforms."""
    from xcontracts.ports import HostingVisibility

    class Unnamed:
        def visibility(self, remote_url):
            answer = {PRIVATE: "private", PUBLIC: "public"}.get(remote_url)
            return HostingVisibility(answer) if answer else HostingVisibility("unknown", reason="no answer")
    operator.repository_hosting(Unnamed(), PRIVATE, PUBLIC, ["https://example.test/owner/missing"])


def test_fake_version_control_resolves_the_innermost_worktree():
    vcs = fakes.FakeVersionControl({"repositories": {
        "outer": {"worktrees": ["/repo", "/repo/linked"], "roots": ["outer-root"], "head": "outer-head",
                  "remotes": {"origin": "outer-url"}},
        "nested": {"worktrees": ["/repo/vendor/lib"], "roots": ["nested-root"], "head": "nested-head",
                   "remotes": {"origin": "nested-url"}}}})
    linked = vcs.worktree("/repo/linked/src/file.py")
    assert linked.root == "/repo/linked" and linked.private_dir == "/fake/outer/.git/worktrees/1"
    assert vcs.worktree("/repo/src").root == "/repo"
    assert vcs.worktree("/repo/vendor/lib/x.py").root == "/repo/vendor/lib"
    assert vcs.root_commits("/repo/vendor/lib/x.py") == frozenset({"nested-root"})
    assert vcs.remote_url("/repo/vendor/lib") == "nested-url" and vcs.revision("/repo/vendor/lib") == "nested-head"
    assert vcs.revision("/repo/linked") == "outer-head" and vcs.root_commits("/repo") == frozenset({"outer-root"})


def test_fake_version_control_follows_the_git_rules_for_real_paths(tmp_path):
    """Backed by real directories, the fake answers like the git adapter: files via their parent, nothing
    for a path whose parent is missing, and inside ``.git`` the repository but no worktree."""
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    (repository / "src").mkdir()
    (repository / "src" / "file.py").write_text("")
    vcs = fakes.FakeVersionControl({"repositories": {"r": {"worktrees": [str(repository)], "roots": ["abc"],
                                                           "head": "abc", "remotes": {"origin": "url"}}}})
    for inside in (repository / "src" / "file.py", repository / "src" / "new.py", repository / "src"):
        assert vcs.worktree(str(inside)).root == str(repository) and vcs.revision(str(inside)) == "abc"
        assert vcs.root_commits(str(inside)) == frozenset({"abc"}) and vcs.remote_url(str(inside)) == "url"
    missing = repository / "missing" / "deeper" / "x"
    assert vcs.worktree(str(missing)) is None and vcs.revision(str(missing)) is None
    assert vcs.root_commits(str(missing)) == frozenset() and vcs.remote_url(str(missing)) is None
    for metadata in (repository / ".git", repository / ".git" / "HEAD"):
        assert vcs.worktree(str(metadata)) is None
        assert vcs.revision(str(metadata)) == "abc" and vcs.root_commits(str(metadata)) == frozenset({"abc"})
