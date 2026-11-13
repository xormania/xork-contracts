"""Conformance checks for the language-neutral contract-access agreement.

``CHECKS`` receive a fixture factory: ``factory(definitions) -> resolver``.
It provisions those definitions in an isolated provider and returns its reader;
it need not be the adapter's constructor. This does not add a publication method
to the read-only port. Each check closes the reader it acquires.

``failure_is_distinct`` instead receives a reader whose backend is already in
the named failure condition. Resolution describes obligations, not proof that
either role or any pair of implementations fulfills them.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from ..contracts import ContractDefinition
from ..model import OrchestrationError
from ..ports import ContractResolver
from ._core import check, expect, expect_equal, raises

Factory = Callable[[list[ContractDefinition]], ContractResolver]


def sample_definitions() -> list[ContractDefinition]:
    """Fresh small corpus with opaque versions and distinct exact identities."""
    first: ContractDefinition = {
        "schema_version": "1", "id": "Example/Exchange", "version": "draft-A",
        "roles": {
            "requester": {"obligations": ["Supply an exact request identity."]},
            "responder": {"obligations": ["Retain the request identity in the result."]},
        },
        "artifacts": {
            "source": {
                "format": "cue", "purpose": "definition",
                "content": "#Request: {id: string}\n#Response: {request_id: string}\n",
                "selector": "#Request",
            },
            "request-schema": {
                "format": "json-schema", "purpose": "derived",
                "content": '{"type":"object","required":["id"],"properties":{"id":{"type":"string"}}}',
            },
            "request-example": {
                "format": "application/x-example-opaque", "purpose": "example",
                "content": "  identity=example-1\n",
            },
        },
    }
    second = deepcopy(first)
    second["version"] = "draft-B"
    second["roles"]["responder"]["obligations"].append("Report completion separately from acceptance.")
    other = deepcopy(first)
    other["id"] = " Example/Exchange "
    other["roles"]["requester"]["obligations"] = ["Treat this as a distinct agreement."]
    return [first, second, other]


@check()
def definition_is_valid(document: object) -> None:
    """A v1 definition carries an exact identity and obligations for two named roles."""
    expect(type(document) is dict, "CONTRACT_DEFINITION_OBJECT")
    required = {"schema_version", "id", "version", "roles"}
    expect(required <= set(document) <= required | {"artifacts"}, "CONTRACT_DEFINITION_FIELDS")
    expect(type(document["schema_version"]) is str and document["schema_version"] == "1",
           "CONTRACT_DEFINITION_SCHEMA")
    for name in ("id", "version"):
        expect(type(document[name]) is str and bool(document[name]), "CONTRACT_DEFINITION_REFERENCE", name)
    roles = document["roles"]
    expect(type(roles) is dict and len(roles) == 2, "CONTRACT_DEFINITION_TWO_ROLES")
    for name, role in roles.items():
        expect(type(name) is str and bool(name), "CONTRACT_DEFINITION_ROLE_NAME")
        expect(type(role) is dict and set(role) == {"obligations"}, "CONTRACT_DEFINITION_ROLE_FIELDS")
        obligations = role["obligations"]
        expect(type(obligations) is list and bool(obligations), "CONTRACT_DEFINITION_OBLIGATIONS")
        expect(all(type(item) is str and bool(item) for item in obligations), "CONTRACT_DEFINITION_OBLIGATION_TEXT")
    artifacts = document.get("artifacts", {})
    expect(type(artifacts) is dict, "CONTRACT_DEFINITION_ARTIFACTS")
    for name, artifact in artifacts.items():
        expect(type(name) is str and bool(name), "CONTRACT_DEFINITION_ARTIFACT_NAME")
        required_artifact = {"format", "purpose", "content"}
        expect(type(artifact) is dict and required_artifact <= set(artifact) <= required_artifact | {"selector"},
               "CONTRACT_DEFINITION_ARTIFACT_FIELDS")
        for field in ("format", "content", "selector"):
            if field != "selector" or field in artifact:
                expect(type(artifact[field]) is str and bool(artifact[field]),
                       f"CONTRACT_DEFINITION_ARTIFACT_{field.upper()}")
        expect(type(artifact["purpose"]) is str and artifact["purpose"] in {"definition", "derived", "example"},
               "CONTRACT_DEFINITION_ARTIFACT_PURPOSE")


@check()
def resolves_exact_definitions(factory: Factory) -> None:
    """Resolve the requested identity/version unchanged; a missing pair is None."""
    definitions = sample_definitions()
    resolver = factory(deepcopy(definitions))
    try:
        for _ in range(2):
            for expected in definitions:
                actual = resolver.resolve(expected["id"], expected["version"])
                definition_is_valid(actual)
                expect_equal(actual, expected, "CONTRACT_EXACT_DEFINITION")
        for contract_id, version in (("Example/Exchange", "latest"), ("example/exchange", "draft-A"),
                                     ("unknown", "draft-A"), ("Example/Exchange", " draft-A ")):
            expect(resolver.resolve(contract_id, version) is None, "CONTRACT_ABSENCE_IS_NONE")
    finally:
        resolver.close()


@check()
def returns_detached_definitions(factory: Factory) -> None:
    """Mutating nested roles or artifacts never changes another result or later reads."""
    expected = sample_definitions()[0]
    resolver = factory([deepcopy(expected)])
    try:
        first = resolver.resolve(expected["id"], expected["version"])
        second = resolver.resolve(expected["id"], expected["version"])
        definition_is_valid(first)
        first["id"] = "changed"
        for role in first["roles"].values():
            role["obligations"].append("Caller mutation.")
        first["artifacts"]["source"]["content"] = "Caller mutation."
        first["artifacts"]["source"]["selector"] = "#Changed"
        del first["artifacts"]["request-example"]
        expect_equal(second, expected, "CONTRACT_RESULTS_DETACHED")
        expect_equal(resolver.resolve(expected["id"], expected["version"]), expected, "CONTRACT_RESULTS_DETACHED")
    finally:
        resolver.close()


@check()
def refuses_invalid_references(factory: Factory) -> None:
    """Empty or non-string identity/version is invalid_arguments, never absence."""
    resolver = factory(sample_definitions())
    try:
        for bad in ("", None, 1, False, [], {}):
            for contract_id, version in ((bad, "draft-A"), ("Example/Exchange", bad)):
                error = raises(OrchestrationError, lambda key=contract_id, rev=version: resolver.resolve(key, rev),
                               "CONTRACT_INVALID_REFERENCE_REFUSED")
                expect_equal(error.code, "invalid_arguments", "CONTRACT_INVALID_REFERENCE_CODE")
    finally:
        resolver.close()


@check()
def close_is_idempotent_and_prevents_reuse(factory: Factory) -> None:
    """Closing twice succeeds and subsequent resolution reports contract_resolver_closed."""
    resolver = factory(sample_definitions())
    try:
        resolver.close()
        resolver.close()
        error = raises(OrchestrationError, lambda: resolver.resolve("Example/Exchange", "draft-A"),
                       "CONTRACT_CLOSED_REFUSES_RESOLUTION")
        expect_equal(error.code, "contract_resolver_closed", "CONTRACT_CLOSED_CODE")
    finally:
        resolver.close()


@check()
def failure_is_distinct(resolver: ContractResolver, contract_id: str, version: str, expected_code: str) -> None:
    """A known unavailable, denied or invalid backend reports its failure instead of None."""
    expect(expected_code in {"contract_unavailable", "contract_denied", "contract_invalid"},
           "CONTRACT_FAILURE_FIXTURE_CODE")
    try:
        error = raises(OrchestrationError, lambda: resolver.resolve(contract_id, version), "CONTRACT_FAILURE_IS_NOT_ABSENCE")
        expect_equal(error.code, expected_code, "CONTRACT_FAILURE_CODE")
    finally:
        resolver.close()


CHECKS = (resolves_exact_definitions, returns_detached_definitions, refuses_invalid_references,
          close_is_idempotent_and_prevents_reuse)
