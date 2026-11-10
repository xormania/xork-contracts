"""Deliberately defective subjects: each breaks one documented requirement of a fake that conforms."""

import re
import threading
from contextlib import contextmanager

from xcontracts.model import Conflict, OrchestrationError, Record
from xcontracts.testing import fakes


class BlindReplaceStore(fakes.MemoryStateStore):
    """Replaces a record whatever expected version it is given."""

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            original = tx.put

            def put(kind, key, data, expected_version=None):
                current = tx.get(kind, key)
                if current is not None and expected_version is not None:
                    expected_version = current.version
                return original(kind, key, data, expected_version)
            tx.put = put
            yield tx


class SharedRecordStore(fakes.MemoryStateStore):
    """Returns the stored object itself, so callers can change stored data."""

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            cache = {}
            original_put, original_get = tx.put, tx.get

            def put(kind, key, data, expected_version=None):
                record = original_put(kind, key, data, expected_version)
                cache[(kind, key)] = data
                return Record(kind, key, data, record.version)

            def get(kind, key):
                record = original_get(kind, key)
                if record is not None and (kind, key) in cache:
                    return Record(kind, key, cache[(kind, key)], record.version)
                return record
            tx.put, tx.get = put, get
            yield tx


class IgnoredAbortStore(fakes.MemoryStateStore):
    """Treats abort as a no-op."""

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            tx.abort = lambda: None
            yield tx


class CommitOnErrorStore(fakes.MemoryStateStore):
    """Commits whatever was written even when the transaction body raises."""

    @contextmanager
    def transaction(self):
        with self._lock:
            transaction = fakes._MemoryTransaction(self._records, self._events)
            try:
                yield transaction
            finally:
                self._records, self._events = transaction.records, transaction.log
                transaction.active = False


class UnserializedStore(fakes.MemoryStateStore):
    """Lets transactions overlap and commits their snapshots without checking versions again.

    Transactions opened by worker threads wait for a second one to take its
    snapshot, so two writers always overlap; the main thread never waits.
    """

    def __init__(self, options=None):
        super().__init__(options)
        self._overlap = threading.Barrier(2, timeout=5)

    @contextmanager
    def transaction(self):
        if self._closed:
            raise RuntimeError("closed")
        transaction = fakes._MemoryTransaction(self._records, self._events)
        if threading.current_thread() is not threading.main_thread():
            self._overlap.wait()
        try:
            yield transaction
            self._records, self._events = transaction.records, transaction.log
        finally:
            transaction.active = False


class OverwritingCompanion(fakes.MemoryCompanion):
    """Ignores ``create_only``."""

    def records(self, project):
        records = super().records(project)
        original = records.write
        records.write = lambda kind, key, data, *, create_only=False: original(kind, key, data)
        return records


class PermissiveCompanion(fakes.MemoryCompanion):
    """Accepts any kind or key."""

    def records(self, project):
        records = super().records(project if project is None or "/" not in project else None)
        store = records.store
        records.read = lambda kind, key: store.get((records.project, kind, key))
        return records


class SplitVersionControl(fakes.FakeVersionControl):
    """Gives each worktree of one repository its own common directory."""

    def worktree(self, path):
        location = super().worktree(path)
        if location is None:
            return None
        return type(location)(location.root, location.private_dir, location.private_dir, location.branch)


class SilentHosting(fakes.FakeHosting):
    """Reports unknown repositories without a reason."""

    def visibility(self, remote_url):
        report = super().visibility(remote_url)
        return type(report)(report.visibility, report.repository, None)


class ConflictlessDeleteStore(fakes.MemoryStateStore):
    """Deletes regardless of the expected version."""

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            def delete(kind, key, expected_version):
                if (kind, key) not in tx.records:
                    raise Conflict()
                del tx.records[(kind, key)]
            tx.delete = delete
            yield tx


class _Patched(fakes.MemoryStateStore):
    """Applies ``patch(tx)`` to every transaction it opens."""

    def patch(self, tx):
        raise NotImplementedError

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            self.patch(tx)
            yield tx


class DeleteAppliedImmediatelyStore(_Patched):
    """Deletes from the committed state at once, so a rolled-back or aborted delete is kept."""

    def patch(self, tx):
        original = tx.delete

        def delete(kind, key, expected_version):
            original(kind, key, expected_version)
            self._records.pop((kind, key), None)
        tx.delete = delete


class UnsortedListStore(_Patched):
    """Lists records in reverse key order."""

    def patch(self, tx):
        original = tx.list
        tx.list = lambda kind: list(reversed(original(kind)))


class CallerSequenceStore(_Patched):
    """Keeps an emitter-supplied ``seq`` instead of the store's sequence."""

    def patch(self, tx):
        original_emit, original_events = tx.emit, tx.events
        supplied = {}

        def emit(event):
            sequence = original_emit(event)
            if "seq" in event:
                supplied[sequence] = event["seq"]
            return sequence

        def events(after=0, limit=100):
            return [{**row, "seq": supplied.get(row["seq"], row["seq"])} for row in original_events(after, limit)]
        tx.emit, tx.events = emit, events


class TupleAcceptingStore(_Patched):
    """Accepts tuples, which JSON would silently turn into lists."""

    def patch(self, tx):
        original = tx.put

        def put(kind, key, data, expected_version=None):
            if isinstance(data, dict) and any(isinstance(value, tuple) for value in data.values()):
                data = {name: list(value) if isinstance(value, tuple) else value for name, value in data.items()}
            return original(kind, key, data, expected_version)
        tx.put = put


