"""Fault witnesses: each check detects a deliberate defect in an otherwise conforming fake.

The healthy controls are in ``test_conformance.py``: the same checks pass
against the unmodified fakes.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests import faults
from xcontracts.testing import ContractViolation, factory, fakes, operator, state_store

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("store", "check", "code"), [
    (faults.BlindReplaceStore, state_store.create_replace_delete_and_stale_versions,
     "STORE_STALE_REPLACEMENT_CONFLICTS"),
    (faults.ConflictlessDeleteStore, state_store.create_replace_delete_and_stale_versions,
     "STORE_STALE_DELETION_CONFLICTS"),
    (faults.SharedRecordStore, state_store.inputs_and_returned_records_are_detached, "STORE_RECORDS_ARE_DETACHED"),
    (faults.IgnoredAbortStore, state_store.abort_discards_the_transaction_even_if_the_caller_catches,
     "STORE_ABORT_DISCARDS_RECORDS"),
    (faults.CommitOnErrorStore, state_store.exception_rolls_back_record_and_event_bundle,
     "STORE_EXCEPTION_ROLLS_BACK_RECORDS"),
    (faults.UnserializedStore, state_store.concurrent_stale_snapshots_allow_exactly_one_winner,
     "STORE_CONCURRENT_REPLACEMENT_HAS_ONE_WINNER"),
], ids=lambda value: getattr(value, "__name__", str(value)))
def test_state_store_checks_detect_their_fault(store, check, code):
    with pytest.raises(ContractViolation) as caught:
        check(store)
    assert caught.value.code == code
    check(fakes.MemoryStateStore)  # healthy control with the same inputs


def test_companion_checks_detect_overwriting_and_permissive_names():
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.OverwritingCompanion())
    assert caught.value.code == "COMPANION_CREATE_ONLY_KEEPS_EXISTING"
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.PermissiveCompanion())
    assert caught.value.code == "COMPANION_REFUSES_INVALID_NAME"


def test_version_control_check_detects_split_common_directories():
    options = {"repositories": {"repo": {"worktrees": ["/w/repo", "/w/linked"], "roots": ["abc"]}}}
    with pytest.raises(ContractViolation) as caught:
        operator.version_control(faults.SplitVersionControl(options), "/w/repo", "/w/linked", "/w/elsewhere")
    assert caught.value.code == "VCS_WORKTREES_SHARE_COMMON_DIR"
    operator.version_control(fakes.FakeVersionControl(options), "/w/repo", "/w/linked", "/w/elsewhere")


def test_hosting_check_detects_unknown_without_reason():
    answers = {"visibility": {"git@h:o/p.git": "private", "https://h/o/q": "public"}}
    with pytest.raises(ContractViolation) as caught:
        operator.repository_hosting(faults.SilentHosting(answers), "git@h:o/p.git", "https://h/o/q", ["x"])
    assert caught.value.code == "HOSTING_UNANSWERABLE_IS_UNKNOWN_WITH_REASON"


def test_factory_check_detects_a_missing_port_member_and_an_internal_kind():
    with pytest.raises(ContractViolation) as caught:
        factory.construct("version_control", {"adapter": "xcontracts.testing.fakes:FakeHosting"})
    assert caught.value.code == "FACTORY_ADAPTER_IMPLEMENTS_PORT" and "worktree" in caught.value.detail
    with pytest.raises(ContractViolation) as caught:
        factory.construct("state_engine", {"adapter": "xcontracts.testing.fakes:MemoryStateStore"})
    assert caught.value.code == "FACTORY_KIND_IS_PUBLIC"
    with pytest.raises(ContractViolation) as caught:
        factory.construct("companion", {"adapter": "xcontracts.testing.fakes:MemoryCompanion"})
    assert caught.value.code == "FACTORY_DEPENDENCIES_MATCH_KIND"
    assert isinstance(factory.construct("version_control", {"adapter": "xcontracts.testing.fakes:FakeVersionControl"}),
                      fakes.FakeVersionControl)


def test_checks_still_fail_under_optimized_python():
    """The kit does not rely on ``assert``, which ``python -O`` removes."""
    script = ("from tests import faults\nfrom xcontracts.testing import run, state_store\n"
              "result, = run([state_store.create_replace_delete_and_stale_versions], faults.BlindReplaceStore)\n"
              "print(result.passed, result.code)\n")
    completed = subprocess.run([sys.executable, "-O", "-c", script], cwd=ROOT, capture_output=True, text=True,
                               timeout=60, check=True)
    assert completed.stdout.split() == ["False", "STORE_STALE_REPLACEMENT_CONFLICTS"]
