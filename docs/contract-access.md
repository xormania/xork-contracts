# Contract access

`ContractResolver` is the first port for obtaining contracts. It reads one exact
version of a language-neutral agreement between two roles. The roles name the
participants' responsibilities; either side can be implemented in any language.

The shared description is [contract-definition v1](../xcontracts/schemas/contract-definition-v1.json).
The [contract-access agreement](../xcontracts/schemas/contract-resolver-v1.json)
uses that format to describe the requester's and resolver's obligations. The
Python `ContractResolver` Protocol and `ContractDefinition`/`ContractRole`/
`ContractArtifact` values
are native bindings to those definitions. Other languages can supply their own
bindings without importing Python or adopting a Python class identity.

## One operation

The logical operation is `resolve(contract_id, version)`:

- Both arguments are nonempty, exact, opaque strings. A literal `latest` has no
  special meaning. The port neither orders versions nor evaluates ranges.
- A successful lookup returns a detached definition matching both arguments.
- A missing result means the exact pair is known to be absent in the selected
  source. Python represents that result as `None`.
- Invalid arguments, unavailable sources, denied access, malformed definitions,
  and a closed resolver have distinct error codes. Python uses the existing
  `OrchestrationError`; another binding preserves the same meanings.
- Closing releases the binding's resources, is repeatable, and prevents further
  reads. It is a binding lifecycle operation, not deletion of the source.

Adapters may use packages, files, or a service. This contract does not prescribe
a network endpoint, message framing, authentication mechanism, or code-loading
protocol. A source may restrict visibility; inability or refusal to answer is
an error, never a fabricated absence. Public error messages must not expose
credentials or private source details.

## A two-sided definition

```json
{
  "schema_version": "1",
  "id": "example.verification",
  "version": "draft-a",
  "roles": {
    "requester": {
      "obligations": ["Identify the candidate being submitted."]
    },
    "executor": {
      "obligations": ["Bind every reported result to the submitted candidate."]
    }
  }
}
```

This is an illustrative agreement, not an implemented Xorgate API. Roles need
not be named requester/executor; symmetric peers can have named roles too.
Version 1 represents exactly two distinct roles, each with at least one
nonempty obligation. The schema closes the envelope and role objects so an
unknown field cannot silently carry an ignored requirement. Optional native
artifacts preserve machine-readable definitions alongside these readable
responsibilities. Checker references and additional participants can be added
through a later explicit format revision.

`schema_version` identifies the description format. `id`/`version` identify the
agreement within its selected source. They are independent of the Python package
release, the participating applications' releases, and their binding adapters.
A published identity/version denotes unchanged content. The resolver returns
that content without applying defaults, dropping a role, or rewriting obligations.
Different sources may make conflicting claims: callers retain source identity
and choose their trust policy separately. This port does not establish global
uniqueness or authenticity.

Obligations are readable text; they need not exhaust the native definition's
constraints. JSON Schema checks the envelope's shape; conformance scenarios
check the resolver's behavior. Neither checks whether a participant fulfills an
arbitrary described obligation. Resolving a description does not grant approval
or certify compatibility between implementations.

## Native artifacts, including CUE

A definition may include an `artifacts` object. Each nonempty name identifies
source text with an opaque `format`, a declared `purpose` (`definition`,
`derived`, or `example`), and an optional opaque `selector`. For example:

```json
{
  "agreement.cue": {
    "format": "cue",
    "purpose": "definition",
    "content": "package agreement\n#Request: {candidate!: string}\n#Result: {candidate!: string, accepted!: bool}\n",
    "selector": "#Request"
  }
}
```

This is the value of `artifacts`, not a complete contract definition. It keeps
the selected definition even when a source contains multiple definitions.
JSON Schema, OpenAPI, native interface text, and unfamiliar formats use the same
envelope. All text and selectors survive resolution unchanged. An absent or
empty artifacts map is valid for an agreement described entirely in prose.

The resolver does not execute source, interpret selectors, infer missing
values, follow imports, or fetch external references. Names are descriptor
keys, not instructions to write files. A successful lookup says nothing about
whether an artifact is executable or its module context is complete. Declared
purposes do not prove provenance, equivalence between definitions, or that a
derived JSON artifact preserves the original CUE constraints. A future checker
can establish those claims for an explicit format and scope.

This boundary draws on existing project work:

- [Agentscient role packages](https://github.com/xormania/agentscient/blob/f1e2e010832e720f551ab9d70d4e8ef8fb0ef2e9/devtools/role_packages.py)
  validate CUE and check deterministic JSON exports with source digests, while
  runtime consumers load JSON without CUE. That is a useful adapter pattern.
- [Graph-contracts' CUE evaluator](https://github.com/xormania/graph-contracts-poc/blob/0238d79e1d2701f691cba5a88bd128ca3e838c34/src/evaluation.rs)
  retains both source and selected definition. Resolution preserves that
  information; evaluation remains separate.
- [Serena's contract work](https://github.com/xormania/serena/blob/6564186eb6dd44f28493136d2649824f0379dd3e/contract/README.md)
  distinguishes authored declarations, extracted facts, generated output and
  behavioral evidence. These categories must not collapse during resolution.
- [Agent-lab's projection repair](https://github.com/xormania/agent-lab/blob/c5344ed7b05a254f49fc6f9e47ab0ffaebc63116/contracts/experiment/v0alpha2/plan.cue)
  demonstrates why evaluator tests must exercise the actual selected expression.
  A constraint outside that projection did not protect the exported result.

CUE is a supported source format by preservation, not a required compiler or an
implemented evaluator in this package. CUE's [schema subsumption](https://cuelang.org/docs/concept/schema-definition-use-case/)
is useful for directional structural compatibility; successful validation of
one input is a different claim. Its [defaults](https://cuelang.org/docs/tour/types/defaults/)
can complete missing values, so future evaluation must distinguish supplied
observations from resolved configuration. The current port performs neither
operation. The artifact-preservation tests do not claim CUE semantic validity
or native PHP/Rust interoperability.

## Implement and check a binding

Implement `resolve` and `close`; inheritance is optional. Constructor settings,
credentials and transport belong to the adapter. `ContractResolver` is not yet
registered in `KINDS`, because no Xorchestrate composition change is part of
this port. Applications can inject a resolver directly; later configuration
integration can select it through an explicit binding.

`xcontracts.testing.contracts` supplies checks and the test kit's
`MemoryContractResolver` is the reference fake. Adapter authors provide a
fixture factory that seeds known definitions in their own backend, then run
the checks against the returned resolver. The fixture does not add a write
operation to the production port. Backend-specific tests also exercise denial,
unavailability and malformed source data.

The schema and self-description ship with the package. Python callers can read
them with `importlib.resources.files("xcontracts").joinpath("schemas", filename)`;
other implementations can consume the same JSON artifacts. Package installation
does not require a registry service or a schema-validation runtime dependency.

## Compatibility and first adoption

This is an additive port, intended for the next 0.2 compatibility series under
the package's pre-1.0 policy. The working package number is prepared separately
when xor cuts the release. Existing interfaces and `KINDS` remain unchanged.
The source repository is `xormania/xork-contracts`; distribution and imports
remain `xcontracts`. Xorchestrate currently pins the separate `xcontracts`
repository, so consuming this work requires an explicit dependency update.
No consumer, GitHub configuration, or publisher is changed by adding this port.