class BooleanVersionStore(_Patched):
    """Accepts ``True`` as version 1."""

    def patch(self, tx):
        original = tx.put

        def put(kind, key, data, expected_version=None):
            return original(kind, key, data, 1 if expected_version is True else expected_version)
        tx.put = put


class ReusableTransactionStore(fakes.MemoryStateStore):
    """Leaves a transaction usable after its context ends."""

    @contextmanager
    def transaction(self):
        with super().transaction() as tx:
            yield tx
        tx.active = True


class ReopeningStore(fakes.MemoryStateStore):
    """Ignores close."""

    def close(self):
        pass


class LosingUpdatesStore(UnserializedStore):
    """Two overlapping read-modify-write transactions both commit: one update is lost."""


class FailingListStore(_Patched):
    """Raises an unexpected error from ``list``."""

    def patch(self, tx):
        def fail(kind):
            raise KeyError(kind)
        tx.list = fail


class NewlineNameCompanion(fakes.MemoryCompanion):
    """Validates names with ``re.match`` and ``$``, which accepts a trailing newline."""

    def records(self, project):
        records = super().records(project)
        loose = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
        store = records.store

        def name(value):
            if not isinstance(value, str) or not loose.match(value):
                raise OrchestrationError("Invalid name.", "invalid_arguments")
            return value
        records.read = lambda kind, key: store.get((records.project, name(kind), fakes._key(key)))
        return records


class SnapshotIsolationStore:
    """A correct optimistic store: transactions overlap on snapshots; the later conflicting commit is retry-safe.

    This is a healthy alternative, not a fault: it must pass every check.
    Transactions opened by worker threads briefly wait for a second one to
    take its snapshot, so concurrent checks really overlap and the later
    commit really conflicts.
    """

    def __init__(self, options=None):
        self._overlap = threading.Barrier(2)
        self._lock = threading.Lock()
        self._records, self._events = {}, []
        self._closed, self._open = False, 0
        self._local = threading.local()

    @contextmanager
    def transaction(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("The state store is closed.")
            if getattr(self._local, "active", False):
                raise RuntimeError("Nested transactions are not supported.")
            snapshot, base = dict(self._records), list(self._events)
            self._open += 1
        self._local.active = True
        tx = fakes._MemoryTransaction(snapshot, base)
        if threading.current_thread() is not threading.main_thread():
            try:
                self._overlap.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                self._overlap.reset()
        try:
            yield tx
            tx._check()
            with self._lock:
                changed = {key for key in set(snapshot) | set(tx.records) if snapshot.get(key) != tx.records.get(key)}
                emitted = tx.log[len(base):]
                if any(self._records.get(key) != snapshot.get(key) for key in changed) or (
                        emitted and len(self._events) != len(base)):
                    raise Conflict("A concurrent transaction committed first.", retry_safe=True)
                for key in changed:
                    if key in tx.records:
                        self._records[key] = tx.records[key]
                    else:
                        self._records.pop(key, None)
                self._events.extend(emitted)
        finally:
            tx.active = False
            self._local.active = False
            with self._lock:
                self._open -= 1

    def close(self):
        with self._lock:
            if self._open:
                raise RuntimeError("Cannot close a state store inside a transaction.")
            self._closed = True


class FlatListingCompanion(fakes.MemoryCompanion):
    """Lists nested keys even without ``recursive``."""

    def records(self, project):
        records = super().records(project)
        original = records.keys
        records.keys = lambda kind, *, recursive=False: original(kind, recursive=True)
        return records


class PrefixConflictCompanion(fakes.MemoryCompanion):
    """Lets a record also be the prefix of another key."""

    def records(self, project):
        records = super().records(project)
        store = records.store

        def write(kind, key, data, *, create_only=False):
            address = (records.project, fakes._name(kind, "kind"), fakes._key(key))
            if create_only and address in store:
                return False
            store[address] = bytes(data)
            return True
        records.write = write
        return records


class SingleNameKeyCompanion(fakes.MemoryCompanion):
    """Keeps the old rule that a key is a single name."""

    def records(self, project):
        records = super().records(project)
        original = records.write

        def write(kind, key, data, *, create_only=False):
            fakes._name(key, "key")
            return original(kind, key, data, create_only=create_only)
        records.write = write
        return records


class EmptySegmentCompanion(fakes.MemoryCompanion):
    """Drops empty segments (``a//b`` becomes ``a/b``) instead of refusing the key."""

    def records(self, project):
        records = super().records(project)
        original_read, original_write = records.read, records.write

        def tidy(key):
            return "/".join(part for part in key.split("/") if part) if isinstance(key, str) and key.strip("/") else key
        records.read = lambda kind, key: original_read(kind, tidy(key))
        records.write = lambda kind, key, data, *, create_only=False: original_write(kind, tidy(key), data,
                                                                                     create_only=create_only)
        return records


class HeadlessVersionControl(fakes.FakeVersionControl):
    """Reports no revision even for a repository with history."""

    def revision(self, path):
        return None


class LeakyRevisionVersionControl(fakes.FakeVersionControl):
    """Reports a revision for any path, even outside every repository."""

    def revision(self, path):
        return super().revision(path) or "abc"
