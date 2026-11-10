"""Deliberately defective subjects: each breaks one documented requirement of a fake that conforms."""

import threading
from contextlib import contextmanager

from xcontracts.model import Conflict, Record
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
