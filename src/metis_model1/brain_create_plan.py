"""Strict, non-authoritative CreateDeltaPlan contract for Metis Brain.

The model may select only host-issued, role-typed references and the closed
operation vocabulary below.  A plan never contains Metis source, snippets,
paths, templates, identifiers, or free-form text.  It is still untrusted: the
host must validate request-bound revisions, requirement coverage, reference
roles and dependency order before a future permit or renderer may consume it.

Bounds are deliberately conservative for the frozen ten-journey census.  The
largest observed repeated family has 27 members, so repeat/matrix and binding
lists allow 32 entries.  Ninety-six operations leave more than three times
that family size while retaining a finite admission and decoding envelope.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREATE_DELTA_PLAN_SCHEMA_PATH = PROJECT_ROOT / "schemas/metis-brain-create-delta-plan.schema.json"
CREATE_DELTA_PLAN_CONTRACT = "metis-brain-create-delta-plan/v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

MAX_JSON_BYTES = 65_536
MAX_OPERATIONS = 96
MAX_REQUIREMENTS = 64
MAX_DEPENDENCIES = 16
MAX_COLLECTION_ITEMS = 32
MAX_MATRIX_AXES = 8

OPERATION_KINDS = frozenset(
    {
        "endpoint.create",
        "endpoint.set_metadata",
        "input.declare",
        "context.bind",
        "block.create",
        "block.set_parameter",
        "block.instantiate",
        "query.set_catalog",
        "query.add_predicate",
        "query.set_order",
        "query.set_take",
        "query.set_pagination",
        "query.set_view_all",
        "query.set_pipeline",
        "fallback.set",
        "response.set",
        "output.set_pipeline",
        "repeat.expand",
        "matrix.expand",
    }
)

HOST_REF_ROLES = frozenset(
    {
        "basis",
        "block",
        "block_instance_slot",
        "block_slot",
        "catalog",
        "catalog_value",
        "context_slot",
        "endpoint",
        "endpoint_slot",
        "expansion_pattern",
        "expansion_slot",
        "fallback_slot",
        "field",
        "input",
        "input_slot",
        "input_type",
        "matrix_axis",
        "metadata_key",
        "output_slot",
        "parameter_key",
        "pipeline",
        "pipeline_step",
        "predicate_operator",
        "query",
        "requirement",
        "response_format",
        "response_slot",
        "result",
        "scalar",
        "target",
    }
)

_FORBIDDEN_PAYLOAD_KEYS = frozenset(
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

_OP_REF_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "endpoint.create": {"endpoint_ref": frozenset({"endpoint_slot"})},
    "endpoint.set_metadata": {
        "endpoint_ref": frozenset({"endpoint"}),
        "key_ref": frozenset({"metadata_key"}),
        "value_ref": frozenset({"scalar"}),
    },
    "input.declare": {
        "endpoint_ref": frozenset({"endpoint"}),
        "input_ref": frozenset({"input_slot"}),
        "type_ref": frozenset({"input_type"}),
        "default_ref": frozenset({"scalar", "catalog_value"}),
    },
    "context.bind": {
        "endpoint_ref": frozenset({"endpoint"}),
        "context_ref": frozenset({"context_slot"}),
        "value_ref": frozenset({"scalar", "input", "catalog_value"}),
    },
    "block.create": {
        "endpoint_ref": frozenset({"endpoint"}),
        "block_ref": frozenset({"block_slot"}),
    },
    "block.set_parameter": {
        "block_ref": frozenset({"block"}),
        "parameter_ref": frozenset({"parameter_key"}),
        "value_ref": frozenset({"scalar", "input", "catalog_value"}),
    },
    "block.instantiate": {
        "block_ref": frozenset({"block"}),
        "instance_ref": frozenset({"block_instance_slot"}),
    },
    "query.set_catalog": {
        "query_ref": frozenset({"query"}),
        "catalog_ref": frozenset({"catalog"}),
    },
    "query.add_predicate": {
        "query_ref": frozenset({"query"}),
        "field_ref": frozenset({"field"}),
        "operator_ref": frozenset({"predicate_operator"}),
    },
    "query.set_order": {
        "query_ref": frozenset({"query"}),
        "key_ref": frozenset({"field"}),
    },
    "query.set_take": {"query_ref": frozenset({"query"})},
    "query.set_pagination": {
        "query_ref": frozenset({"query"}),
        "page_input_ref": frozenset({"input"}),
    },
    "query.set_view_all": {"query_ref": frozenset({"query"})},
    "query.set_pipeline": {
        "query_ref": frozenset({"query"}),
        "pipeline_ref": frozenset({"pipeline"}),
    },
    "fallback.set": {
        "fallback_slot_ref": frozenset({"fallback_slot"}),
        "primary_ref": frozenset({"block", "query", "result"}),
        "secondary_ref": frozenset({"block", "query", "result"}),
    },
    "response.set": {
        "response_ref": frozenset({"response_slot"}),
        "format_ref": frozenset({"response_format"}),
        "source_ref": frozenset({"block", "query", "result"}),
    },
    "output.set_pipeline": {
        "output_ref": frozenset({"output_slot"}),
        "pipeline_ref": frozenset({"pipeline"}),
    },
    "repeat.expand": {
        "target_ref": frozenset({"expansion_slot"}),
        "pattern_ref": frozenset({"expansion_pattern"}),
    },
    "matrix.expand": {
        "target_ref": frozenset({"expansion_slot"}),
        "pattern_ref": frozenset({"expansion_pattern"}),
    },
}

_OP_REF_LIST_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "query.add_predicate": {"value_refs": frozenset({"catalog_value", "input", "scalar"})},
    "query.set_pipeline": {"step_refs": frozenset({"pipeline_step"})},
    "output.set_pipeline": {"step_refs": frozenset({"pipeline_step"})},
    "repeat.expand": {"item_refs": frozenset({"catalog_value", "input", "scalar"})},
    "matrix.expand": {"axis_refs": frozenset({"matrix_axis"})},
}


class CreateDeltaPlanError(ValueError):
    """Raised when the tracked CreateDeltaPlan schema cannot be loaded."""


def _load_schema() -> dict[str, Any]:
    try:
        value = json.loads(CREATE_DELTA_PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - tracked contract must fail closed
        raise CreateDeltaPlanError("CreateDeltaPlan schema is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise CreateDeltaPlanError("CreateDeltaPlan schema is invalid")
    return value


CREATE_DELTA_PLAN_SCHEMA = _load_schema()
CREATE_DELTA_PLAN_SCHEMA_SHA256 = bytes_sha256(canonical_json(CREATE_DELTA_PLAN_SCHEMA))
_SCHEMA_VALIDATOR = Draft202012Validator(CREATE_DELTA_PLAN_SCHEMA)


def _schema_errors(value: Any) -> list[str]:
    errors = sorted(
        _SCHEMA_VALIDATOR.iter_errors(value),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    return [error.message for error in errors]


def validate_create_delta_plan_shape(value: Any) -> list[str]:
    """Validate only the public JSON shape; request authority is checked later."""

    try:
        raw = canonical_json(value)
    except BrainError:
        return ["CreateDeltaPlan is not strict JSON"]
    if not raw or len(raw) > MAX_JSON_BYTES:
        return ["CreateDeltaPlan exceeds its JSON bound"]
    return _schema_errors(value)


def _forbidden_payload_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _FORBIDDEN_PAYLOAD_KEYS:
                return str(key)
            found = _forbidden_payload_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _forbidden_payload_key(nested)
            if found is not None:
                return found
    return None


def _collection_of_strings(value: Any) -> frozenset[str] | None:
    if isinstance(value, str):
        return frozenset({value})
    if not isinstance(value, Collection):
        return None
    if not value or any(not isinstance(item, str) for item in value):
        return None
    return frozenset(value)


def _normalize_issued_roles(
    issued_refs: Mapping[str, str | Collection[str]],
) -> tuple[dict[str, frozenset[str]], str | None]:
    normalized: dict[str, frozenset[str]] = {}
    for ref, raw_roles in issued_refs.items():
        if not isinstance(ref, str) or HOST_REF_RE.fullmatch(ref) is None:
            return {}, "issued host reference is invalid"
        roles = _collection_of_strings(raw_roles)
        if roles is None or not roles.issubset(HOST_REF_ROLES):
            return {}, "issued host reference has an invalid role"
        normalized[ref] = roles
    return normalized, None


def _normalize_requirement_kinds(
    expected_requirement_kinds: Mapping[str, Collection[str] | str],
) -> tuple[dict[str, frozenset[str]], str | None]:
    if not expected_requirement_kinds or len(expected_requirement_kinds) > MAX_REQUIREMENTS:
        return {}, "expected requirement roster is empty or exceeds its bound"
    normalized: dict[str, frozenset[str]] = {}
    for ref, raw_kinds in expected_requirement_kinds.items():
        if not isinstance(ref, str) or HOST_REF_RE.fullmatch(ref) is None:
            return {}, "expected requirement reference is invalid"
        kinds = _collection_of_strings(raw_kinds)
        if kinds is None or not kinds.issubset(OPERATION_KINDS):
            return {}, "expected requirement has an invalid operation kind"
        normalized[ref] = kinds
    return normalized, None


def _role_error(
    roles: Mapping[str, frozenset[str]],
    ref: str,
    expected: frozenset[str],
    label: str,
) -> str | None:
    actual = roles.get(ref)
    if actual is None:
        return f"{label} was not issued by the host"
    if actual.isdisjoint(expected):
        return f"{label} has a role incompatible with the operation"
    return None


def _operation_role_error(
    operation: Mapping[str, Any],
    roles: Mapping[str, frozenset[str]],
) -> str | None:
    kind = operation["kind"]
    ordinal = operation["ordinal"]
    prefix = f"operation {ordinal}"
    for field, expected in _OP_REF_FIELDS[kind].items():
        ref = operation.get(field)
        if ref is None:
            continue
        error = _role_error(roles, ref, expected, f"{prefix} {field}")
        if error is not None:
            return error
    for field, expected in _OP_REF_LIST_FIELDS.get(kind, {}).items():
        for ref in operation[field]:
            error = _role_error(roles, ref, expected, f"{prefix} {field}")
            if error is not None:
                return error
    if kind == "block.instantiate":
        parameters: set[str] = set()
        for binding in operation["bindings"]:
            parameter_ref = binding["parameter_ref"]
            if parameter_ref in parameters:
                return f"{prefix} contains duplicate parameter bindings"
            parameters.add(parameter_ref)
            error = _role_error(
                roles,
                parameter_ref,
                frozenset({"parameter_key"}),
                f"{prefix} binding parameter_ref",
            )
            if error is not None:
                return error
            error = _role_error(
                roles,
                binding["value_ref"],
                frozenset({"catalog_value", "input", "scalar"}),
                f"{prefix} binding value_ref",
            )
            if error is not None:
                return error
    if kind == "matrix.expand":
        axis_count = len(operation["axis_refs"])
        seen_rows: set[tuple[str, ...]] = set()
        for row in operation["rows"]:
            if len(row) != axis_count:
                return f"{prefix} matrix row width differs from its axis roster"
            row_key = tuple(row)
            if row_key in seen_rows:
                return f"{prefix} contains duplicate matrix rows"
            seen_rows.add(row_key)
            for ref in row:
                error = _role_error(
                    roles,
                    ref,
                    frozenset({"catalog_value", "input", "scalar"}),
                    f"{prefix} matrix value",
                )
                if error is not None:
                    return error
    return None


def validate_create_delta_plan(
    value: Any,
    *,
    issued_refs: Mapping[str, str | Collection[str]],
    expected_context_revision: str,
    expected_semantic_revision: str,
    expected_surface_revision: str,
    expected_target_ref: str,
    expected_basis_ref: str | None,
    expected_requirement_kinds: Mapping[str, Collection[str] | str],
) -> list[str]:
    """Return deterministic request-bound validation errors; never resolve a ref."""

    forbidden = _forbidden_payload_key(value)
    if forbidden is not None:
        return ["CreateDeltaPlan cannot contain raw DSL, source, path, or template payloads"]
    errors = _schema_errors(value)
    if errors:
        return errors
    if not isinstance(value, Mapping):
        return ["CreateDeltaPlan must be an object"]

    expected_revisions = (
        ("context", expected_context_revision),
        ("semantic", expected_semantic_revision),
        ("surface", expected_surface_revision),
    )
    for label, revision in expected_revisions:
        if HASH_RE.fullmatch(revision) is None:
            return [f"expected {label} revision is invalid"]
        if value[f"{label}_revision"] != revision:
            return [f"{label} revision differs from the admitted authority"]
    if HOST_REF_RE.fullmatch(expected_target_ref) is None:
        return ["expected target reference is invalid"]
    if expected_basis_ref is not None and HOST_REF_RE.fullmatch(expected_basis_ref) is None:
        return ["expected basis reference is invalid"]
    if value["target_ref"] != expected_target_ref:
        return ["target reference differs from the admitted target"]
    if value["basis_ref"] != expected_basis_ref:
        return ["basis reference differs from the admitted proposal"]
    expected_mode = "initial" if expected_basis_ref is None else "refinement"
    if value["mode"] != expected_mode:
        return ["plan mode is incompatible with its admitted basis"]

    requirements, requirement_error = _normalize_requirement_kinds(expected_requirement_kinds)
    if requirement_error is not None:
        return [requirement_error]
    if value["requirements"] != list(requirements):
        return ["requirement roster differs from the admitted instruction"]

    roles, role_roster_error = _normalize_issued_roles(issued_refs)
    if role_roster_error is not None:
        return [role_roster_error]
    error = _role_error(roles, value["target_ref"], frozenset({"target"}), "target_ref")
    if error is not None:
        return [error]
    if value["basis_ref"] is not None:
        error = _role_error(roles, value["basis_ref"], frozenset({"basis"}), "basis_ref")
        if error is not None:
            return [error]
    for ref in value["requirements"]:
        error = _role_error(roles, ref, frozenset({"requirement"}), "requirement_ref")
        if error is not None:
            return [error]

    operations = value["operations"]
    if len(operations) > MAX_OPERATIONS:
        return ["CreateDeltaPlan exceeds its operation bound"]
    if [operation["ordinal"] for operation in operations] != list(range(len(operations))):
        return ["CreateDeltaPlan operations must have contiguous ordinals"]
    create_ordinals = [
        operation["ordinal"] for operation in operations if operation["kind"] == "endpoint.create"
    ]
    if expected_mode == "initial":
        if create_ordinals != [0]:
            return ["initial CreateDeltaPlan must begin with exactly one endpoint.create"]
    elif create_ordinals:
        return ["refinement CreateDeltaPlan cannot recreate its endpoint"]

    coverage: dict[str, set[str]] = {ref: set() for ref in requirements}
    for operation in operations:
        ordinal = operation["ordinal"]
        dependencies = operation["depends_on"]
        if any(dependency >= ordinal for dependency in dependencies):
            return [f"operation {ordinal} has a forward or self dependency"]
        if expected_mode == "initial" and ordinal > 0 and not dependencies:
            return [f"initial operation {ordinal} is disconnected from endpoint.create"]
        for requirement_ref in operation["requirement_refs"]:
            allowed_kinds = requirements.get(requirement_ref)
            if allowed_kinds is None:
                return [f"operation {ordinal} cites an unadmitted requirement"]
            if operation["kind"] not in allowed_kinds:
                return [f"operation {ordinal} cannot cover its cited requirement"]
            coverage[requirement_ref].add(operation["kind"])
        error = _operation_role_error(operation, roles)
        if error is not None:
            return [error]
    if any(not kinds for kinds in coverage.values()):
        return ["CreateDeltaPlan does not cover every admitted requirement"]
    return []


def admit_create_delta_plan(
    value: Any,
    *,
    issued_refs: Mapping[str, str | Collection[str]],
    expected_context_revision: str,
    expected_semantic_revision: str,
    expected_surface_revision: str,
    expected_target_ref: str,
    expected_basis_ref: str | None,
    expected_requirement_kinds: Mapping[str, Collection[str] | str],
) -> dict[str, Any]:
    errors = validate_create_delta_plan(
        value,
        issued_refs=issued_refs,
        expected_context_revision=expected_context_revision,
        expected_semantic_revision=expected_semantic_revision,
        expected_surface_revision=expected_surface_revision,
        expected_target_ref=expected_target_ref,
        expected_basis_ref=expected_basis_ref,
        expected_requirement_kinds=expected_requirement_kinds,
    )
    if errors:
        raise BrainError("CREATE_DELTA_PLAN_INVALID", 502, errors[0])
    return deepcopy(dict(value))


def parse_create_delta_plan_json(
    raw: str,
    *,
    issued_refs: Mapping[str, str | Collection[str]],
    expected_context_revision: str,
    expected_semantic_revision: str,
    expected_surface_revision: str,
    expected_target_ref: str,
    expected_basis_ref: str | None,
    expected_requirement_kinds: Mapping[str, Collection[str] | str],
) -> dict[str, Any]:
    """Parse one bounded strict JSON object, then perform full host admission."""

    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise BrainError("CREATE_DELTA_PLAN_INVALID", 502, "CreateDeltaPlan JSON exceeds its bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise BrainError(
            "CREATE_DELTA_PLAN_INVALID", 502, "CreateDeltaPlan JSON is invalid"
        ) from error
    return admit_create_delta_plan(
        decoded,
        issued_refs=issued_refs,
        expected_context_revision=expected_context_revision,
        expected_semantic_revision=expected_semantic_revision,
        expected_surface_revision=expected_surface_revision,
        expected_target_ref=expected_target_ref,
        expected_basis_ref=expected_basis_ref,
        expected_requirement_kinds=expected_requirement_kinds,
    )


__all__ = [
    "CREATE_DELTA_PLAN_CONTRACT",
    "CREATE_DELTA_PLAN_SCHEMA",
    "CREATE_DELTA_PLAN_SCHEMA_PATH",
    "CREATE_DELTA_PLAN_SCHEMA_SHA256",
    "CreateDeltaPlanError",
    "HOST_REF_RE",
    "HOST_REF_ROLES",
    "MAX_COLLECTION_ITEMS",
    "MAX_DEPENDENCIES",
    "MAX_JSON_BYTES",
    "MAX_MATRIX_AXES",
    "MAX_OPERATIONS",
    "MAX_REQUIREMENTS",
    "OPERATION_KINDS",
    "admit_create_delta_plan",
    "parse_create_delta_plan_json",
    "validate_create_delta_plan",
    "validate_create_delta_plan_shape",
]
