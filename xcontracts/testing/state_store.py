"""Conformance checks for ``StateStore`` and ``Transaction``.

Every check takes ``make_store``, a zero-argument callable returning a new,
empty store, and closes what it creates. Run them all with pytest::

    import pytest
    from xcontracts.testing import state_store

    @pytest.mark.parametrize("check", state_store.CHECKS, ids=str)
    def test_my_store_conforms(check, tmp_path):
        check(lambda: MyStore({"path": str(tmp_path / "state.db")}))

or without pytest: ``xcontracts.testing.run(state_store.CHECKS, make_store)``.

These checks state the port's documented behavior; persistence across
restarts, multiple processes and storage formats are adapter-specific and stay
with the adapter's own tests.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ..model import Conflict, OrchestrationError
from ..ports import StateStore
from ._core import ContractViolation, check, expect, expect_equal, raises

MakeStore = Callable[[], StateStore]


class _Store:
    def __init__(self, make_store: MakeStore):
        self.store = make_store()

    def __enter__(self) -> StateStore:
        return self.store

    def __exit__(self, *exc_info: object) -> None:
        self.store.close()


@check()
def create_replace_delete_and_stale_versions(make_store: MakeStore) -> None:
    """Creation, compare-and-replace and deletion honor versions; stale or missing versions conflict."""
    with _Store(make_store) as store, store.transaction() as tx:
        expect(tx.get("job", "missing") is None, "STORE_MISSING_RECORD_IS_NONE")
        first = tx.put("job", "one", {"value": 1})
        expect_equal(first.version, 1, "STORE_CREATION_STARTS_AT_VERSION_ONE")
        raises(Conflict, lambda: tx.put("job", "one", {"value": 2}), "STORE_DUPLICATE_CREATION_CONFLICTS")
        raises(Conflict, lambda: tx.put("job", "missing", {}, expected_version=1),
               "STORE_REPLACING_MISSING_RECORD_CONFLICTS")
        changed = tx.put("job", "one", {"value": 2}, expected_version=first.version)
        expect_equal(changed.version, 2, "STORE_REPLACEMENT_INCREMENTS_VERSION")
        raises(Conflict, lambda: tx.put("job", "one", {"value": 3}, expected_version=first.version),
               "STORE_STALE_REPLACEMENT_CONFLICTS")
        raises(Conflict, lambda: tx.delete("job", "one", expected_version=first.version),
               "STORE_STALE_DELETION_CONFLICTS")
        expect_equal(tx.get("job", "one"), changed, "STORE_REFUSED_WRITES_LEAVE_RECORD")
        tx.delete("job", "one", expected_version=changed.version)
        raises(Conflict, lambda: tx.delete("job", "one", expected_version=changed.version),
               "STORE_DELETING_MISSING_RECORD_CONFLICTS")
        expect(tx.get("job", "one") is None, "STORE_DELETION_REMOVES_RECORD")


@check()
def inputs_and_returned_records_are_detached(make_store: MakeStore) -> None:
    """Changing a written value or a returned record never changes stored data."""
    original = {"nested": [{"value": 1}], "unicode": "\ud800"}
    with _Store(make_store) as store:
        with store.transaction() as tx:
            created = tx.put("job", "one", original)
            original["nested"][0]["value"] = 9
            created.data["nested"][0]["value"] = 8
            fetched = tx.get("job", "one")
            expect_equal(fetched.data["nested"][0]["value"], 1, "STORE_RECORDS_ARE_DETACHED")
            fetched.data["nested"].append({"value": 7})
            listed = tx.list("job")
            listed[0].data["nested"][0]["value"] = 6
        with store.transaction() as tx:
            expect_equal(tx.get("job", "one").data, {"nested": [{"value": 1}], "unicode": "\ud800"},
                         "STORE_RECORDS_ARE_DETACHED")


@check()
def lists_are_sorted_and_scoped_to_kind(make_store: MakeStore) -> None:
    """``list`` returns one kind's records sorted by key."""
    with _Store(make_store) as store, store.transaction() as tx:
        tx.put("job", "z", {})
        tx.put("actor", "a", {})
        tx.put("job", "a", {})
        expect_equal([record.key for record in tx.list("job")], ["a", "z"], "STORE_LIST_SORTED_AND_SCOPED")
        expect_equal(tx.list("missing"), [], "STORE_LIST_UNKNOWN_KIND_EMPTY")


