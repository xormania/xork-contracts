"""Fault witnesses: each check detects a deliberate defect in an otherwise conforming fake.

The healthy controls are in ``test_conformance.py``: the same checks pass
against the unmodified fakes.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests import faults
from xcontracts.model import Conflict
from xcontracts.testing import ContractViolation, factory, fakes, operator, run, state_store

ROOT = Path(__file__).resolve().parents[1]


WITNESSES = [
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
    (faults.DeleteAppliedImmediatelyStore, state_store.exception_rolls_back_record_and_event_bundle,
     "STORE_EXCEPTION_ROLLS_BACK_DELETIONS"),
    (faults.DeleteAppliedImmediatelyStore, state_store.abort_discards_the_transaction_even_if_the_caller_catches,
     "STORE_ABORT_DISCARDS_DELETIONS"),
    (faults.UnsortedListStore, state_store.lists_are_sorted_and_scoped_to_kind, "STORE_LIST_SORTED_AND_SCOPED"),
    (faults.CallerSequenceStore, state_store.events_are_detached_ordered_and_pageable,
     "STORE_EVENTS_DETACHED_WITH_SEQ"),
    (faults.TupleAcceptingStore, state_store.invalid_json_rejected_without_partial_writes,
     "STORE_REFUSES_INVALID_RECORD_DATA"),
    (faults.BooleanVersionStore, state_store.invalid_identifiers_versions_and_pagination, "STORE_REFUSES_VERSION"),
    (faults.ReusableTransactionStore, state_store.transaction_lifetime_thread_ownership_and_nesting,
     "STORE_TRANSACTION_UNUSABLE_AFTER_EXIT"),
    (faults.ReopeningStore, state_store.close_is_idempotent_and_prevents_reuse, "STORE_CLOSED_REFUSES_TRANSACTIONS"),
    (faults.LosingUpdatesStore, state_store.concurrent_transactional_updates_keep_events_consistent,
     "STORE_SERIALIZES_CONCURRENT_TRANSACTIONS"),
    (faults.FailingListStore, state_store.lists_are_sorted_and_scoped_to_kind, "UNEXPECTED_EXCEPTION"),
]


@pytest.mark.parametrize(("store", "check", "code"), WITNESSES, ids=lambda value: getattr(value, "__name__", str(value)))
def test_state_store_checks_detect_their_fault(store, check, code):
    with pytest.raises(ContractViolation) as caught:
        check(store)
    assert caught.value.code == code
    check(fakes.MemoryStateStore)  # healthy control with the same inputs


def test_every_state_store_check_has_a_fault_witness():
    witnessed = {case[1].name for case in WITNESSES}
    assert witnessed == {check.name for check in state_store.CHECKS}


@pytest.mark.parametrize("check", state_store.CHECKS, ids=str)
def test_an_optimistic_snapshot_isolation_store_passes(check):
    """Healthy alternative: overlapping transactions with retry-safe conflicts at commit conform."""
    store = faults.SnapshotIsolationStore
    check(store)


def test_the_optimistic_store_really_conflicts_and_the_kit_retries():
    """Without retrying retry-safe conflicts, the concurrent check would fail against this store."""
    conflicts = []

    class Counting(faults.SnapshotIsolationStore):
        def transaction(self):
            context = super().transaction()

            class Wrapped:
                def __enter__(inner):
                    return context.__enter__()

                def __exit__(inner, *exc_info):
                    try:
                        return context.__exit__(*exc_info)
                    except Conflict as conflict:
                        conflicts.append(conflict.details.get("retry_safe"))
                        raise
            return Wrapped()
    state_store.concurrent_transactional_updates_keep_events_consistent(Counting)
    assert conflicts and all(conflicts)


def test_run_reports_an_unexpected_adapter_error_as_a_named_violation():
    result, = run([state_store.lists_are_sorted_and_scoped_to_kind], faults.FailingListStore)
    assert (result.passed, result.code) == (False, "UNEXPECTED_EXCEPTION")
    assert result.detail.startswith("lists_are_sorted_and_scoped_to_kind: KeyError")


def test_companion_check_detects_a_trailing_newline_name():
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.NewlineNameCompanion())
    assert caught.value.code == "COMPANION_REFUSES_INVALID_NAME" and "key\\n" in caught.value.detail


def test_companion_checks_detect_overwriting_and_permissive_names():
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.OverwritingCompanion())
    assert caught.value.code == "COMPANION_CREATE_ONLY_KEEPS_EXISTING"
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.PermissiveCompanion())
    assert caught.value.code == "COMPANION_REFUSES_INVALID_NAME"


def test_version_control_check_detects_split_common_directories():
    options = {"repositories": {"repo": {"worktrees": ["/w/repo", "/w/linked"], "roots": ["abc"], "head": "abc"}}}
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


@pytest.mark.parametrize(("companion", "code"), [
    (faults.FlatListingCompanion, "COMPANION_FLAT_KEYS_ARE_SINGLE_NAMES"),
    (faults.PrefixConflictCompanion, "COMPANION_REFUSES_PREFIX_CONFLICT"),
    (faults.SingleNameKeyCompanion, "COMPANION_KEYS_MAY_BE_PATHS"),
    (faults.EmptySegmentCompanion, "COMPANION_REFUSES_INVALID_KEY"),
], ids=lambda value: getattr(value, "__name__", str(value)))
def test_companion_path_key_checks_detect_their_fault(companion, code):
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(companion())
    assert caught.value.code == code
    operator.companion_records(fakes.MemoryCompanion())  # healthy control


@pytest.mark.parametrize(("vcs", "code"), [
    (faults.HeadlessVersionControl, "VCS_REVISION_OF_REPOSITORY_WITH_HISTORY"),
    (faults.LeakyRevisionVersionControl, "VCS_NO_REVISION_OUTSIDE_REPOSITORY"),
], ids=lambda value: getattr(value, "__name__", str(value)))
def test_version_control_revision_checks_detect_their_fault(vcs, code):
    options = {"repositories": {"repo": {"worktrees": ["/w/repo", "/w/linked"], "roots": ["abc"], "head": "abc"}}}
    with pytest.raises(ContractViolation) as caught:
        operator.version_control(vcs(options), "/w/repo", "/w/linked", "/w/elsewhere")
    assert caught.value.code == code


def test_scope_check_detects_a_companion_that_mixes_scopes_by_path():
    with pytest.raises(ContractViolation) as caught:
        operator.companion_scopes_are_isolated(faults.MixedScopeCompanion())
    assert caught.value.code == "COMPANION_SHARED_RECORD_SEEN_BY_PROJECT"
    operator.companion_scopes_are_isolated(fakes.MemoryCompanion())  # healthy control


def test_companion_check_detects_non_bytes_records():
    with pytest.raises(ContractViolation) as caught:
        operator.companion_records(faults.TextAcceptingCompanion())
    assert caught.value.code == "COMPANION_RECORDS_ARE_BYTES_ONLY"
