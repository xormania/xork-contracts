"""Native Python values for the language-neutral contract-definition v1 format.

The packaged JSON Schema and contract-access document describe the wire-neutral
shape and the obligations of both participants. These TypedDicts are a Python
binding, not runtime validators or a restriction on either participant's language.
"""

from typing import Literal, NotRequired, TypedDict


class ContractRole(TypedDict):
    """One participant's nonempty list of plain-language behavioral obligations."""

    obligations: list[str]


class ContractArtifact(TypedDict):
    """Native source text retained without interpretation or conversion.

    ``format`` and optional ``selector`` are opaque, nonempty identifiers for
    a future format-aware consumer. ``purpose`` is the publisher's description,
    not verified provenance or evidence that a derivation preserves semantics.
    """

    format: str
    purpose: Literal["definition", "derived", "example"]
    content: str
    selector: NotRequired[str]


class ContractDefinition(TypedDict):
    """An exact version of an agreement between two distinctly named roles.

    ``id`` and ``version`` are nonempty opaque strings, not package versions or
    version selectors. ``roles`` maps exactly two nonempty role names to their
    obligations. Names describe participation, not an implementation or language.
    ``schema_version`` versions this description format independently.
    Optional ``artifacts`` preserves native definitions and related material
    by nonempty name. Neither artifact names nor selectors trigger execution.
    """

    schema_version: Literal["1"]
    id: str
    version: str
    roles: dict[str, ContractRole]
    artifacts: NotRequired[dict[str, ContractArtifact]]
