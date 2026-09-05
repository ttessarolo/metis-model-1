"""Compact, host-expanded CREATE plan v2 for Metis Brain.

The decoder sees only a five-operation body over projection-local integer
handles.  Revisions, target, basis, opaque references and leaf evidence are
server-owned.  This module deliberately does not render Metis, read a tenant,
call a model or make a compiler call.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeAlias

from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import CREATE_ENDPOINT_SPEC_SCHEMA
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREATE_DELTA_PLAN_BODY_V2_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas/metis-brain-create-delta-plan-body-v2.schema.json"
)
CREATE_DELTA_PLAN_V2_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas/metis-brain-create-delta-plan-v2.schema.json"
)
CREATE_DELTA_PLAN_V2_CONTRACT = "metis-brain-create-delta-plan/v2"
COMPACT_AUTHORITY_PROJECTION_V2_CONTRACT = "metis-brain-create-compact-projection/v2"

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MEMBER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
JSON_POINTER_TOKEN_RE = re.compile(r"(?:/(?:[^~/]|~[01])*)*")

MAX_JSON_BYTES = 8_192
MAX_OPERATIONS = 5
MAX_REQUIREMENT_HANDLES = 64
MAX_AUTHORITY_HANDLES = 256
MAX_REQUIREMENTS_PER_OPERATION = 4
MAX_EXPANSION_ROWS = 12
MAX_FRAGMENT_BYTES = 16_384
MAX_FRAGMENT_DEPTH = 24
MAX_FRAGMENT_NODES = 1_024
MAX_LEAF_BINDINGS = 256
# The decoder constraint is deliberately much smaller than the full private
# authority projection.  It contains only local integer handles and is an
# optional *pre-admission* guard; the full reciprocal/order proof below stays
# the final authority.
MAX_DECODER_DIRECT_ALTERNATIVES = 256
MAX_DECODER_EXPANSION_DESCRIPTORS = 128
MAX_DECODER_CONSTRAINT_BYTES = 32_768

_FORBIDDEN_KEYS = frozenset(
    {
        "code",
        "dsl",
        "endpoint_template",
        "file",
        "metis",
        "metis_source",
        "path",
        "raw",
        "raw_source",
        "snippet",
        "source",
        "source_path",
        "source_text",
        "template",
        "template_ref",
        "text",
    }
)
_FORBIDDEN_MODEL_LABEL_TOKENS = frozenset(
    {
        "arguments",
        "dsl",
        "evidence",
        "file",
        "fragment",
        "golden",
        "hostref",
        "path",
        "source",
        "template",
    }
)
CREATE_V2_NEW_FRAGMENT_TYPES = frozenset(
    {
        "argumentValue",
        "attribute",
        "boolValue",
        "clause",
        "container",
        "contextBinding",
        "contextValue",
        "endpointParams",
        "fallback",
        "fetch",
        "fetchCardinality",
        "fetchSource",
        "groupBy",
        "guard",
        "identifier",
        "inheritance",
        "input",
        "inputValue",
        "listRefValue",
        "literalValue",
        "metaEntry",
        "operand",
        "order",
        "outputStep",
        "parameter",
        "predicate",
        "presentation",
        "qualifiedIdentifier",
        "returnFlow",
        "safeText",
        "segments",
        "title",
        "use",
        "value",
        "valuesValue",
        "variant",
    }
)
_EXCLUDED_NEW_FRAGMENT_TYPES = frozenset({"endpoint"})
_STRUCTURAL_NEW_FRAGMENT_PLACEMENTS = {
    "container": frozenset({("blocks", "many", "append")}),
    "contextBinding": frozenset({("context", "many", "append")}),
    "fetch": frozenset({("fetches", "many", "append")}),
    "variant": frozenset({("variants", "many", "append")}),
}
_OP_NAMES = frozenset({"attach", "set", "remove", "expand"})
_OP_CODE_TO_NAME = {"a": "attach", "s": "set", "d": "remove", "x": "expand"}


class CreateDeltaPlanV2Error(ValueError):
    """Raised when a tracked v2 schema is unavailable or malformed."""


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - tracked protocol must fail closed
        raise CreateDeltaPlanV2Error("CREATE plan v2 schema is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise CreateDeltaPlanV2Error("CREATE plan v2 schema is invalid")
    return value


CREATE_DELTA_PLAN_BODY_V2_SCHEMA = _load_schema(CREATE_DELTA_PLAN_BODY_V2_SCHEMA_PATH)
CREATE_DELTA_PLAN_V2_SCHEMA = _load_schema(CREATE_DELTA_PLAN_V2_SCHEMA_PATH)
CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256 = bytes_sha256(
    canonical_json(CREATE_DELTA_PLAN_BODY_V2_SCHEMA)
)
CREATE_DELTA_PLAN_V2_SCHEMA_SHA256 = bytes_sha256(canonical_json(CREATE_DELTA_PLAN_V2_SCHEMA))
_BODY_VALIDATOR = Draft202012Validator(CREATE_DELTA_PLAN_BODY_V2_SCHEMA)

try:
    _ENDPOINT_SPEC_FRAGMENT_DEFS = CREATE_ENDPOINT_SPEC_SCHEMA["$defs"]
except (KeyError, TypeError) as error:  # pragma: no cover - tracked builder contract
    raise CreateDeltaPlanV2Error(
        "typed CREATE endpoint schema is unavailable or invalid"
    ) from error
if (
    not isinstance(_ENDPOINT_SPEC_FRAGMENT_DEFS, Mapping)
    or frozenset(_ENDPOINT_SPEC_FRAGMENT_DEFS)
    != CREATE_V2_NEW_FRAGMENT_TYPES | _EXCLUDED_NEW_FRAGMENT_TYPES
    or not frozenset(_STRUCTURAL_NEW_FRAGMENT_PLACEMENTS).issubset(CREATE_V2_NEW_FRAGMENT_TYPES)
):
    raise CreateDeltaPlanV2Error("typed CREATE endpoint fragment registry differs")


@lru_cache(maxsize=len(CREATE_V2_NEW_FRAGMENT_TYPES))
def _new_fragment_validator(fragment_type: str) -> Draft202012Validator:
    """Build the exact private endpoint-spec validator for one reviewed fragment type."""

    if fragment_type not in CREATE_V2_NEW_FRAGMENT_TYPES:
        raise CreateDeltaPlanV2Error("typed CREATE fragment type is unavailable")
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{fragment_type}",
            "$defs": _ENDPOINT_SPEC_FRAGMENT_DEFS,
        }
    )


def _is_exact_new_fragment(fragment_type: str, fragment: Any) -> bool:
    """Whether a new node earns the reviewed populated-fragment exemption.

    A label alone is never enough: otherwise a `value` grant could smuggle an
    arbitrary endpoint subtree past the new-node skeleton restriction.  Only
    the explicit current non-root registry backed by the tracked endpoint-spec
    schema may bypass that restriction.  A future `$defs` entry is not admitted
    until this code-owned roster is deliberately revised.
    """

    if fragment_type not in CREATE_V2_NEW_FRAGMENT_TYPES:
        return False
    return not any(_new_fragment_validator(fragment_type).iter_errors(fragment))


def _invalid(message: str) -> BrainError:
    return BrainError("CREATE_DELTA_PLAN_V2_INVALID", 502, message)


def _strict_hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise _invalid(f"{label} is invalid")
    return value


def _strict_ref(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or HOST_REF_RE.fullmatch(value) is None:
        raise _invalid(f"{label} is invalid")
    return value


def _safe_model_label(value: Any, *, label: str) -> str:
    """Accept a bounded human hint that cannot become private authority."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 160
        or any(ord(character) < 32 for character in value)
        or "/" in value
        or "\\" in value
        or HOST_REF_RE.fullmatch(value) is not None
    ):
        raise _invalid(f"{label} is invalid")
    tokens = set(re.findall(r"[a-z0-9_]+", value.casefold()))
    if tokens & _FORBIDDEN_MODEL_LABEL_TOKENS or "sha256:" in value.casefold():
        raise _invalid(f"{label} is not model-safe")
    return value


