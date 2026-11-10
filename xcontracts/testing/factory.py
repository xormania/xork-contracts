"""Checks for the adapter factory convention (``xcontracts.factories``).

``construct`` builds an adapter exactly as a host does from a selection, so an
adapter author can confirm that a ``module:Name`` reference resolves, accepts
an options dict and yields something with the port's members::

    from xcontracts.testing import factory

    store = factory.construct("store", {"adapter": "my_package.storage:Store", "options": {"path": "/abs"}})
"""

from __future__ import annotations

import importlib
from copy import deepcopy
from typing import Any

from ..factories import KINDS, split_reference
from ._core import ContractViolation, expect


def port_members(port: type) -> set[str]:
    """The public method and attribute names a ``Protocol`` port declares, including inherited ones."""
    members: set[str] = set()
    for cls in port.__mro__:
        if cls is object or cls.__module__ in {"typing", "typing_extensions", "abc"}:
            continue
        names = set(vars(cls)) | set(getattr(cls, "__annotations__", {}))
        members |= {name for name in names if not name.startswith("_") or name == "__call__"}
    return members


def missing_members(subject: object, port: type) -> list[str]:
    """Port members ``subject`` lacks (methods must be callable), sorted."""
    missing = []
    for name in sorted(port_members(port)):
        if not hasattr(subject, name):
            missing.append(name)
        elif callable(getattr(port, name, None)) and not callable(getattr(subject, name)):
            missing.append(name)
    return missing


def load(reference: str) -> Any:
    """Import the factory a ``module:Name`` reference names, as a host does."""
    module, name = split_reference(reference)
    return getattr(importlib.import_module(module), name)


def construct(kind: str, selection: dict, **dependencies: Any) -> Any:
    """Construct ``selection`` (``{"adapter": "module:Name", "options": {...}}``) for ``kind``.

    The factory receives a deep copy of the options, plus the keyword
    dependencies its kind declares (``version_control`` for ``companion``).
    Raises ``ContractViolation`` when the adapter lacks a member of the kind's
    port; exceptions from the factory itself propagate.
    """
    expect(kind in KINDS, "FACTORY_KIND_IS_PUBLIC", kind)
    declared = KINDS[kind]
    expect(set(dependencies) == set(declared.dependencies), "FACTORY_DEPENDENCIES_MATCH_KIND",
           f"{kind} takes {declared.dependencies}, got {sorted(dependencies)}")
    options = selection.get("options", {})
    expect(isinstance(options, dict), "FACTORY_OPTIONS_ARE_AN_OBJECT")
    factory = load(selection["adapter"])
    adapter = factory(deepcopy(options), **dependencies)
    missing = missing_members(adapter, declared.port)
    if missing:
        raise ContractViolation("FACTORY_ADAPTER_IMPLEMENTS_PORT", f"{declared.port.__name__} lacks {missing}")
    return adapter
