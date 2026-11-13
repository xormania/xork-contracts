"""Fault witnesses: each check detects a deliberate defect in an otherwise conforming fake.

The healthy controls are in ``test_conformance.py``: the same checks pass
against the unmodified fakes.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests import contract_faults, faults
from xcontracts.model import Conflict
from xcontracts.testing import Check, ContractViolation, contracts, factory, fakes, operator, run, state_store

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


CONTRACT_WITNESSES = [
    (contract_faults.WrongVersionResolver, contracts.resolves_exact_definitions, "CONTRACT_EXACT_DEFINITION"),
    (contract_faults.MissingAsEmptyResolver, contracts.resolves_exact_definitions, "CONTRACT_ABSENCE_IS_NONE"),
    (contract_faults.DroppedArtifactsResolver, contracts.resolves_exact_definitions, "CONTRACT_EXACT_DEFINITION"),
    (contract_faults.SharedDefinitionResolver, contracts.returns_detached_definitions, "CONTRACT_RESULTS_DETACHED"),
    (contract_faults.ShallowDefinitionResolver, contracts.returns_detached_definitions, "CONTRACT_RESULTS_DETACHED"),
    (contract_faults.InvalidReferenceMissingResolver, contracts.refuses_invalid_references,
     "CONTRACT_INVALID_REFERENCE_REFUSED"),
    (contract_faults.ReusableContractResolver, contracts.close_is_idempotent_and_prevents_reuse,
     "CONTRACT_CLOSED_REFUSES_RESOLUTION"),
]


@pytest.mark.parametrize(("resolver", "check", "code"), CONTRACT_WITNESSES,
                         ids=lambda value: getattr(value, "__name__", str(value)))
def test_contract_checks_detect_their_fault(resolver, check, code):
    with pytest.raises(ContractViolation) as caught:
        check(resolver)
    assert caught.value.code == code
    check(fakes.MemoryContractResolver)


def test_definition_check_detects_a_provider_that_drops_one_role():
    example = contracts.sample_definitions()[0]
    for resolver_type, defective in ((contract_faults.OneSidedResolver, True), (fakes.MemoryContractResolver, False)):
        resolver = resolver_type([example])
        try:
            value = resolver.resolve(example["id"], example["version"])
            if defective:
                with pytest.raises(ContractViolation) as caught:
                    contracts.definition_is_valid(value)
                assert caught.value.code == "CONTRACT_DEFINITION_TWO_ROLES"
            else:
                contracts.definition_is_valid(value)
        finally:
            resolver.close()


@pytest.mark.parametrize("failure", ["contract_unavailable", "contract_denied", "contract_invalid"])
@pytest.mark.parametrize(("resolver", "code"), [
    (contract_faults.FailureAsAbsenceResolver, "CONTRACT_FAILURE_IS_NOT_ABSENCE"),
    (contract_faults.FailureAsSuccessResolver, "CONTRACT_FAILURE_IS_NOT_ABSENCE"),
    (contract_faults.WrongFailureCodeResolver, "CONTRACT_FAILURE_CODE"),
], ids=lambda value: getattr(value, "__name__", str(value)))
def test_failure_check_refuses_false_absence_success_or_misclassification(failure, resolver, code):
    with pytest.raises(ContractViolation) as caught:
        contracts.failure_is_distinct(resolver(failure), "known.exchange", "draft-a", failure)
    assert caught.value.code == code
    contracts.failure_is_distinct(contract_faults.KnownFailureResolver(failure), "known.exchange", "draft-a", failure)


def test_every_contract_check_has_a_fault_witness():
    witnessed = {case[1].name for case in CONTRACT_WITNESSES}
    assert witnessed == {check.name for check in contracts.CHECKS}
    witnessed |= {contracts.definition_is_valid.name, contracts.failure_is_distinct.name}
    assert witnessed == {value.name for value in vars(contracts).values() if isinstance(value, Check)}


def test_contract_checks_still_detect_their_faults_under_optimized_python():
    script = """
import json
from tests import contract_faults as faults
from xcontracts.testing import contracts, fakes, run
cases = [
    (contracts.resolves_exact_definitions, faults.WrongVersionResolver),
    (contracts.returns_detached_definitions, faults.SharedDefinitionResolver),
    (contracts.refuses_invalid_references, faults.InvalidReferenceMissingResolver),
    (contracts.close_is_idempotent_and_prevents_reuse, faults.ReusableContractResolver),
]
results = [run([check], resolver)[0] for check, resolver in cases]
definition = contracts.sample_definitions()[0]
definition['roles'].pop('requester')
results += run([contracts.definition_is_valid], definition)
results += run([contracts.failure_is_distinct], faults.FailureAsAbsenceResolver('contract_unavailable'),
               'known.exchange', 'draft-a', 'contract_unavailable')
healthy = run(contracts.CHECKS, fakes.MemoryContractResolver)
healthy += run([contracts.definition_is_valid], contracts.sample_definitions()[0])
healthy += run([contracts.failure_is_distinct], faults.KnownFailureResolver('contract_unavailable'),
               'known.exchange', 'draft-a', 'contract_unavailable')
print(json.dumps({'faults': [[item.passed, item.code] for item in results],
                  'healthy': [item.passed for item in healthy]}))
"""
    completed = subprocess.run([sys.executable, "-O", "-c", script], cwd=ROOT, capture_output=True, text=True,
                               timeout=60, check=True)
    assert json.loads(completed.stdout) == {
        "faults": [[False, code] for code in [
            "CONTRACT_EXACT_DEFINITION", "CONTRACT_RESULTS_DETACHED", "CONTRACT_INVALID_REFERENCE_REFUSED",
            "CONTRACT_CLOSED_REFUSES_RESOLUTION", "CONTRACT_DEFINITION_TWO_ROLES", "CONTRACT_FAILURE_IS_NOT_ABSENCE",
        ]],
        "healthy": [True] * 6,
    }
