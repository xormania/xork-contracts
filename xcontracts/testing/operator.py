"""Conformance checks for the operator ports: ``Companion``, ``VersionControl`` and ``RepositoryHosting``.

Each check receives a subject (a real adapter or a fake) and the inputs it
needs, and states the port's contract from its documented behavior::

    from xcontracts.testing import operator

    operator.companion_records(MyCompanion({"path": str(tmp_path / "companion")}, version_control=vcs))
    operator.version_control(MyVCS({}), repository, linked_worktree, unrelated_directory)
    operator.repository_hosting(MyHosting({}), private_url, public_url, [unanswerable_url])
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from os import PathLike

from ..ports import Companion, RepositoryHosting, VersionControl
from ._core import ContractViolation, check, expect, expect_equal

INVALID_NAMES = ("", ".hidden", "_private", "-dash", "../escape", "a/b", "spaced name", "key\n", "x" * 129)
"""Kind, key and project names every companion must refuse with ``invalid_arguments``."""


def _refused(call, name: str) -> None:
    try:
        call()
    except Exception as error:  # noqa: BLE001 - any refusal with the right code satisfies the contract
        if getattr(error, "code", None) != "invalid_arguments":
            raise ContractViolation("COMPANION_INVALID_NAME_CODE",
                                    f"{name!r} refused with {type(error).__name__} {error}") from error
    else:
        raise ContractViolation("COMPANION_REFUSES_INVALID_NAME", f"{name!r} was accepted")


@check()
def companion_records(companion: Companion) -> None:
    """Project-scoped, extensible records: kinds and keys, project isolation, atomic create-only.

    ``companion`` must not exist yet; the check initializes it.
    """
    expect(companion.initialize() is not None, "COMPANION_INITIALIZE_REPORTS_CREATED")
    expect(companion.exists(), "COMPANION_EXISTS_AFTER_INITIALIZE")
    expect_equal(companion.initialize(), [], "COMPANION_INITIALIZE_NEVER_RECREATES")
    alpha, beta, shared = companion.records("alpha"), companion.records("beta"), companion.records(None)
    expect(alpha.project == "alpha" and shared.project is None, "COMPANION_RECORDS_NAME_THEIR_PROJECT")
    expect(alpha.read("overlay", "overlay.json") is None, "COMPANION_ABSENT_RECORD_IS_NONE")
    expect_equal(alpha.keys("overlay"), [], "COMPANION_EMPTY_KIND_HAS_NO_KEYS")
    expect(alpha.write("overlay", "overlay.json", b'{"a": 1}') is True, "COMPANION_WRITE_REPORTS_WRITTEN")
    expect_equal(alpha.read("overlay", "overlay.json"), b'{"a": 1}', "COMPANION_READS_WHAT_WAS_WRITTEN")
    expect(beta.read("overlay", "overlay.json") is None, "COMPANION_PROJECTS_ARE_ISOLATED")
    expect(shared.read("overlay", "overlay.json") is None, "COMPANION_PROJECT_RECORDS_ARE_NOT_SHARED_RECORDS")
    expect(alpha.write("overlay", "overlay.json", b"kept", create_only=True) is False,
           "COMPANION_CREATE_ONLY_KEEPS_EXISTING")
    expect_equal(alpha.read("overlay", "overlay.json"), b'{"a": 1}', "COMPANION_CREATE_ONLY_KEEPS_EXISTING")
    expect(alpha.write("overlay", "overlay.json", b"replaced") is True, "COMPANION_WRITE_REPLACES")
    expect_equal(alpha.read("overlay", "overlay.json"), b"replaced", "COMPANION_WRITE_REPLACES")
    for key in ("b.json", "a.json"):
        shared.write("policies", key, b"{}")
    expect_equal(shared.keys("policies"), ["a.json", "b.json"], "COMPANION_KEYS_ARE_SORTED")
    # A capability added later is just another kind: no port or adapter change.
    expect(alpha.write("snapshot-archive", "bundle-1", b"\x00\x01") is True, "COMPANION_KINDS_ARE_OPEN")
    expect_equal(alpha.keys("snapshot-archive"), ["bundle-1"], "COMPANION_KINDS_ARE_OPEN")
    expect_equal(alpha.read("snapshot-archive", "bundle-1"), b"\x00\x01", "COMPANION_RECORDS_ARE_BYTES")
    for name in INVALID_NAMES:
        _refused(lambda name=name: alpha.read(name, "key"), name)
        _refused(lambda name=name: alpha.write("kind", name, b"x"), name)
        _refused(lambda name=name: companion.records(name or "/"), name)


@check()
def version_control(vcs: VersionControl, repository: str | PathLike, linked: str | PathLike,
                    unrelated_directory: str | PathLike) -> None:
    """``repository`` and ``linked`` are two worktrees of one repository with history; ``unrelated_directory`` is in none."""
    main, other = vcs.worktree(str(repository)), vcs.worktree(str(linked))
    expect(main is not None and other is not None, "VCS_FINDS_WORKTREES")
    expect_equal((os.path.realpath(main.root), os.path.realpath(other.root)),
                 (os.path.realpath(repository), os.path.realpath(linked)), "VCS_WORKTREE_ROOTS")
    expect(main.common_dir == other.common_dir, "VCS_WORKTREES_SHARE_COMMON_DIR")
    expect(main.private_dir != other.private_dir, "VCS_WORKTREES_HAVE_PRIVATE_DIRS")
    expect(vcs.worktree(str(unrelated_directory)) is None, "VCS_OUTSIDE_REPOSITORY_IS_NONE")
    roots = vcs.root_commits(str(repository))
    expect(roots and roots == vcs.root_commits(str(linked)), "VCS_WORKTREES_SHARE_ROOT_COMMITS")
    expect_equal(vcs.root_commits(str(unrelated_directory)), frozenset(), "VCS_NO_ROOTS_OUTSIDE_REPOSITORY")


@check()
def repository_hosting(hosting: RepositoryHosting, private_url: str, public_url: str,
                       unanswerable_urls: Iterable[str]) -> None:
    """Known repositories report ``private``/``public`` with a name; anything else is ``unknown`` with a reason."""
    for url, expected in ((private_url, "private"), (public_url, "public")):
        report = hosting.visibility(url)
        expect_equal(report.visibility, expected, f"HOSTING_REPORTS_VISIBILITY {url}")
        expect(report.repository, "HOSTING_NAMES_THE_REPOSITORY", url)
    for url in unanswerable_urls:
        report = hosting.visibility(url)
        expect(report.visibility == "unknown" and report.reason, "HOSTING_UNANSWERABLE_IS_UNKNOWN_WITH_REASON",
               f"{url}: {report!r}")


CHECKS = (companion_records, version_control, repository_hosting)
