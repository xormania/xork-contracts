"""Contract access works on exact, language-neutral, two-role definitions."""

import copy
import importlib.resources
import json

import pytest
from jsonschema import Draft202012Validator

import xcontracts
from xcontracts import contracts as definitions
from xcontracts import ports
from xcontracts.model import OrchestrationError
from xcontracts.testing import ContractViolation, contracts, fakes


def document(version="draft-a", contract_id="example.exchange"):
    """Authored expectation, independent of the kit's conformance corpus."""
    return {
        "schema_version": "1",
        "id": contract_id,
        "version": version,
        "roles": {
            "publisher": {"obligations": ["Label each emitted value with its declared unit."]},
            "subscriber": {"obligations": ["Interpret each value using its declared unit."]},
        },
    }


def malformed(kind):
    value = document()
    if kind == "unknown-schema":
        value["schema_version"] = "2"
    elif kind == "numeric-schema":
        value["schema_version"] = 1
    elif kind == "boolean-schema":
        value["schema_version"] = True
    elif kind == "noninteger-schema":
        value["schema_version"] = 1.5
    elif kind == "empty-id":
        value["id"] = ""
    elif kind == "nonstring-version":
        value["version"] = 1
    elif kind == "missing-role":
        value["roles"].pop("subscriber")
    elif kind == "third-role":
        value["roles"]["observer"] = {"obligations": ["Observe."]}
    elif kind == "empty-role-name":
        value["roles"][""] = value["roles"].pop("publisher")
    elif kind == "empty-obligations":
        value["roles"]["publisher"]["obligations"] = []
    elif kind == "nonstring-obligation":
        value["roles"]["publisher"]["obligations"] = [{"text": "Emit."}]
    elif kind == "empty-obligation":
        value["roles"]["publisher"]["obligations"] = [""]
    elif kind == "unknown-top-field":
        value["approved"] = True
    elif kind == "unknown-role-field":
        value["roles"]["publisher"]["implementation"] = "python"
    else:
        raise AssertionError(f"Unknown corpus case {kind}")
    return value


INVALID_DEFINITIONS = (
    "unknown-schema", "numeric-schema", "boolean-schema", "noninteger-schema", "empty-id", "nonstring-version",
    "missing-role", "third-role", "empty-role-name", "empty-obligations", "nonstring-obligation",
    "empty-obligation", "unknown-top-field", "unknown-role-field",
)