def _strict_handle(value: Any, *, label: str, upper: int = MAX_AUTHORITY_HANDLES - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
        raise _invalid(f"{label} is invalid")
    return value


def _strict_basis_path(value: Any, *, label: str) -> tuple[str | int, ...]:
    """Validate a private structural locator; it is never model-visible."""

    if not isinstance(value, tuple) or not 1 <= len(value) <= MAX_FRAGMENT_DEPTH:
        raise _invalid(f"{label} is invalid")
    output: list[str | int] = []
    for token in value:
        if isinstance(token, bool):
            raise _invalid(f"{label} is invalid")
        if isinstance(token, int):
            if not 0 <= token <= MAX_FRAGMENT_NODES:
                raise _invalid(f"{label} is invalid")
        elif not isinstance(token, str) or MEMBER_RE.fullmatch(token) is None:
            raise _invalid(f"{label} is invalid")
        output.append(token)
    return tuple(output)


def _strict_json(value: Any, *, label: str) -> Any:
    """Canonical, bounded JSON that cannot carry source/path/template authority."""

    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > MAX_FRAGMENT_DEPTH or nodes > MAX_FRAGMENT_NODES:
            raise _invalid(f"{label} exceeds its structural bound")
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise _invalid(f"{label} contains a non-string key")
                if key.casefold().replace("-", "_") in _FORBIDDEN_KEYS:
                    raise _invalid(f"{label} contains a forbidden source-like key")
                stack.append((nested, depth + 1))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            stack.extend((nested, depth + 1) for nested in item)
        elif item is None or type(item) in {str, int, float, bool}:
            continue
        else:
            raise _invalid(f"{label} is not strict JSON")
    try:
        raw = canonical_json(value)
        copy = json.loads(raw)
    except (BrainError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise _invalid(f"{label} is not canonical JSON") from error
    if not raw or len(raw) > MAX_FRAGMENT_BYTES:
        raise _invalid(f"{label} exceeds its byte bound")
    return copy


def _decode_pointer(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or JSON_POINTER_TOKEN_RE.fullmatch(pointer) is None:
        raise _invalid("leaf binding JSON pointer is invalid")
    if pointer == "":
        return ()
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def _pointer_value(value: Any, pointer: str) -> Any:
    current = value
    for token in _decode_pointer(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise _invalid("leaf binding pointer is not present in its fragment")
            current = current[token]
        elif isinstance(current, list):
            if not token.isascii() or not token.isdecimal() or (len(token) > 1 and token[0] == "0"):
                raise _invalid("leaf binding array pointer is invalid")
            index = int(token)
            if index >= len(current):
                raise _invalid("leaf binding pointer is not present in its fragment")
            current = current[index]
        else:
            raise _invalid("leaf binding pointer descends through a scalar")
    return current


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _nondefault_leaf_pointers(value: Any, path: str = "") -> set[str]:
    if isinstance(value, dict):
        output: set[str] = set()
        for key, nested in value.items():
            output.update(_nondefault_leaf_pointers(nested, f"{path}/{_escape_pointer(key)}"))
        return output
    if isinstance(value, list):
        output = set()
        for index, nested in enumerate(value):
            output.update(_nondefault_leaf_pointers(nested, f"{path}/{index}"))
        return output
    # A false or null scalar can be executable (for example required, empty,
    # pagination or fallback flags).  The code-owned initial skeleton is not a
    # grant, so every scalar in a grant must have exact evidence.
    return {path}


def _structural_skeleton_only(value: Any) -> bool:
    """Non-atomic new nodes may contain scalars and empty child collections only."""

    if value is None or type(value) in {str, int, float, bool}:
        return True
    if isinstance(value, list):
        return not value
    if not isinstance(value, Mapping):
        return False
    for nested in value.values():
        if isinstance(nested, Mapping) and nested:
            return False
        if isinstance(nested, list) and nested:
            return False
    return True


@dataclass(frozen=True, slots=True)
class RequirementHandle:
    handle: int
    ref: str
    label: str
    allowed_ops: frozenset[str]


@dataclass(frozen=True, slots=True)
class FragmentLeafBinding:
    json_pointer: str
    evidence_ref: str
    requirement_refs: tuple[str, ...]
    origin: Literal["operator", "clarification", "reviewed_semantic", "policy", "basis"]


@dataclass(frozen=True, slots=True)
class SlotGrant:
    handle: int
    ref: str
    label: str
    anchor_ref: str
    member: str
    cardinality: Literal["one", "many"]
    accepts: tuple[str, ...]
    mutations: frozenset[str]
    insertion: Literal["append", "replace", "exact"]
    basis_spec_sha256: str | None
    generation: int


@dataclass(frozen=True, slots=True)
class NodeGrant:
    handle: int
    ref: str
    label: str
    state: Literal["new", "basis"]
    fragment_type: str
    fragment: Any
    fragment_sha256: str
    leaf_bindings: tuple[FragmentLeafBinding, ...]
    basis_spec_sha256: str | None
    basis_path: tuple[str | int, ...] | None
    parent_slot_ref: str | None
    removable: bool


@dataclass(frozen=True, slots=True)
class RecipeGrant:
    handle: int
    ref: str
    label: str
    recipe_id: str
    version: int
    row_type: str
    output_type: str
    scope_members: tuple[str, ...]
    implementation_sha256: str
    max_rows: int
    max_emitted_mutations: int


@dataclass(frozen=True, slots=True)
class ExpansionRow:
    handle: int
    ref: str
    label: str
    recipe_id: str
    row_type: str
    arguments: Any
    leaf_bindings: tuple[FragmentLeafBinding, ...]
    row_sha256: str


AuthorityGrant: TypeAlias = SlotGrant | NodeGrant | RecipeGrant | ExpansionRow


@dataclass(frozen=True, slots=True)
class CompactAuthorityProjection:
    projection_revision: str
    surface_revision: str
    requirements: tuple[RequirementHandle, ...]
    authorities: tuple[AuthorityGrant, ...]
    schema_version: int = 2
    contract_id: str = COMPACT_AUTHORITY_PROJECTION_V2_CONTRACT

    def model_projection_payload(self) -> dict[str, Any]:
        """Return the complete, label-bearing handle roster visible to a decoder.

        The compact body may name only local handles.  Opaque host references,
        executable fragments, row arguments and all evidence remain server-only.
        Validation is intentionally repeated here so an issuer cannot serialize a
        stale or malformed projection merely because it has an object instance.
        """

        validate_compact_authority_projection(self)
        slots = sorted(
            (item for item in self.authorities if isinstance(item, SlotGrant)),
            key=lambda item: item.handle,
        )
        nodes = sorted(
            (item for item in self.authorities if isinstance(item, NodeGrant)),
            key=lambda item: item.handle,
        )
        recipes = sorted(
            (item for item in self.authorities if isinstance(item, RecipeGrant)),
            key=lambda item: item.handle,
        )
        rows = sorted(
            (item for item in self.authorities if isinstance(item, ExpansionRow)),
            key=lambda item: item.handle,
        )
        return {
            "v": 2,
            "p": self.projection_revision,
            "q": [
                {"h": item.handle, "l": item.label, "o": sorted(item.allowed_ops)}
                for item in sorted(self.requirements, key=lambda item: item.handle)
            ],
            "s": [
                {
                    "h": item.handle,
                    "l": item.label,
                    "a": list(item.accepts),
                    "m": sorted(item.mutations),
                    "c": item.cardinality,
                    "i": item.insertion,
                    "g": item.member,
                }
                for item in slots
            ],
            "n": [
                {
                    "h": item.handle,
                    "l": item.label,
                    "t": item.fragment_type,
                    "s": item.state,
                    "d": item.removable,
                }
                for item in nodes
            ],
            "r": [
                {
                    "h": item.handle,
                    "l": item.label,
                    "i": item.recipe_id,
                    "t": item.row_type,
                    "o": item.output_type,
                    "g": list(item.scope_members),
                    "m": item.max_rows,
                }
                for item in recipes
            ],
            "w": [
                {
                    "h": item.handle,
                    "l": item.label,
                    "i": item.recipe_id,
                    "t": item.row_type,
                }
                for item in rows
            ],
        }


@dataclass(frozen=True, slots=True)
class AttachOpV2:
    ordinal: int
    requirement_refs: tuple[str, ...]
    slot_ref: str
    node_ref: str


@dataclass(frozen=True, slots=True)
class SetOpV2:
    ordinal: int
    requirement_refs: tuple[str, ...]
    slot_ref: str
    value_ref: str


@dataclass(frozen=True, slots=True)
class RemoveOpV2:
    ordinal: int
    requirement_refs: tuple[str, ...]
    node_ref: str


@dataclass(frozen=True, slots=True)
class ExpandOpV2:
    ordinal: int
    requirement_refs: tuple[str, ...]
    slot_ref: str
    recipe_ref: str
    row_refs: tuple[str, ...]


CreateDeltaOperationV2: TypeAlias = AttachOpV2 | SetOpV2 | RemoveOpV2 | ExpandOpV2


@dataclass(frozen=True, slots=True)
class CreateDeltaPlanV2:
    mode: Literal["initial", "refinement"]
    context_revision: str
    semantic_revision: str
    surface_revision: str
    projection_revision: str
    target_ref: str
    basis_ref: str | None
    requirements: tuple[str, ...]
    operations: tuple[CreateDeltaOperationV2, ...]
    schema_version: int = 2
    contract_id: str = CREATE_DELTA_PLAN_V2_CONTRACT

    def internal_json(self) -> dict[str, Any]:
        """Return the tracked internal envelope; never use as a model prompt."""

        def operation_value(operation: CreateDeltaOperationV2) -> dict[str, Any]:
            if isinstance(operation, AttachOpV2):
                return {
                    "ordinal": operation.ordinal,
                    "k": "a",
                    "q": list(operation.requirement_refs),
                    "s": operation.slot_ref,
                    "n": operation.node_ref,
                }
            if isinstance(operation, SetOpV2):
                return {
                    "ordinal": operation.ordinal,
                    "k": "s",
                    "q": list(operation.requirement_refs),
                    "s": operation.slot_ref,
                    "v": operation.value_ref,
                }
            if isinstance(operation, RemoveOpV2):
                return {
                    "ordinal": operation.ordinal,
                    "k": "d",
                    "q": list(operation.requirement_refs),
                    "n": operation.node_ref,
                }
            return {
                "ordinal": operation.ordinal,
                "k": "x",
                "q": list(operation.requirement_refs),
                "s": operation.slot_ref,
                "r": operation.recipe_ref,
                "w": list(operation.row_refs),
            }

        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "mode": self.mode,
            "context_revision": self.context_revision,
            "semantic_revision": self.semantic_revision,
            "surface_revision": self.surface_revision,
            "projection_revision": self.projection_revision,
            "target_ref": self.target_ref,
            "basis_ref": self.basis_ref,
            "requirements": list(self.requirements),
            "body": {"o": [operation_value(item) for item in self.operations]},
        }


@dataclass(frozen=True, slots=True)
class CompactProjectionIndex:
    projection: CompactAuthorityProjection
    requirements_by_handle: Mapping[int, RequirementHandle]
    slots_by_handle: Mapping[int, SlotGrant]
    nodes_by_handle: Mapping[int, NodeGrant]
    recipes_by_handle: Mapping[int, RecipeGrant]
    rows_by_handle: Mapping[int, ExpansionRow]


@dataclass(frozen=True, slots=True)
class CreatePlanV2DirectOperationConstraint:
    """One exact, model-safe direct operation available to the decoder.

    The object intentionally carries handles only.  Private refs, evidence,
    fragments, labels and tenant state never enter this constraint.
    """

    kind: Literal["a", "s", "d"]
    requirement_handles: tuple[int, ...]
    slot_handle: int | None
    node_handle: int

    def body(self) -> dict[str, Any]:
        output: dict[str, Any] = {
            "k": self.kind,
            "q": list(self.requirement_handles),
        }
        if self.slot_handle is not None:
            output["s"] = self.slot_handle
        output["n" if self.kind in {"a", "d"} else "v"] = self.node_handle
        return output


@dataclass(frozen=True, slots=True)
class CreatePlanV2ExpansionDescriptor:
    """A bounded role-safe expansion descriptor, with no private content."""

    slot_handle: int
    recipe_handle: int
    row_handles: tuple[int, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "s": self.slot_handle,
            "r": self.recipe_handle,
            "w": list(self.row_handles),
        }


@dataclass(frozen=True, slots=True)
class CreatePlanV2DecoderConstraint:
    """Immutable projection-derived grammar guard for a CREATE-v2 decoder.

    ``payload()`` is the sole model-visible representation.  Its exact wire
    shape is intentionally compact and contains no tenant values, labels,
    host references, source fragments or evidence:

    ``{"v":1,"p":...,"a":[...],"d":[...],"x":[...]}``
    """

    projection_revision: str
    active_requirement_handles: tuple[int, ...]
    direct_operations: tuple[CreatePlanV2DirectOperationConstraint, ...]
    expansion_descriptors: tuple[CreatePlanV2ExpansionDescriptor, ...]
    constraint_sha256: str

    def payload(self) -> dict[str, Any]:
        return {
            "v": 1,
            "p": self.projection_revision,
            "a": list(self.active_requirement_handles),
            "d": [item.body() for item in self.direct_operations],
            "x": [item.payload() for item in self.expansion_descriptors],
        }


def _leaf_manifest(binding: FragmentLeafBinding) -> dict[str, Any]:
    return {
        "json_pointer": binding.json_pointer,
        "evidence_ref": binding.evidence_ref,
        "requirement_refs": list(binding.requirement_refs),
        "origin": binding.origin,
    }


def _authority_manifest(authority: AuthorityGrant) -> dict[str, Any]:
    if isinstance(authority, SlotGrant):
        return {
            "kind": "slot",
            "handle": authority.handle,
            "ref": authority.ref,
            "label": authority.label,
            "anchor_ref": authority.anchor_ref,
            "member": authority.member,
            "cardinality": authority.cardinality,
            "accepts": list(authority.accepts),
            "mutations": sorted(authority.mutations),
            "insertion": authority.insertion,
            "basis_spec_sha256": authority.basis_spec_sha256,
            "generation": authority.generation,
        }
    if isinstance(authority, NodeGrant):
        return {
            "kind": "node",
            "handle": authority.handle,
            "ref": authority.ref,
            "label": authority.label,
            "state": authority.state,
            "fragment_type": authority.fragment_type,
            "fragment_sha256": authority.fragment_sha256,
            "leaf_bindings": [_leaf_manifest(item) for item in authority.leaf_bindings],
            "basis_spec_sha256": authority.basis_spec_sha256,
            "basis_path": list(authority.basis_path) if authority.basis_path is not None else None,
            "parent_slot_ref": authority.parent_slot_ref,
            "removable": authority.removable,
        }
    if isinstance(authority, RecipeGrant):
        return {
            "kind": "recipe",
            "handle": authority.handle,
            "ref": authority.ref,
            "label": authority.label,
            "recipe_id": authority.recipe_id,
            "version": authority.version,
            "row_type": authority.row_type,
            "output_type": authority.output_type,
            "scope_members": list(authority.scope_members),
            "implementation_sha256": authority.implementation_sha256,
            "max_rows": authority.max_rows,
            "max_emitted_mutations": authority.max_emitted_mutations,
        }
    return {
        "kind": "row",
        "handle": authority.handle,
        "ref": authority.ref,
        "label": authority.label,
        "recipe_id": authority.recipe_id,
        "row_type": authority.row_type,
        "row_sha256": authority.row_sha256,
        "leaf_bindings": [_leaf_manifest(item) for item in authority.leaf_bindings],
    }


def compact_authority_projection_revision(
    *,
    surface_revision: str,
    requirements: Sequence[RequirementHandle],
    authorities: Sequence[AuthorityGrant],
) -> str:
    """Return the revision for a projection without embedding private fragments."""

    return bytes_sha256(
        canonical_json(
            {
                "schema_version": 2,
                "contract_id": COMPACT_AUTHORITY_PROJECTION_V2_CONTRACT,
                "surface_revision": surface_revision,
                "requirements": [
                    {
                        "handle": item.handle,
                        "ref": item.ref,
                        "label": item.label,
                        "allowed_ops": sorted(item.allowed_ops),
                    }
                    for item in requirements
                ],
                "authorities": [_authority_manifest(item) for item in authorities],
            }
        )
    )


def _validate_leaf_bindings(
    *,
    value: Any,
    bindings: Sequence[FragmentLeafBinding],
    requirement_refs: frozenset[str],
    label: str,
) -> frozenset[str]:
    if (
        isinstance(bindings, (str, bytes))
        or not isinstance(bindings, Sequence)
        or len(bindings) > MAX_LEAF_BINDINGS
    ):
        raise _invalid(f"{label} leaf bindings are invalid")
    seen: set[str] = set()
    bound_requirements: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, FragmentLeafBinding):
            raise _invalid(f"{label} leaf binding is invalid")
        pointer = binding.json_pointer
        if pointer in seen:
            raise _invalid(f"{label} leaf binding is duplicated")
        seen.add(pointer)
        leaf = _pointer_value(value, pointer)
        if isinstance(leaf, (dict, list)):
            raise _invalid(f"{label} leaf binding does not bind an executable leaf")
        _strict_ref(binding.evidence_ref, label=f"{label} evidence ref")
        if binding.origin not in {
            "operator",
            "clarification",
            "reviewed_semantic",
            "policy",
            "basis",
        }:
            raise _invalid(f"{label} leaf origin is invalid")
        if (
            not binding.requirement_refs
            or len(binding.requirement_refs) > MAX_REQUIREMENTS_PER_OPERATION
        ):
            raise _invalid(f"{label} leaf requirement binding is invalid")
        if len(set(binding.requirement_refs)) != len(binding.requirement_refs):
            raise _invalid(f"{label} leaf requirement binding is duplicated")
        for requirement_ref in binding.requirement_refs:
            _strict_ref(requirement_ref, label=f"{label} leaf requirement ref")
            if requirement_ref not in requirement_refs:
                raise _invalid(f"{label} leaf references a foreign requirement")
            bound_requirements.add(requirement_ref)
    expected = _nondefault_leaf_pointers(value)
    if seen != expected:
        raise _invalid(f"{label} does not prove every executable non-default leaf")
    return frozenset(bound_requirements)


def validate_compact_authority_projection(
    projection: CompactAuthorityProjection,
) -> CompactProjectionIndex:
    """Validate server-owned grants before any untrusted compact plan is read."""

    if not isinstance(projection, CompactAuthorityProjection):
        raise _invalid("compact authority projection is invalid")
    if (
        projection.schema_version != 2
        or projection.contract_id != COMPACT_AUTHORITY_PROJECTION_V2_CONTRACT
    ):
        raise _invalid("compact authority projection contract differs")
    _strict_hash(projection.surface_revision, label="projection surface revision")
    _strict_hash(projection.projection_revision, label="projection revision")
    if not projection.requirements or len(projection.requirements) > MAX_REQUIREMENT_HANDLES:
        raise _invalid("projection requirement roster is invalid")
    if not projection.authorities or len(projection.authorities) > MAX_AUTHORITY_HANDLES:
        raise _invalid("projection authority roster is invalid")

    requirements_by_handle: dict[int, RequirementHandle] = {}
    requirement_refs: set[str] = set()
    for item in projection.requirements:
        if not isinstance(item, RequirementHandle):
            raise _invalid("projection requirement is invalid")
        _strict_handle(
            item.handle, label="projection requirement handle", upper=MAX_REQUIREMENT_HANDLES - 1
        )
        _strict_ref(item.ref, label="projection requirement ref")
        _safe_model_label(item.label, label="projection requirement label")
        if not item.allowed_ops or not item.allowed_ops.issubset(_OP_NAMES):
            raise _invalid("projection requirement operation allowlist is invalid")
        if item.handle in requirements_by_handle or item.ref in requirement_refs:
            raise _invalid("projection requirement handles or refs are duplicated")
        requirements_by_handle[item.handle] = item
        requirement_refs.add(item.ref)

    slots_by_handle: dict[int, SlotGrant] = {}
    nodes_by_handle: dict[int, NodeGrant] = {}
    recipes_by_handle: dict[int, RecipeGrant] = {}
    rows_by_handle: dict[int, ExpansionRow] = {}
    all_handles: set[int] = set()
    all_refs: set[str] = set()
    for authority in projection.authorities:
        if not isinstance(authority, (SlotGrant, NodeGrant, RecipeGrant, ExpansionRow)):
            raise _invalid("projection authority is invalid")
        handle = _strict_handle(authority.handle, label="projection authority handle")
        ref = _strict_ref(authority.ref, label="projection authority ref")
        if handle in all_handles or ref in all_refs:
            raise _invalid("projection authority handles or refs are duplicated")
        all_handles.add(handle)
        all_refs.add(ref)
        _safe_model_label(authority.label, label="projection authority label")
        if isinstance(authority, SlotGrant):
            _strict_ref(authority.anchor_ref, label="slot anchor ref")
            if (
                not isinstance(authority.member, str)
                or MEMBER_RE.fullmatch(authority.member) is None
            ):
                raise _invalid("slot member is invalid")
            if authority.cardinality not in {"one", "many"} or authority.insertion not in {
                "append",
                "replace",
                "exact",
            }:
                raise _invalid("slot cardinality or insertion is invalid")
            if (
                not authority.accepts
                or len(authority.accepts) > 16
                or any(
                    not isinstance(kind, str) or MEMBER_RE.fullmatch(kind) is None
                    for kind in authority.accepts
                )
            ):
                raise _invalid("slot accepted type roster is invalid")
            if not authority.mutations or not authority.mutations.issubset(
                {"attach", "set", "expand"}
            ):
                raise _invalid("slot mutation roster is invalid")
            if authority.basis_spec_sha256 is not None:
                _strict_hash(authority.basis_spec_sha256, label="slot basis spec revision")
            if (
                isinstance(authority.generation, bool)
                or not isinstance(authority.generation, int)
                or authority.generation < 0
            ):
                raise _invalid("slot generation is invalid")
            slots_by_handle[handle] = authority
        elif isinstance(authority, NodeGrant):
            if (
                authority.state not in {"new", "basis"}
                or not isinstance(authority.fragment_type, str)
                or MEMBER_RE.fullmatch(authority.fragment_type) is None
            ):
                raise _invalid("node grant state or fragment type is invalid")
            fragment = _strict_json(authority.fragment, label="node fragment")
            if not hmac.compare_digest(
                bytes_sha256(canonical_json(fragment)),
                _strict_hash(authority.fragment_sha256, label="node fragment hash"),
            ):
                raise _invalid("node fragment hash differs")
            if authority.parent_slot_ref is not None:
                _strict_ref(authority.parent_slot_ref, label="node parent slot ref")
            if authority.basis_spec_sha256 is not None:
                _strict_hash(authority.basis_spec_sha256, label="node basis spec revision")
            if not isinstance(authority.removable, bool):
                raise _invalid("node removable flag is invalid")
            if authority.state == "new":
                if (
                    authority.parent_slot_ref is None
                    or authority.removable
                    or authority.basis_spec_sha256 is not None
                    or authority.basis_path is not None
                ):
                    raise _invalid("new node has an invalid parent, basis locator or removability")
                if authority.fragment_type in _EXCLUDED_NEW_FRAGMENT_TYPES:
                    raise _invalid("new root endpoint fragments are forbidden")
                if not _is_exact_new_fragment(
                    authority.fragment_type, fragment
                ) and not _structural_skeleton_only(fragment):
                    raise _invalid("new structural node contains populated child collections")
            elif authority.basis_spec_sha256 is None or authority.basis_path is None:
                raise _invalid("basis node lacks its exact basis locator")
            if authority.basis_path is not None:
                _strict_basis_path(authority.basis_path, label="node basis path")
            _validate_leaf_bindings(
                value=fragment,
                bindings=authority.leaf_bindings,
                requirement_refs=frozenset(requirement_refs),
                label="node fragment",
            )
            nodes_by_handle[handle] = authority
        elif isinstance(authority, RecipeGrant):
            if (
                not isinstance(authority.recipe_id, str)
                or not authority.recipe_id
                or not isinstance(authority.version, int)
                or authority.version != 1
                or not isinstance(authority.row_type, str)
                or not isinstance(authority.output_type, str)
                or MEMBER_RE.fullmatch(authority.row_type) is None
                or MEMBER_RE.fullmatch(authority.output_type) is None
            ):
                raise _invalid("recipe grant is invalid")
            if (
                not authority.scope_members
                or len(authority.scope_members) > 16
                or len(set(authority.scope_members)) != len(authority.scope_members)
                or any(
                    not isinstance(member, str) or MEMBER_RE.fullmatch(member) is None
                    for member in authority.scope_members
                )
            ):
                raise _invalid("recipe scope member roster is invalid")
            _strict_hash(authority.implementation_sha256, label="recipe implementation hash")
            if (
                not 1 <= authority.max_rows <= MAX_EXPANSION_ROWS
                or not 1 <= authority.max_emitted_mutations <= 128
            ):
                raise _invalid("recipe grant bounds are invalid")
            recipes_by_handle[handle] = authority
        else:
            if (
                not isinstance(authority.recipe_id, str)
                or not authority.recipe_id
                or not isinstance(authority.row_type, str)
                or MEMBER_RE.fullmatch(authority.row_type) is None
            ):
                raise _invalid("expansion row is invalid")
            arguments = _strict_json(authority.arguments, label="expansion row arguments")
            if not hmac.compare_digest(
                bytes_sha256(canonical_json(arguments)),
                _strict_hash(authority.row_sha256, label="expansion row hash"),
            ):
                raise _invalid("expansion row hash differs")
            _validate_leaf_bindings(
                value=arguments,
                bindings=authority.leaf_bindings,
                requirement_refs=frozenset(requirement_refs),
                label="expansion row",
            )
            rows_by_handle[handle] = authority

    slots_by_ref = {slot.ref: slot for slot in slots_by_handle.values()}
    known_slot_refs = set(slots_by_ref)
    for node in nodes_by_handle.values():
        if node.parent_slot_ref is not None and node.parent_slot_ref not in known_slot_refs:
            # A dynamic / forward virtual slot is deliberately not expressible in
            # v2.  It must be a server-projected slot in a later validated plan.
            raise _invalid("node references an unknown or forward virtual slot")
        placements = _STRUCTURAL_NEW_FRAGMENT_PLACEMENTS.get(node.fragment_type)
        if (
            node.state == "new"
            and placements is not None
            and _is_exact_new_fragment(node.fragment_type, node.fragment)
        ):
            parent = slots_by_ref[node.parent_slot_ref]
            placement = (parent.member, parent.cardinality, parent.insertion)
            if (
                placement not in placements
                or node.fragment_type not in parent.accepts
                or "attach" not in parent.mutations
            ):
                raise _invalid("new structural node placement is incompatible with the builder")
    expected_revision = compact_authority_projection_revision(
        surface_revision=projection.surface_revision,
        requirements=projection.requirements,
        authorities=projection.authorities,
    )
    if not hmac.compare_digest(expected_revision, projection.projection_revision):
        raise _invalid("compact authority projection revision differs")
    return CompactProjectionIndex(
        projection=projection,
        requirements_by_handle=requirements_by_handle,
        slots_by_handle=slots_by_handle,
        nodes_by_handle=nodes_by_handle,
        recipes_by_handle=recipes_by_handle,
        rows_by_handle=rows_by_handle,
    )


def validate_create_delta_plan_v2_body_shape(value: Any) -> list[str]:
    try:
        raw = canonical_json(value)
    except BrainError:
        return ["compact CREATE body is not strict JSON"]
    if not raw or len(raw) > MAX_JSON_BYTES:
        return ["compact CREATE body exceeds its JSON bound"]
    errors = sorted(
        _BODY_VALIDATOR.iter_errors(value),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    return [item.message for item in errors]


def _body_requirements(
    operation: Mapping[str, Any], index: CompactProjectionIndex
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    handles_raw = operation["q"]
    if (
        not isinstance(handles_raw, list)
        or not 1 <= len(handles_raw) <= MAX_REQUIREMENTS_PER_OPERATION
    ):
        raise _invalid("operation requirement handles are invalid")
    handles = tuple(
        _strict_handle(
            item, label="operation requirement handle", upper=MAX_REQUIREMENT_HANDLES - 1
        )
        for item in handles_raw
    )
    if len(set(handles)) != len(handles):
        raise _invalid("operation requirement handles are duplicated")
    requirements: list[RequirementHandle] = []
    for handle in handles:
        try:
            requirements.append(index.requirements_by_handle[handle])
        except KeyError as error:
            raise _invalid("operation references an unknown requirement handle") from error
    return handles, tuple(item.ref for item in requirements)


def _node_requirements(node: NodeGrant, index: CompactProjectionIndex) -> frozenset[str]:
    return _validate_leaf_bindings(
        value=_strict_json(node.fragment, label="node fragment"),
        bindings=node.leaf_bindings,
        requirement_refs=frozenset(item.ref for item in index.requirements_by_handle.values()),
        label="node fragment",
    )


def _check_requirements(
    *,
    requirement_refs: tuple[str, ...],
    op_name: str,
    bound_requirements: frozenset[str],
) -> None:
    declared = frozenset(requirement_refs)
    if declared != bound_requirements:
        raise _invalid("operation requirement binding is not reciprocal and exact")
    if not declared:
        raise _invalid("operation has no active requirements")
    # Caller has already resolved every ref, but this makes the exact action
    # binding readable at the admission site.
    if op_name not in _OP_NAMES:
        raise _invalid("operation kind is invalid")


def _slot_active(
    index: CompactProjectionIndex, slot: SlotGrant, active_node_refs: frozenset[str]
) -> bool:
    """A slot under a new node becomes live only after that node was attached."""

    by_ref = {node.ref: node for node in index.nodes_by_handle.values()}
    anchor = by_ref.get(slot.anchor_ref)
    return anchor is None or anchor.state == "basis" or anchor.ref in active_node_refs


def _slot(
    index: CompactProjectionIndex, handle: Any, *, active_node_refs: frozenset[str]
) -> SlotGrant:
    try:
        slot = index.slots_by_handle[_strict_handle(handle, label="slot handle")]
    except KeyError as error:
        raise _invalid("operation references an unknown or forward virtual slot") from error
    if not _slot_active(index, slot, active_node_refs):
        raise _invalid("operation references a forward virtual slot")
    return slot


def _node(index: CompactProjectionIndex, handle: Any) -> NodeGrant:
    try:
        return index.nodes_by_handle[_strict_handle(handle, label="node handle")]
    except KeyError as error:
        raise _invalid("operation references an unknown node handle") from error


def _recipe(index: CompactProjectionIndex, handle: Any) -> RecipeGrant:
    try:
        return index.recipes_by_handle[_strict_handle(handle, label="recipe handle")]
    except KeyError as error:
        raise _invalid("operation references an unknown recipe handle") from error


def _row(index: CompactProjectionIndex, handle: Any) -> ExpansionRow:
    try:
        return index.rows_by_handle[_strict_handle(handle, label="row handle")]
    except KeyError as error:
        raise _invalid("operation references an unknown expansion row handle") from error


def _row_target_slots(
    index: CompactProjectionIndex, rows: Sequence[ExpansionRow]
) -> tuple[SlotGrant, ...]:
    """Extract only explicit structural target slots from private recipe rows.

    Exact recipe semantics live in the combinator module.  This boundary merely
    guarantees that a row cannot target a child slot before its owning node was
    attached earlier in the same compact body.
    """

    refs: list[str] = []
    for row in rows:
        arguments = _strict_json(row.arguments, label="expansion row arguments")
        if not isinstance(arguments, Mapping):
            continue
        direct = arguments.get("target_slot_ref")
        if direct is not None:
            if not isinstance(direct, str):
                raise _invalid("expansion row target slot is invalid")
            refs.append(direct)
        quota_targets = arguments.get("targets")
        if quota_targets is not None:
            if isinstance(quota_targets, (str, bytes)) or not isinstance(quota_targets, Sequence):
                raise _invalid("expansion row target slot roster is invalid")
            for target in quota_targets:
                if not isinstance(target, Mapping) or not isinstance(
                    target.get("target_slot_ref"), str
                ):
                    raise _invalid("expansion row target slot roster is invalid")
                refs.append(target["target_slot_ref"])
    slots_by_ref = {slot.ref: slot for slot in index.slots_by_handle.values()}
    try:
        return tuple(slots_by_ref[ref] for ref in refs)
    except KeyError as error:
        raise _invalid("expansion row targets an unknown slot") from error


def _decoder_active_requirement_handles(
    index: CompactProjectionIndex, active_requirement_handles: Sequence[int] | None
) -> tuple[int, ...]:
    """Resolve a canonical active roster without accepting an ambient default."""

    if active_requirement_handles is None:
        handles = tuple(sorted(index.requirements_by_handle))
    else:
        if isinstance(active_requirement_handles, (str, bytes)) or not isinstance(
            active_requirement_handles, Sequence
        ):
            raise _invalid("active requirement roster is invalid")
        handles = tuple(
            _strict_handle(
                item, label="active requirement handle", upper=MAX_REQUIREMENT_HANDLES - 1
            )
            for item in active_requirement_handles
        )
    if not handles or len(handles) != len(set(handles)):
        raise _invalid("active requirement roster is invalid")
    if any(handle not in index.requirements_by_handle for handle in handles):
        raise _invalid("active requirement roster contains an unknown requirement")
    return tuple(sorted(handles))


def _decoder_constraint_digest_payload(
    *,
    projection_revision: str,
    active_requirement_handles: tuple[int, ...],
    direct_operations: tuple[CreatePlanV2DirectOperationConstraint, ...],
    expansion_descriptors: tuple[CreatePlanV2ExpansionDescriptor, ...],
) -> dict[str, Any]:
    return {
        "v": 1,
        "p": projection_revision,
        "a": list(active_requirement_handles),
        "d": [item.body() for item in direct_operations],
        "x": [item.payload() for item in expansion_descriptors],
    }


def _validate_create_plan_v2_decoder_constraint(
    constraint: CreatePlanV2DecoderConstraint,
) -> None:
    """Validate the immutable, handle-only decoder constraint itself."""

    if not isinstance(constraint, CreatePlanV2DecoderConstraint):
        raise _invalid("CREATE decoder constraint is invalid")
    _strict_hash(constraint.projection_revision, label="CREATE decoder constraint projection")
    active = constraint.active_requirement_handles
    if not isinstance(active, tuple) or not active or len(active) > MAX_REQUIREMENT_HANDLES:
        raise _invalid("CREATE decoder constraint active roster is invalid")
    if tuple(sorted(active)) != active or len(set(active)) != len(active):
        raise _invalid("CREATE decoder constraint active roster is not canonical")
    for handle in active:
        _strict_handle(
            handle,
            label="CREATE decoder constraint active requirement handle",
            upper=MAX_REQUIREMENT_HANDLES - 1,
        )
    direct = constraint.direct_operations
    if not isinstance(direct, tuple) or len(direct) > MAX_DECODER_DIRECT_ALTERNATIVES:
        raise _invalid("CREATE decoder direct alternatives exceed their bound")
    direct_bodies: list[dict[str, Any]] = []
    for item in direct:
        if not isinstance(item, CreatePlanV2DirectOperationConstraint):
            raise _invalid("CREATE decoder direct alternative is invalid")
        if item.kind not in {"a", "s", "d"}:
            raise _invalid("CREATE decoder direct alternative kind is invalid")
        handles = item.requirement_handles
        if (
            not isinstance(handles, tuple)
            or not handles
            or len(handles) > MAX_REQUIREMENTS_PER_OPERATION
            or tuple(sorted(handles)) != handles
            or len(set(handles)) != len(handles)
            or any(handle not in active for handle in handles)
        ):
            raise _invalid("CREATE decoder direct requirement roster is invalid")
        for handle in handles:
            _strict_handle(
                handle,
                label="CREATE decoder direct requirement handle",
                upper=MAX_REQUIREMENT_HANDLES - 1,
            )
        _strict_handle(item.node_handle, label="CREATE decoder direct node handle")
        if item.kind == "d":
            if item.slot_handle is not None:
                raise _invalid("CREATE decoder remove alternative has a slot")
        else:
            if item.slot_handle is None:
                raise _invalid("CREATE decoder direct alternative lacks a slot")
            _strict_handle(item.slot_handle, label="CREATE decoder direct slot handle")
        direct_bodies.append(item.body())
    if direct_bodies != sorted(direct_bodies, key=canonical_json):
        raise _invalid("CREATE decoder direct alternatives are not canonical")
    if len({canonical_json(item) for item in direct_bodies}) != len(direct_bodies):
        raise _invalid("CREATE decoder direct alternatives are duplicated")

    expansions = constraint.expansion_descriptors
    if not isinstance(expansions, tuple) or len(expansions) > MAX_DECODER_EXPANSION_DESCRIPTORS:
        raise _invalid("CREATE decoder expansion descriptors exceed their bound")
    expansion_payloads: list[dict[str, Any]] = []
    for item in expansions:
        if not isinstance(item, CreatePlanV2ExpansionDescriptor):
            raise _invalid("CREATE decoder expansion descriptor is invalid")
        _strict_handle(item.slot_handle, label="CREATE decoder expansion slot handle")
        _strict_handle(item.recipe_handle, label="CREATE decoder expansion recipe handle")
        rows = item.row_handles
        if (
            not isinstance(rows, tuple)
            or not rows
            or len(rows) > MAX_EXPANSION_ROWS
            or tuple(sorted(rows)) != rows
            or len(set(rows)) != len(rows)
        ):
            raise _invalid("CREATE decoder expansion row roster is invalid")
        for handle in rows:
            _strict_handle(handle, label="CREATE decoder expansion row handle")
        expansion_payloads.append(item.payload())
    if expansion_payloads != sorted(expansion_payloads, key=canonical_json):
        raise _invalid("CREATE decoder expansion descriptors are not canonical")
    if len({canonical_json(item) for item in expansion_payloads}) != len(expansion_payloads):
        raise _invalid("CREATE decoder expansion descriptors are duplicated")
    if not direct and not expansions:
        raise _invalid("CREATE decoder constraint has no alternatives")

    payload = _decoder_constraint_digest_payload(
        projection_revision=constraint.projection_revision,
        active_requirement_handles=active,
        direct_operations=direct,
        expansion_descriptors=expansions,
    )
    raw = canonical_json(payload)
    if len(raw) > MAX_DECODER_CONSTRAINT_BYTES:
        raise _invalid("CREATE decoder constraint exceeds its byte bound")
    if not hmac.compare_digest(
        bytes_sha256(raw), _strict_hash(constraint.constraint_sha256, label="CREATE decoder digest")
    ):
        raise _invalid("CREATE decoder constraint digest differs")


def derive_create_plan_v2_decoder_constraint(
    projection: CompactAuthorityProjection,
    active_requirement_handles: Sequence[int] | None = None,
) -> CreatePlanV2DecoderConstraint:
    """Derive the smallest model-safe pre-admission grammar from one projection.

    Direct operations are enumerated only when all role and reciprocal leaf
    evidence checks already hold.  Expansion rows are described by bounded
    role-safe triples instead: their exact requirement reciprocity, ordering
    and virtual-slot lifecycle remain deliberately enforced by full admission.
    """

    index = validate_compact_authority_projection(projection)
    active = _decoder_active_requirement_handles(index, active_requirement_handles)
    active_set = frozenset(active)
    requirement_handles_by_ref = {
        item.ref: handle for handle, item in index.requirements_by_handle.items()
    }

    def node_requirements(node: NodeGrant) -> tuple[int, ...] | None:
        refs = _node_requirements(node, index)
        handles = tuple(sorted(requirement_handles_by_ref[ref] for ref in refs))
        if not handles or not frozenset(handles).issubset(active_set):
            return None
        return handles

    def authorized(kind: str, handles: tuple[int, ...]) -> bool:
        return all(kind in index.requirements_by_handle[handle].allowed_ops for handle in handles)

    direct: list[CreatePlanV2DirectOperationConstraint] = []
    for slot in index.slots_by_handle.values():
        for node in index.nodes_by_handle.values():
            handles = node_requirements(node)
            if handles is None or node.fragment_type not in slot.accepts:
                continue
            if (
                node.state == "new"
                and "attach" in slot.mutations
                and node.parent_slot_ref == slot.ref
                and authorized("attach", handles)
            ):
                direct.append(
                    CreatePlanV2DirectOperationConstraint("a", handles, slot.handle, node.handle)
                )
            if (
                "set" in slot.mutations
                and node.parent_slot_ref == slot.ref
                and authorized("set", handles)
            ):
                direct.append(
                    CreatePlanV2DirectOperationConstraint("s", handles, slot.handle, node.handle)
                )
    for node in index.nodes_by_handle.values():
        handles = node_requirements(node)
        if (
            handles is not None
            and node.state == "basis"
            and node.removable
            and authorized("remove", handles)
        ):
            direct.append(CreatePlanV2DirectOperationConstraint("d", handles, None, node.handle))

    # Each expansion descriptor names only a role-compatible slot/recipe pair
    # and that recipe's verified row-handle roster.  Selecting rows remains
    # bounded by the schema and this descriptor; execution/admission verifies
    # the private expansion semantics again.
    expansions: list[CreatePlanV2ExpansionDescriptor] = []
    for slot in index.slots_by_handle.values():
        if "expand" not in slot.mutations:
            continue
        for recipe in index.recipes_by_handle.values():
            if slot.member not in recipe.scope_members:
                continue
            rows = tuple(
                sorted(
                    row.handle
                    for row in index.rows_by_handle.values()
                    if row.recipe_id == recipe.recipe_id and row.row_type == recipe.row_type
                )
            )
            if rows:
                expansions.append(CreatePlanV2ExpansionDescriptor(slot.handle, recipe.handle, rows))

    direct_tuple = tuple(sorted(direct, key=lambda item: canonical_json(item.body())))
    expansions_tuple = tuple(sorted(expansions, key=lambda item: canonical_json(item.payload())))
    if len(direct_tuple) > MAX_DECODER_DIRECT_ALTERNATIVES:
        raise _invalid("CREATE decoder direct alternatives exceed their bound")
    if len(expansions_tuple) > MAX_DECODER_EXPANSION_DESCRIPTORS:
        raise _invalid("CREATE decoder expansion descriptors exceed their bound")
    payload = _decoder_constraint_digest_payload(
        projection_revision=projection.projection_revision,
        active_requirement_handles=active,
        direct_operations=direct_tuple,
        expansion_descriptors=expansions_tuple,
    )
    if len(canonical_json(payload)) > MAX_DECODER_CONSTRAINT_BYTES:
        raise _invalid("CREATE decoder constraint exceeds its byte bound")
    constraint = CreatePlanV2DecoderConstraint(
        projection.projection_revision,
        active,
        direct_tuple,
        expansions_tuple,
        bytes_sha256(canonical_json(payload)),
    )
    _validate_create_plan_v2_decoder_constraint(constraint)
    return constraint


def validate_create_plan_v2_decoder_constraint_membership(
    body: Any, constraint: CreatePlanV2DecoderConstraint
) -> None:
    """Reject a body outside its exact direct/role-safe expansion grammar.

    This is intentionally a pre-admission filter.  A passing body must still
    go through :func:`admit_create_delta_plan_v2`, which owns execution order,
    expansion reciprocity and complete active-roster coverage.
    """

    _validate_create_plan_v2_decoder_constraint(constraint)
    shape_errors = validate_create_delta_plan_v2_body_shape(body)
    if shape_errors:
        raise _invalid(shape_errors[0])
    direct = {canonical_json(item.body()) for item in constraint.direct_operations}
    expansion_by_pair = {
        (item.slot_handle, item.recipe_handle): frozenset(item.row_handles)
        for item in constraint.expansion_descriptors
    }
    active = frozenset(constraint.active_requirement_handles)
    for operation in body["o"]:
        kind = operation["k"]
        if kind in {"a", "s", "d"}:
            if canonical_json(operation) not in direct:
                raise _invalid("CREATE decoder body is outside its direct authority grammar")
            continue
        if kind != "x":  # schema currently makes this unreachable; keep the boundary explicit.
            raise _invalid("CREATE decoder body operation kind is invalid")
        handles = operation["q"]
        if (
            not isinstance(handles, list)
            or not handles
            or len(set(handles)) != len(handles)
            or any(handle not in active for handle in handles)
        ):
            raise _invalid("CREATE decoder expansion requirements are outside the active roster")
        try:
            allowed_rows = expansion_by_pair[(operation["s"], operation["r"])]
        except KeyError as error:
            raise _invalid("CREATE decoder expansion is outside its role grammar") from error
        rows = operation["w"]
        if (
            not isinstance(rows, list)
            or not rows
            or len(set(rows)) != len(rows)
            or not frozenset(rows).issubset(allowed_rows)
        ):
            raise _invalid("CREATE decoder expansion rows are outside their role grammar")


def _admit_operation(
    operation: Mapping[str, Any],
    ordinal: int,
    index: CompactProjectionIndex,
    *,
    active_node_refs: frozenset[str],
) -> CreateDeltaOperationV2:
    kind = operation["k"]
    _, requirement_refs = _body_requirements(operation, index)
    requirements = [
        item
        for item in index.requirements_by_handle.values()
        if item.ref in frozenset(requirement_refs)
    ]
    op_name = _OP_CODE_TO_NAME.get(kind)
    if op_name is None or any(op_name not in item.allowed_ops for item in requirements):
        raise _invalid("operation kind is not authorized by every requirement")
    if kind == "a":
        slot = _slot(index, operation["s"], active_node_refs=active_node_refs)
        node = _node(index, operation["n"])
        if (
            "attach" not in slot.mutations
            or node.state != "new"
            or node.parent_slot_ref != slot.ref
        ):
            raise _invalid("attach operation is incompatible with its slot or node")
        if node.fragment_type not in slot.accepts:
            raise _invalid("attach node type is not accepted by its slot")
        _check_requirements(
            requirement_refs=requirement_refs,
            op_name="attach",
            bound_requirements=_node_requirements(node, index),
        )
        return AttachOpV2(ordinal, requirement_refs, slot.ref, node.ref)
    if kind == "s":
        slot = _slot(index, operation["s"], active_node_refs=active_node_refs)
        value = _node(index, operation["v"])
        if (
            "set" not in slot.mutations
            or value.fragment_type not in slot.accepts
            or value.parent_slot_ref != slot.ref
        ):
            raise _invalid("set operation is incompatible with its slot or value")
        _check_requirements(
            requirement_refs=requirement_refs,
            op_name="set",
            bound_requirements=_node_requirements(value, index),
        )
        return SetOpV2(ordinal, requirement_refs, slot.ref, value.ref)
    if kind == "d":
        node = _node(index, operation["n"])
        if node.state != "basis" or not node.removable:
            raise _invalid("remove operation may target only a removable basis node")
        _check_requirements(
            requirement_refs=requirement_refs,
            op_name="remove",
            bound_requirements=_node_requirements(node, index),
        )
        return RemoveOpV2(ordinal, requirement_refs, node.ref)
    slot = _slot(index, operation["s"], active_node_refs=active_node_refs)
    recipe = _recipe(index, operation["r"])
    row_handles = operation["w"]
    if "expand" not in slot.mutations or slot.member not in recipe.scope_members:
        raise _invalid("expand operation is incompatible with its slot or recipe")
    if (
        not isinstance(row_handles, list)
        or not row_handles
        or len(row_handles) > min(MAX_EXPANSION_ROWS, recipe.max_rows)
    ):
        raise _invalid("expand row roster is invalid")
    if len(set(row_handles)) != len(row_handles):
        raise _invalid("expand row handles are duplicated")
    rows = tuple(_row(index, handle) for handle in row_handles)
    if any(row.recipe_id != recipe.recipe_id or row.row_type != recipe.row_type for row in rows):
        raise _invalid("expand row does not match its recipe")
    if any(
        not _slot_active(index, target, active_node_refs)
        for target in _row_target_slots(index, rows)
    ):
        raise _invalid("expand operation references a forward virtual slot")
    # Local import avoids the intentional plan -> combinator runtime cycle:
    # combinators use these authority types, while admission executes the pure,
    # code-pinned recipe so it can bind the same complete evidence as execution.
    from metis_model1.brain_create_combinators import execute_combinator

    try:
        expansion = execute_combinator(
            index.projection,
            slot_handle=slot.handle,
            recipe_handle=recipe.handle,
            row_handles=tuple(row.handle for row in rows),
        )
    except BrainError as error:
        raise _invalid("expansion recipe rejects its projected authority") from error
    _check_requirements(
        requirement_refs=requirement_refs,
        op_name="expand",
        bound_requirements=expansion.requirement_refs,
    )
    return ExpandOpV2(
        ordinal, requirement_refs, slot.ref, recipe.ref, tuple(row.ref for row in rows)
    )


def admit_create_delta_plan_v2(
    body: Any,
    *,
    projection: CompactAuthorityProjection,
    mode: Literal["initial", "refinement"],
    context_revision: str,
    semantic_revision: str,
    target_ref: str,
    basis_ref: str | None,
    active_requirement_handles: Sequence[int] | None = None,
) -> CreateDeltaPlanV2:
    """Expand one decoder body under exact server-owned authority.

    Revisions, target/basis, requirement refs and source ordinals are injected
    here rather than being repeated in the model wire.
    """

    shape_errors = validate_create_delta_plan_v2_body_shape(body)
    if shape_errors:
        raise _invalid(shape_errors[0])
    if mode not in {"initial", "refinement"}:
        raise _invalid("CREATE plan mode is invalid")
    _strict_hash(context_revision, label="context revision")
    _strict_hash(semantic_revision, label="semantic revision")
    target_ref = _strict_ref(target_ref, label="target ref")
    if basis_ref is not None:
        basis_ref = _strict_ref(basis_ref, label="basis ref")
    if (mode == "initial") != (basis_ref is None):
        raise _invalid("CREATE plan mode and basis differ")
    index = validate_compact_authority_projection(projection)
    if active_requirement_handles is None:
        active_handles = tuple(sorted(index.requirements_by_handle))
    else:
        if isinstance(active_requirement_handles, (str, bytes)) or not isinstance(
            active_requirement_handles, Sequence
        ):
            raise _invalid("active requirement roster is invalid")
        active_handles = tuple(
            _strict_handle(
                item, label="active requirement handle", upper=MAX_REQUIREMENT_HANDLES - 1
            )
            for item in active_requirement_handles
        )
    if not active_handles or len(active_handles) != len(set(active_handles)):
        raise _invalid("active requirement roster is invalid")
    if any(handle not in index.requirements_by_handle for handle in active_handles):
        raise _invalid("active requirement roster contains an unknown requirement")
    operations_raw = body["o"]
    active_node_refs = frozenset(
        node.ref for node in index.nodes_by_handle.values() if node.state == "basis"
    )
    operations_list: list[CreateDeltaOperationV2] = []
    for ordinal, operation in enumerate(operations_raw):
        admitted = _admit_operation(
            operation,
            ordinal,
            index,
            active_node_refs=active_node_refs,
        )
        operations_list.append(admitted)
        if isinstance(admitted, AttachOpV2):
            active_node_refs = frozenset((*active_node_refs, admitted.node_ref))
    operations = tuple(operations_list)
    used_refs = frozenset(ref for operation in operations for ref in operation.requirement_refs)
    expected_refs = frozenset(index.requirements_by_handle[handle].ref for handle in active_handles)
    if used_refs != expected_refs:
        raise _invalid("CREATE plan does not cover the exact active requirement roster")
    # Revisions are independently rooted in the request/snapshot; surface and
    # projection are rooted in the validated private projection.
    return CreateDeltaPlanV2(
        mode=mode,
        context_revision=context_revision,
        semantic_revision=semantic_revision,
        surface_revision=projection.surface_revision,
        projection_revision=projection.projection_revision,
        target_ref=target_ref,
        basis_ref=basis_ref,
        requirements=tuple(index.requirements_by_handle[handle].ref for handle in active_handles),
        operations=operations,
    )


def parse_create_delta_plan_v2_json(raw: str, **kwargs: Any) -> CreateDeltaPlanV2:
    """Parse one strict compact body then perform host-only v2 admission."""

    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise _invalid("compact CREATE body exceeds its JSON bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if key in output:
                raise ValueError("duplicate JSON member")
            output[key] = value
        return output

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid("compact CREATE body JSON is invalid") from error
    return admit_create_delta_plan_v2(decoded, **kwargs)


def initial_create_endpoint_skeleton(name: str) -> dict[str, Any]:
    """The only empty initial CREATE spec; later expansion may fill typed slots."""

    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 256:
        raise _invalid("initial endpoint name is invalid")
    return {
        "schema_version": 1,
        "contract_id": "metis-brain-create-endpoint-spec/v1",
        "endpoint": {
            "name": name,
            "reference": None,
            "params": {"timeout": None, "expires": None, "paginate": None},
            "inputs": [],
            "needs_time": False,
            "attributes": [],
            "input_pipeline": [],
            "output_pipeline": [],
            "inheritance": {"without_input": [], "without_output": []},
            "context": [],
            "blocks": [],
            "variants": [],
            "output": None,
        },
    }


__all__ = [
    "AttachOpV2",
    "AuthorityGrant",
    "COMPACT_AUTHORITY_PROJECTION_V2_CONTRACT",
    "CREATE_DELTA_PLAN_BODY_V2_SCHEMA",
    "CREATE_DELTA_PLAN_BODY_V2_SCHEMA_PATH",
    "CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256",
    "CREATE_DELTA_PLAN_V2_CONTRACT",
    "CREATE_DELTA_PLAN_V2_SCHEMA",
    "CREATE_DELTA_PLAN_V2_SCHEMA_PATH",
    "CREATE_DELTA_PLAN_V2_SCHEMA_SHA256",
    "CREATE_V2_NEW_FRAGMENT_TYPES",
    "CompactAuthorityProjection",
    "CompactProjectionIndex",
    "CreatePlanV2DecoderConstraint",
    "CreatePlanV2DirectOperationConstraint",
    "CreatePlanV2ExpansionDescriptor",
    "CreateDeltaOperationV2",
    "CreateDeltaPlanV2",
    "CreateDeltaPlanV2Error",
    "ExpandOpV2",
    "ExpansionRow",
    "FragmentLeafBinding",
    "MAX_AUTHORITY_HANDLES",
    "MAX_DECODER_CONSTRAINT_BYTES",
    "MAX_DECODER_DIRECT_ALTERNATIVES",
    "MAX_DECODER_EXPANSION_DESCRIPTORS",
    "MAX_EXPANSION_ROWS",
    "MAX_JSON_BYTES",
    "MAX_OPERATIONS",
    "MAX_REQUIREMENT_HANDLES",
    "NodeGrant",
    "RecipeGrant",
    "RemoveOpV2",
    "RequirementHandle",
    "SetOpV2",
    "SlotGrant",
    "admit_create_delta_plan_v2",
    "compact_authority_projection_revision",
    "derive_create_plan_v2_decoder_constraint",
    "initial_create_endpoint_skeleton",
    "parse_create_delta_plan_v2_json",
    "validate_compact_authority_projection",
    "validate_create_plan_v2_decoder_constraint_membership",
    "validate_create_delta_plan_v2_body_shape",
]