@check()
def exception_rolls_back_record_and_event_bundle(make_store: MakeStore) -> None:
    """Leaving a transaction by any exception discards its records and events together."""
    with _Store(make_store) as store:
        with store.transaction() as tx:
            original = tx.put("job", "one", {"phase": "initial"})
            tx.emit({"phase": "initial"})
        for failure in (RuntimeError, KeyboardInterrupt):
            def fail(failure: type[BaseException] = failure) -> None:
                with store.transaction() as tx:
                    tx.put("job", "one", {"phase": "changed"}, original.version)
                    tx.put("job", "two", {})
                    tx.emit({"phase": "changed"})
                    raise failure()
            raises(failure, fail, "STORE_TRANSACTION_PROPAGATES_ITS_EXCEPTION")
            with store.transaction() as tx:
                expect_equal(tx.get("job", "one"), original, "STORE_EXCEPTION_ROLLS_BACK_RECORDS")
                expect(tx.get("job", "two") is None, "STORE_EXCEPTION_ROLLS_BACK_RECORDS")
                expect_equal(tx.events(), [{"phase": "initial", "seq": 1}], "STORE_EXCEPTION_ROLLS_BACK_EVENTS")
        with store.transaction() as tx:
            tx.delete("job", "one", original.version)
            seq = tx.emit({"phase": "deleted"})
        with store.transaction() as tx:
            expect(tx.get("job", "one") is None, "STORE_COMMIT_PUBLISHES_DELETION")
            expect_equal(tx.events(after=1), [{"phase": "deleted", "seq": seq}], "STORE_COMMIT_PUBLISHES_EVENTS")


@check()
def abort_discards_the_transaction_even_if_the_caller_catches(make_store: MakeStore) -> None:
    """After ``abort``, nothing written in the transaction is published, whether or not leaving it raises."""
    with _Store(make_store) as store:
        with store.transaction() as tx:
            original = tx.put("job", "one", {"phase": "initial"})
        try:
            with store.transaction() as tx:
                tx.put("job", "one", {"phase": "changed"}, original.version)
                tx.emit({"phase": "changed"})
                tx.abort()
        except (OrchestrationError, RuntimeError):
            pass  # a store may report the aborted commit; it must not publish it
        with store.transaction() as tx:
            expect_equal(tx.get("job", "one"), original, "STORE_ABORT_DISCARDS_RECORDS")
            expect_equal(tx.events(), [], "STORE_ABORT_DISCARDS_EVENTS")


@check()
def events_are_detached_ordered_and_pageable(make_store: MakeStore) -> None:
    """Events get increasing ``seq`` values, replace a supplied ``seq`` and page by ``after``/``limit``."""
    event = {"nested": ["original"], "seq": "untrusted input"}
    with _Store(make_store) as store:
        with store.transaction() as tx:
            first = tx.emit(event)
            event["nested"].append("changed")
            tx.emit({"kind": "second"})
            returned = tx.events()
            expect_equal(returned[0], {"nested": ["original"], "seq": first}, "STORE_EVENTS_DETACHED_WITH_SEQ")
            returned[0]["nested"].append("changed")
        with store.transaction() as tx:
            third = tx.emit({"kind": "third"})
            expect_equal(tx.events(after=first, limit=1), [{"kind": "second", "seq": first + 1}],
                         "STORE_EVENTS_PAGE_AFTER_CURSOR")
            expect_equal(tx.events(after=first + 1), [{"kind": "third", "seq": third}], "STORE_EVENTS_PAGE_AFTER_CURSOR")
            expect_equal(tx.events(limit=0), [], "STORE_EVENTS_LIMIT_ZERO_EMPTY")
            expect_equal(tx.events(after=third + 100), [], "STORE_EVENTS_PAST_END_EMPTY")
            expect_equal(tx.events(limit=1)[0]["nested"], ["original"], "STORE_EVENTS_DETACHED_WITH_SEQ")


@check()
def invalid_json_rejected_without_partial_writes(make_store: MakeStore) -> None:
    """Non-JSON data is refused with ``OrchestrationError`` and writes nothing."""
    cycle: list = []
    cycle.append(cycle)
    invalid = [
        {"value": float("nan")}, {"value": float("inf")}, {"value": object()}, {"value": (1, 2)},
        {1: "non-string key"}, {"nested": [{False: "non-string key"}]}, {"value": cycle}, [], None,
    ]
    with _Store(make_store) as store, store.transaction() as tx:
        for value in invalid:
            raises(OrchestrationError, lambda value=value: tx.put("job", "invalid", value),
                   f"STORE_REFUSES_INVALID_RECORD_DATA {value!r}"[:120])
            raises(OrchestrationError, lambda value=value: tx.emit(value),
                   f"STORE_REFUSES_INVALID_EVENT_DATA {value!r}"[:120])
        expect(tx.get("job", "invalid") is None, "STORE_INVALID_DATA_WRITES_NOTHING")
        expect_equal(tx.events(), [], "STORE_INVALID_DATA_WRITES_NOTHING")


@check()
def invalid_identifiers_versions_and_pagination(make_store: MakeStore) -> None:
    """Empty, non-string or non-UTF-8-encodable keys, non-positive or non-int versions and negative cursors are refused."""
    with _Store(make_store) as store, store.transaction() as tx:
        for key in (None, "", 2, "\ud800"):
            raises(OrchestrationError, lambda key=key: tx.put("job", key, {}), f"STORE_REFUSES_KEY {key!r}")
        for version in (True, 0, -1, 1.5, "1"):
            raises(OrchestrationError, lambda version=version: tx.put("job", "one", {}, version),
                   f"STORE_REFUSES_VERSION {version!r}")
            raises(OrchestrationError, lambda version=version: tx.delete("job", "one", version),
                   f"STORE_REFUSES_VERSION {version!r}")
        for after, limit in ((-1, 1), (1, -1), (True, 1), (1, 1.5)):
            raises(OrchestrationError, lambda after=after, limit=limit: tx.events(after, limit),
                   f"STORE_REFUSES_EVENT_PAGE {(after, limit)!r}")