def validator():
    schema = json.loads(importlib.resources.files("xcontracts").joinpath(
        "schemas/contract-definition-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_public_binding_is_one_protocol_and_native_types_remain_optional():
    assert xcontracts.ContractResolver is ports.ContractResolver
    assert xcontracts.ContractDefinition is definitions.ContractDefinition
    assert xcontracts.ContractRole is definitions.ContractRole
    resolver = fakes.MemoryContractResolver([document()])
    try:
        assert isinstance(resolver, ports.ContractResolver)
        assert resolver.resolve("example.exchange", "draft-a") == document()
    finally:
        resolver.close()


@pytest.mark.parametrize("version", ["draft-a", "0.1", "0.10", "0.2", "release/\u03b1", "latest", ">=0.1", " latest "])
def test_json_roundtrip_preserves_both_roles_and_opaque_versions(version):
    expected = document(version)
    transported = json.loads(json.dumps(expected, ensure_ascii=False))
    validator().validate(transported)
    contracts.definition_is_valid(transported)
    resolver = fakes.MemoryContractResolver([transported])
    try:
        assert resolver.resolve("example.exchange", version) == expected
        assert resolver.resolve("example.exchange", version + ".missing") is None
    finally:
        resolver.close()


def test_exact_references_do_not_trim_ids_or_choose_a_latest_version():
    entries = [document("0.10"), document("0.2"), document("draft-a", " example.exchange ")]
    resolver = fakes.MemoryContractResolver(entries)
    try:
        for entry in entries:
            assert resolver.resolve(entry["id"], entry["version"]) == entry
        assert resolver.resolve("example.exchange", "latest") is None
        assert resolver.resolve("example.exchange", ">=0.1") is None
        assert resolver.resolve("example.exchange", "draft-a") is None
        assert resolver.resolve("unknown.exchange", "0.2") is None
    finally:
        resolver.close()


def test_source_and_returned_roles_are_deeply_detached_and_repeatable():
    source = document()
    expected = copy.deepcopy(source)
    resolver = fakes.MemoryContractResolver([source])
    try:
        source["roles"]["publisher"]["obligations"].append("Injected after construction.")
        first = resolver.resolve("example.exchange", "draft-a")
        assert first == expected
        first["roles"]["subscriber"]["obligations"][0] = "Caller mutation."
        first["roles"].pop("publisher")
        assert resolver.resolve("example.exchange", "draft-a") == expected
        assert resolver.resolve("example.exchange", "draft-a") == expected
    finally:
        resolver.close()


def document_with_artifacts():
    value = document("candidate/\u03b1")
    value["artifacts"] = {
        "exchange.cue": {
            "format": "cue", "purpose": "definition",
            "content": 'package exchange\n\n#Request: {amount: number, unit: "ms" | "s"}\n#Reply: {accepted: bool}\n',
            "selector": "#Request",
        },
        "request.schema": {
            "format": "json-schema", "purpose": "derived",
            "content": '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object"}',
        },
        "opaque.example": {
            "format": "vendor/experimental-rules@4", "purpose": "example",
            "content": "do not trim this source \n", "selector": " opaque selector ",
        },
    }
    return value


def test_artifact_text_and_selectors_survive_transport_and_are_detached():
    """CUE and other sources are preserved as documents, without evaluating them."""
    expected = document_with_artifacts()
    transported = json.loads(json.dumps(expected, ensure_ascii=False))
    validator().validate(transported)
    contracts.definition_is_valid(transported)
    resolver = fakes.MemoryContractResolver([transported])
    try:
        transported["artifacts"]["exchange.cue"]["content"] = "Caller changed the source."
        first = resolver.resolve(expected["id"], expected["version"])
        assert first == expected
        first["artifacts"]["exchange.cue"]["selector"] = "#Reply"
        first["artifacts"]["request.schema"]["content"] += " "
        first["artifacts"].pop("opaque.example")
        assert resolver.resolve(expected["id"], expected["version"]) == expected
    finally:
        resolver.close()


def test_an_empty_artifact_map_does_not_add_a_format_requirement():
    value = document()
    value["artifacts"] = {}
    validator().validate(value)
    contracts.definition_is_valid(value)
    resolver = fakes.MemoryContractResolver([value])
    try:
        assert resolver.resolve(value["id"], value["version"]) == value
    finally:
        resolver.close()


@pytest.mark.parametrize(("field", "bad"), [
    ("format", ""), ("format", None), ("purpose", "evaluation"), ("purpose", 1),
    ("content", ""), ("content", {}), ("selector", ""), ("selector", []),
    ("unknown-field", "not in the v1 envelope"),
])
def test_invalid_artifact_fields_are_refused_consistently(field, bad):
    value = document_with_artifacts()
    value["artifacts"]["exchange.cue"][field] = bad
    assert not validator().is_valid(value)
    with pytest.raises(ContractViolation):
        contracts.definition_is_valid(value)
    with pytest.raises(OrchestrationError) as caught:
        fakes.MemoryContractResolver([value])
    assert caught.value.code == "contract_invalid"


@pytest.mark.parametrize("kind", ["nonobject-map", "empty-name", "nonobject-artifact", "missing-content"])
def test_invalid_artifact_structure_is_refused_consistently(kind):
    value = document_with_artifacts()
    if kind == "nonobject-map":
        value["artifacts"] = []
    elif kind == "empty-name":
        value["artifacts"][""] = value["artifacts"].pop("exchange.cue")
    elif kind == "nonobject-artifact":
        value["artifacts"]["exchange.cue"] = "source instead of an artifact object"
    elif kind == "missing-content":
        value["artifacts"]["exchange.cue"].pop("content")
    assert not validator().is_valid(value)
    with pytest.raises(ContractViolation):
        contracts.definition_is_valid(value)
    with pytest.raises(OrchestrationError) as caught:
        fakes.MemoryContractResolver([value])
    assert caught.value.code == "contract_invalid"


@pytest.mark.parametrize("kind", INVALID_DEFINITIONS)
def test_invalid_definitions_are_rejected_by_the_schema_kit_and_reference_fake(kind):
    bad = malformed(kind)
    assert not validator().is_valid(bad), kind
    with pytest.raises(ContractViolation):
        contracts.definition_is_valid(bad)
    with pytest.raises(OrchestrationError) as caught:
        fakes.MemoryContractResolver([bad])
    assert caught.value.code == "contract_invalid"


def test_conflicting_definitions_cannot_share_a_published_identity():
    first, conflicting = document(), document()
    conflicting["roles"]["subscriber"]["obligations"] = ["Interpret in a different unit."]
    with pytest.raises(OrchestrationError) as caught:
        fakes.MemoryContractResolver([first, conflicting])
    assert caught.value.code == "contract_invalid"


@pytest.mark.parametrize(("contract_id", "version"), [("", "a"), ("a", ""), (None, "a"), ("a", 1)])
def test_invalid_references_are_not_reported_as_missing(contract_id, version):
    resolver = fakes.MemoryContractResolver([])
    try:
        with pytest.raises(OrchestrationError) as caught:
            resolver.resolve(contract_id, version)
        assert caught.value.code == "invalid_arguments"
    finally:
        resolver.close()


def test_close_is_repeatable_and_a_closed_resolver_cannot_answer_absence():
    resolver = fakes.MemoryContractResolver([document()])
    resolver.close()
    resolver.close()
    for contract_id in ("example.exchange", "absent.exchange"):
        with pytest.raises(OrchestrationError) as caught:
            resolver.resolve(contract_id, "draft-a")
        assert caught.value.code == "contract_resolver_closed"


def test_the_packaged_self_description_is_a_two_sided_contract():
    example = json.loads(importlib.resources.files("xcontracts").joinpath(
        "schemas/contract-resolver-v1.json").read_text())
    validator().validate(example)
    contracts.definition_is_valid(example)
    assert len(example["roles"]) == 2
    assert all(role["obligations"] for role in example["roles"].values())


@pytest.mark.parametrize("check", contracts.CHECKS, ids=str)
def test_reference_contract_resolver_conforms(check):
    check(fakes.MemoryContractResolver)
