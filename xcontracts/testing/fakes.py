"""Reference fakes: small, complete implementations of the ports the kit checks.

They pass the conformance kit (xcontracts' own CI runs it against them), so an
adapter author can compare behavior, and a host's tests can use them in place
of real infrastructure. Each takes an ``options`` dict and follows the factory
convention, so it can be selected as ``xcontracts.testing.fakes:Name``.

They are test doubles: process-local, unoptimized and with no durability.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from ..model import JSON, Conflict, OrchestrationError, Record
from ..ports import HostingVisibility, VersionControl, WorktreeLocation

# -- StateStore ---------------------------------------------------------------------------


def _encode(data: object) -> str:
    if not isinstance(data, dict):
        raise OrchestrationError("State and event data must be JSON objects.")
    try:
        encoded = json.dumps(data, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        raise OrchestrationError("State and event data must contain valid JSON values.") from error
    # json.dumps accepts tuples and non-string keys, which would change type on read.
    pending: list[object] = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise OrchestrationError("JSON object keys must be strings.")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise OrchestrationError("State and event data must contain valid JSON values.")
    return encoded


def _identity(*names: object) -> None:
    for name in names:
        if not isinstance(name, str) or not name:
            raise OrchestrationError("Record kinds and keys must be nonempty strings.")
        try:
            name.encode("utf-8")
        except UnicodeError as error:
            raise OrchestrationError("Record kinds and keys must be valid Unicode strings.") from error


def _version(version: object) -> None:
    if type(version) is not int or version < 1:
        raise OrchestrationError("Expected version must be a positive integer.")


class _MemoryTransaction:
    def __init__(self, records: dict, events: list):
        self.records = dict(records)
        self.log = list(events)
        self.active = True
        self.aborted = False
        self.owner = threading.get_ident()

    def _check(self) -> None:
        if not self.active or self.owner != threading.get_ident():
            raise RuntimeError("Use a transaction only inside its context and on its owning thread.")
        if self.aborted:
            raise OrchestrationError("The transaction was aborted and cannot commit.", "transaction_aborted")

    def abort(self) -> None:
        if not self.active or self.owner != threading.get_ident():
            raise RuntimeError("Abort a transaction only inside its context and on its owning thread.")
        self.aborted = True

    def get(self, kind: str, key: str) -> Record | None:
        self._check()
        _identity(kind, key)
        item = self.records.get((kind, key))
        return None if item is None else Record(kind, key, json.loads(item[0]), item[1])

    def list(self, kind: str) -> list[Record]:
        self._check()
        _identity(kind)
        return [Record(kind, key, json.loads(data), version)
                for (stored, key), (data, version) in sorted(self.records.items()) if stored == kind]

    def put(self, kind: str, key: str, data: JSON, expected_version: int | None = None) -> Record:
        self._check()
        _identity(kind, key)
        if expected_version is not None:
            _version(expected_version)
        encoded = _encode(data)
        existing = self.records.get((kind, key))
        current = None if existing is None else existing[1]
        if current != expected_version:
            raise Conflict()
        version = 1 if existing is None else existing[1] + 1
        self.records[(kind, key)] = (encoded, version)
        return Record(kind, key, json.loads(encoded), version)

    def delete(self, kind: str, key: str, expected_version: int) -> None:
        self._check()
        _identity(kind, key)
        _version(expected_version)
        existing = self.records.get((kind, key))
        if existing is None or existing[1] != expected_version:
            raise Conflict()
        del self.records[(kind, key)]

    def emit(self, event: JSON) -> int:
        self._check()
        self.log.append(_encode(event))
        return len(self.log)

    def events(self, after: int = 0, limit: int = 100) -> list[JSON]:
        self._check()
        if type(after) is not int or after < 0 or type(limit) is not int or limit < 0:
            raise OrchestrationError("Event cursor and limit must be nonnegative integers.")
        return [{**json.loads(data), "seq": seq}
                for seq, data in enumerate(self.log[after:after + limit], start=after + 1)]


class MemoryStateStore:
    """A ``StateStore`` held in memory; transactions run one at a time."""

    def __init__(self, options: JSON | None = None):
        if options:
            raise OrchestrationError("MemoryStateStore takes no options.", "configuration_error")
        self._lock = threading.RLock()
        self._active = False
        self._closed = False
        self._records: dict = {}
        self._events: list = []

    @contextmanager
    def transaction(self) -> Iterator[_MemoryTransaction]:
        with self._lock:
            if self._closed:
                raise RuntimeError("The state store is closed.")
            if self._active:
                raise RuntimeError("Nested transactions are not supported.")
            self._active = True
            transaction = _MemoryTransaction(self._records, self._events)
            try:
                yield transaction
                transaction._check()
                self._records, self._events = transaction.records, transaction.log
            finally:
                transaction.active = False
                self._active = False

    def close(self) -> None:
        with self._lock:
            if self._active:
                raise RuntimeError("Cannot close a state store inside its transaction.")
            self._closed = True


# -- Companion ----------------------------------------------------------------------------

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not NAME.match(value):
        raise OrchestrationError(f"Invalid companion record {what}.", "invalid_arguments", {what: value})
    return value


class _MemoryRecords:
    def __init__(self, store: dict, project: str | None):
        self.store = store
        self.project = None if project is None else _name(project, "project")

    def keys(self, kind: str) -> list[str]:
        _name(kind, "kind")
        return sorted(key for (project, stored, key) in self.store if project == self.project and stored == kind)

    def read(self, kind: str, key: str) -> bytes | None:
        return self.store.get((self.project, _name(kind, "kind"), _name(key, "key")))

    def write(self, kind: str, key: str, data: bytes, *, create_only: bool = False) -> bool:
        address = (self.project, _name(kind, "kind"), _name(key, "key"))
        if create_only and address in self.store:
            return False
        self.store[address] = bytes(data)
        return True


class MemoryCompanion:
    """A ``Companion`` held in memory.

    Options: ``name`` (its location, default ``memory``), ``unsafe`` (a reason
    its location check reports, default none) and ``remote`` (its published URL).
    """

    def __init__(self, options: JSON | None = None, *, version_control: VersionControl | None = None):
        options = options or {}
        self.location = options.get("name", "memory")
        self.unsafe = options.get("unsafe")
        self.remote_url = options.get("remote")
        self.store: dict = {}
        self.initialized = False

    def validate_location(self) -> str | None:
        return self.unsafe

    def exists(self) -> bool:
        return self.initialized

    def initialize(self) -> list[str]:
        if self.initialized:
            return []
        self.initialized = True
        return [self.location]

    def records(self, project: str | None) -> _MemoryRecords:
        return _MemoryRecords(self.store, project)

    def remote(self) -> str | None:
        return self.remote_url


# -- VersionControl and RepositoryHosting ---------------------------------------------


class FakeVersionControl:
    """A ``VersionControl`` over declared repositories.

    Options: ``{"repositories": {name: {"worktrees": [root, ...], "roots": [...],
    "branch": ..., "remotes": {name: url}}}}``. The first worktree is the main one.
    """

    def __init__(self, options: JSON | None = None):
        self.repositories = (options or {}).get("repositories", {})

    def _find(self, path: str) -> tuple[str, WorktreeLocation] | None:
        for name, repository in self.repositories.items():
            for index, root in enumerate(repository["worktrees"]):
                if path == root or path.startswith(root.rstrip("/") + "/"):
                    common = f"/fake/{name}/.git"
                    private = common if index == 0 else f"{common}/worktrees/{index}"
                    return name, WorktreeLocation(root, private, common, repository.get("branch"))
        return None

    def worktree(self, path: str) -> WorktreeLocation | None:
        found = self._find(path)
        return None if found is None else found[1]

    def root_commits(self, path: str) -> frozenset[str]:
        found = self._find(path)
        return frozenset() if found is None else frozenset(self.repositories[found[0]].get("roots", []))

    def remote_url(self, path: str, name: str = "origin") -> str | None:
        found = self._find(path)
        return None if found is None else self.repositories[found[0]].get("remotes", {}).get(name)

    def initialize(self, path: str) -> None:
        self.repositories[path] = {"worktrees": [path], "roots": []}


class FakeHosting:
    """A ``RepositoryHosting`` answering from ``{"visibility": {remote_url: "private" | "public"}}``; others are unknown."""

    def __init__(self, options: JSON | None = None):
        self.answers = (options or {}).get("visibility", {})

    def visibility(self, remote_url: str) -> HostingVisibility:
        answer = self.answers.get(remote_url)
        if answer is None:
            return HostingVisibility("unknown", None, "the fake has no answer")
        return HostingVisibility(answer, remote_url.rsplit(":", 1)[-1].removesuffix(".git"))