@check()
def transaction_lifetime_thread_ownership_and_nesting(make_store: MakeStore) -> None:
    """Nested transactions, close inside a transaction, foreign threads and use after exit raise ``RuntimeError``."""
    with _Store(make_store) as store:
        with store.transaction() as tx:
            def nested() -> None:
                with store.transaction():
                    pass
            raises(RuntimeError, nested, "STORE_REFUSES_NESTED_TRANSACTION")
            raises(RuntimeError, store.close, "STORE_REFUSES_CLOSE_INSIDE_TRANSACTION")
            with ThreadPoolExecutor(max_workers=1) as pool:
                raises(RuntimeError, lambda: pool.submit(tx.get, "job", "one").result(timeout=5),
                       "STORE_TRANSACTION_OWNED_BY_ITS_THREAD")
            tx.put("job", "one", {})
        for name, operation in (
            ("get", lambda: tx.get("job", "one")), ("list", lambda: tx.list("job")),
            ("put", lambda: tx.put("job", "two", {})), ("delete", lambda: tx.delete("job", "one", 1)),
            ("emit", lambda: tx.emit({})), ("events", lambda: tx.events()),
        ):
            raises(RuntimeError, operation, f"STORE_TRANSACTION_UNUSABLE_AFTER_EXIT {name}")


@check()
def close_is_idempotent_and_prevents_reuse(make_store: MakeStore) -> None:
    """``close`` may be repeated; a closed store refuses transactions."""
    store = make_store()
    store.close()
    store.close()

    def reuse() -> None:
        with store.transaction():
            pass
    raises(RuntimeError, reuse, "STORE_CLOSED_REFUSES_TRANSACTIONS")


@check()
def concurrent_stale_snapshots_allow_exactly_one_winner(make_store: MakeStore) -> None:
    """Two writers replacing the same version: one commits, the other conflicts and leaves no event."""
    with _Store(make_store) as store:
        with store.transaction() as tx:
            tx.put("job", "one", {"winner": None})
        barrier = threading.Barrier(2, timeout=5)

        def replace(winner: str) -> str | None:
            with store.transaction() as tx:
                previous = tx.get("job", "one")
            barrier.wait()
            try:
                with store.transaction() as tx:
                    tx.put("job", "one", {"winner": winner}, previous.version)
                    tx.emit({"winner": winner})
                return winner
            except Conflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(replace, ["first", "second"]))
        winners = [result for result in results if result is not None]
        expect_equal(len(winners), 1, "STORE_CONCURRENT_REPLACEMENT_HAS_ONE_WINNER")
        with store.transaction() as tx:
            expect_equal(tx.get("job", "one").data["winner"], winners[0], "STORE_CONCURRENT_REPLACEMENT_HAS_ONE_WINNER")
            expect_equal(tx.events(), [{"winner": winners[0], "seq": 1}], "STORE_CONFLICT_LEAVES_NO_EVENT")


@check()
def concurrent_transactional_updates_keep_events_consistent(make_store: MakeStore) -> None:
    """Serialized read-modify-write from several threads loses no update and keeps events in commit order."""
    with _Store(make_store) as store:
        with store.transaction() as tx:
            tx.put("counter", "one", {"count": 0})

        def increment(_: int) -> None:
            for _ in range(15):
                with store.transaction() as tx:
                    previous = tx.get("counter", "one")
                    count = previous.data["count"] + 1
                    tx.put("counter", "one", {"count": count}, previous.version)
                    tx.emit({"count": count})

        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in [pool.submit(increment, index) for index in range(4)]:
                error = future.exception(timeout=60)
                if error is not None:
                    raise ContractViolation("STORE_SERIALIZES_CONCURRENT_TRANSACTIONS",
                                            f"{type(error).__name__}: {error}") from error
        with store.transaction() as tx:
            expect_equal(tx.get("counter", "one").data["count"], 60, "STORE_SERIALIZES_CONCURRENT_TRANSACTIONS")
            expect_equal(tx.events(), [{"count": count, "seq": count} for count in range(1, 61)],
                         "STORE_EVENTS_FOLLOW_COMMIT_ORDER")


CHECKS = (
    create_replace_delete_and_stale_versions,
    inputs_and_returned_records_are_detached,
    lists_are_sorted_and_scoped_to_kind,
    exception_rolls_back_record_and_event_bundle,
    abort_discards_the_transaction_even_if_the_caller_catches,
    events_are_detached_ordered_and_pageable,
    invalid_json_rejected_without_partial_writes,
    invalid_identifiers_versions_and_pagination,
    transaction_lifetime_thread_ownership_and_nesting,
    close_is_idempotent_and_prevents_reuse,
    concurrent_stale_snapshots_allow_exactly_one_winner,
    concurrent_transactional_updates_keep_events_consistent,
)
"""Every ``StateStore`` check, in a stable order."""
