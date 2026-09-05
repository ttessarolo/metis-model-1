"""Deterministic private executor for admitted ``CreateDeltaPlan`` values.

This module is the narrow bridge between an untrusted, already admitted model
plan and the private typed CREATE builder.  It never parses Metis source and it
does not infer a location from a label.  Every mutation is anchored by a
source-ordered, host-only placement manifest and every referenced fragment is
resolved from the exact issued authority surface.

Preparation deliberately does *not* return a renderable spec.  The detached
spec is released only after an exact CREATE permit has been issued and burned.
This keeps a future orchestrator from accidentally bypassing the one-shot
authority boundary.
"""

from __future__ import annotations

import copy
import hmac
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from metis_model1.brain_create_authority_issuer import Issued
from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_CONTRACT,
    CREATE_ENDPOINT_SPEC_SCHEMA,
)
from metis_model1.brain_create_permit import (
    AuthorizedCreatePlan,
    CreatePermitConsumer,
    CreatePermitReceipt,
    issue_create_permit,
)
from metis_model1.brain_create_plan import admit_create_delta_plan
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CREATE_EXECUTION_CONTRACT = "metis-brain-create-execution/v1"
CREATE_PLACEMENT_CONTRACT = "metis-brain-create-placement/v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PATH_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_PATH_DEPTH = 16
MAX_PLACEMENTS = 96

# These constructs occur in the frozen ten-journey corpus but cannot be
# selected faithfully by CreateDeltaPlan v1.  A full builder fragment is not a
# substitute: silently hiding the requested decision inside such a fragment
# would turn the host into an oracle/template provider.
PLAN_V1_REQUIRED_EXTENSIONS: Mapping[str, str] = {
    "attribute": "attribute.declare with a typed guard reference",
    "context_fetch": "query.create plus context.fetch attachment",
    "endpoint_params": "endpoint.set_params including snapshot/windowed pagination",
    "fallback_policy": (
        "fallback.set v2 with trigger, threshold, target kind and materialization semantics"
    ),
    "guard": "guard.set with an explicit guarded target",
    "needs_time": "endpoint.set_needs_time",
    "predicate_richness": (
        "query.add_predicate v2 with clause intent, guard, groups, similarity profile and boost"
    ),
    "projection_meta": "response.set v2 with projection, metadata and per-item metadata",
    "repeat_recipe": "repeat.expand v2 with a typed substitution recipe and output identity",
    "matrix_recipe": "matrix.expand v2 with typed axes, substitutions, aliases and titles",
    "variant": "variant.create with typed activation/empty semantics and placement",
    "view_all_target": "query.set_view_all v2 with endpoint-or-argument target",
}

# Operations whose current public fields do not contain enough information to
# construct their builder meaning.  They are rejected even if a compatible
# full fragment happens to be present in the private registry.
UNREPRESENTABLE_OPERATION_KINDS: Mapping[str, str] = {
    "query.set_pagination": PLAN_V1_REQUIRED_EXTENSIONS["endpoint_params"],
    "query.set_pipeline": (
        "query.set_pipeline v2 defining whether steps are transformers, alternatives "
        "or output steps"
    ),
    "query.set_view_all": PLAN_V1_REQUIRED_EXTENSIONS["view_all_target"],
    "fallback.set": PLAN_V1_REQUIRED_EXTENSIONS["fallback_policy"],
    "response.set": PLAN_V1_REQUIRED_EXTENSIONS["projection_meta"],
    "repeat.expand": PLAN_V1_REQUIRED_EXTENSIONS["repeat_recipe"],
    "matrix.expand": PLAN_V1_REQUIRED_EXTENSIONS["matrix_recipe"],
}


class CreateExecutorError(ValueError):
    """One fail-closed planning, expansion or permit error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        gap_report: CreateExecutionGapReport | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.gap_report = gap_report


@dataclass(frozen=True, slots=True)
class CreateExecutionGapReport:
    unsupported_kinds: tuple[str, ...]
    required_extensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateOperationPlacement:
    """One exact host-selected location for one operation ordinal."""

    ordinal: int
    operation_kind: str
    anchor_ref: str
    action: str
    path: tuple[str | int, ...]
    clause_intent: str | None = None


@dataclass(frozen=True, slots=True)
class CreatePlacementManifest:
    surface_revision: str
    placements: Sequence[CreateOperationPlacement]
    required_constructs: Sequence[str] = ()
    contract_id: str = CREATE_PLACEMENT_CONTRACT


@dataclass(frozen=True, slots=True, repr=False)
class PreparedCreateExecution:
    """Private expansion result.  It intentionally exposes hashes, not spec."""

    plan_sha256: str
    grants_sha256: str
    outline_sha256: str
    spec_sha256: str
    operation_sha256: tuple[str, ...]
    target_ref: str
    basis_ref: str | None
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    generation: int
    _spec_bytes: bytes = field(repr=False)
    _permit_state: _PreparedPermitState = field(
        default_factory=lambda: _PreparedPermitState(), repr=False, compare=False
    )


@dataclass(frozen=True, slots=True)
class RenderAuthorizedCreateSpec:
    spec: Mapping[str, Any]
    spec_sha256: str
    receipt: CreatePermitReceipt


class _PreparedPermitState:
    """One local burn flag; a prepared expansion can authorize exactly once."""

    __slots__ = ("lock", "retired")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.retired = False

    def burn(self) -> None:
        with self.lock:
            if self.retired:
                _fail("CREATE_PERMIT_REPLAY", "prepared create authority was already consumed")
            self.retired = True


_ACTION_BY_KIND: Mapping[str, str] = {
    "endpoint.create": "replace_endpoint",
    "endpoint.set_metadata": "mutate_endpoint",
    "input.declare": "append_input",
    "context.bind": "append_context",
    "block.create": "append_block",
    "block.set_parameter": "set_block_parameter",
    "block.instantiate": "append_use",
    "query.set_catalog": "mutate_query",
    "query.add_predicate": "mutate_query",
    "query.set_order": "mutate_query",
    "query.set_take": "mutate_query",
    "query.set_view_all": "mutate_query",
    "fallback.set": "append_fallback",
    "output.set_pipeline": "set_output_pipeline",
}

_ANCHOR_FIELD_BY_KIND: Mapping[str, str] = {
    "endpoint.create": "endpoint_ref",
    "endpoint.set_metadata": "endpoint_ref",
    "input.declare": "input_ref",
    "context.bind": "context_ref",
    "block.create": "block_ref",
    "block.set_parameter": "block_ref",
    "block.instantiate": "instance_ref",
    "query.set_catalog": "query_ref",
    "query.add_predicate": "query_ref",
    "query.set_order": "query_ref",
    "query.set_take": "query_ref",
    "query.set_view_all": "query_ref",
    "fallback.set": "fallback_slot_ref",
    "output.set_pipeline": "output_ref",
}

# Every operation field has a closed role -> builder-fragment matrix.  Value
# authorities use the builder's ``value`` union rather than accepting an
# arbitrary member type; that makes the issued contract exact and uniform.
_FRAGMENT_MATRIX: Mapping[str, Mapping[str, tuple[tuple[str, str], ...]]] = {
    "endpoint.create": {"endpoint_ref": (("endpoint_slot", "endpoint"),)},
    "endpoint.set_metadata": {
        "endpoint_ref": (("endpoint", "qualifiedIdentifier"),),
        "key_ref": (("metadata_key", "identifier"),),
        "value_ref": (("scalar", "value"),),
    },
    "input.declare": {
        "endpoint_ref": (("endpoint", "qualifiedIdentifier"),),
        "input_ref": (("input_slot", "input"),),
        "type_ref": (("input_type", "identifier"),),
        "default_ref": (("scalar", "value"), ("catalog_value", "value")),
    },
    "context.bind": {
        "endpoint_ref": (("endpoint", "qualifiedIdentifier"),),
        "context_ref": (("context_slot", "contextBinding"),),
        "value_ref": (
            ("scalar", "value"),
            ("input", "value"),
            ("catalog_value", "value"),
        ),
    },
    "block.create": {
        "endpoint_ref": (("endpoint", "qualifiedIdentifier"),),
        "block_ref": (("block_slot", "container"),),
    },
    "block.set_parameter": {
        "block_ref": (("block", "identifier"),),
        "parameter_ref": (("parameter_key", "parameter"),),
        "value_ref": (
            ("scalar", "value"),
            ("input", "value"),
            ("catalog_value", "value"),
        ),
    },
    "block.instantiate": {
        "block_ref": (("block", "identifier"),),
        "instance_ref": (("block_instance_slot", "use"),),
        "binding.parameter_ref": (("parameter_key", "parameter"),),
        "binding.value_ref": (
            ("scalar", "value"),
            ("input", "value"),
            ("catalog_value", "value"),
        ),
    },
    "query.set_catalog": {
        "query_ref": (("query", "identifier"),),
        "catalog_ref": (("catalog", "identifier"),),
    },
    "query.add_predicate": {
        "query_ref": (("query", "identifier"),),
        "field_ref": (("field", "identifier"),),
        "operator_ref": (("predicate_operator", "identifier"),),
        "value_refs": (
            ("catalog_value", "value"),
            ("input", "value"),
            ("scalar", "value"),
        ),
    },
    "query.set_order": {
        "query_ref": (("query", "identifier"),),
        "key_ref": (("field", "identifier"),),
    },
    "query.set_take": {"query_ref": (("query", "identifier"),)},
    "query.set_view_all": {"query_ref": (("query", "identifier"),)},
    "fallback.set": {
        "fallback_slot_ref": (("fallback_slot", "fallback"),),
        "primary_ref": (
            ("block", "identifier"),
            ("query", "identifier"),
            ("result", "qualifiedIdentifier"),
        ),
        "secondary_ref": (
            ("block", "identifier"),
            ("query", "identifier"),
            ("result", "qualifiedIdentifier"),
        ),
    },
    "output.set_pipeline": {
        "output_ref": (("output_slot", "identifier"),),
        "pipeline_ref": (("pipeline", "qualifiedIdentifier"),),
        "step_refs": (("pipeline_step", "qualifiedIdentifier"),),
    },
}


def _fail(
    code: str,
    message: str,
    *,
    gap_report: CreateExecutionGapReport | None = None,
) -> NoReturn:
    raise CreateExecutorError(code, message, gap_report=gap_report)


def _strict_copy(value: Any, *, label: str) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (BrainError, TypeError, ValueError, UnicodeError) as error:
        raise CreateExecutorError(
            "CREATE_EXECUTOR_INVALID", f"{label} is not strict JSON"
        ) from error


def _sha(value: Any) -> str:
    return bytes_sha256(canonical_json(value))


def _gap_report(
    plan: Mapping[str, Any], manifest: CreatePlacementManifest
) -> CreateExecutionGapReport:
    unsupported = tuple(
        sorted(
            {
                op["kind"]
                for op in plan["operations"]
                if op["kind"] in UNREPRESENTABLE_OPERATION_KINDS
            }
        )
    )
    constructs: list[str] = []
    for item in manifest.required_constructs:
        if item not in PLAN_V1_REQUIRED_EXTENSIONS:
            _fail("CREATE_PLACEMENT_INVALID", "placement manifest names an unknown construct")
        if item not in constructs:
            constructs.append(item)
    extensions = [UNREPRESENTABLE_OPERATION_KINDS[kind] for kind in unsupported]
    extensions.extend(PLAN_V1_REQUIRED_EXTENSIONS[item] for item in sorted(constructs))
    return CreateExecutionGapReport(unsupported, tuple(dict.fromkeys(extensions)))


def _placement_body(manifest: CreatePlacementManifest) -> dict[str, Any]:
    return {
        "contract_id": manifest.contract_id,
        "surface_revision": manifest.surface_revision,
        "placements": [
            {
                "ordinal": item.ordinal,
                "operation_kind": item.operation_kind,
                "anchor_ref": item.anchor_ref,
                "action": item.action,
                "path": list(item.path),
                "clause_intent": item.clause_intent,
            }
            for item in manifest.placements
        ],
        "required_constructs": list(manifest.required_constructs),
    }


def _validate_manifest(
    plan: Mapping[str, Any], issued: Issued, manifest: CreatePlacementManifest
) -> tuple[CreateOperationPlacement, ...]:
    if not isinstance(manifest, CreatePlacementManifest):
        _fail("CREATE_PLACEMENT_INVALID", "placement manifest is invalid")
    if manifest.contract_id != CREATE_PLACEMENT_CONTRACT:
        _fail("CREATE_PLACEMENT_INVALID", "placement contract differs")
    if not hmac.compare_digest(manifest.surface_revision, issued.surface.surface_revision):
        _fail("CREATE_PLACEMENT_STALE", "placement surface revision differs")
    placements = tuple(manifest.placements)
    operations = plan["operations"]
    if not 1 <= len(placements) <= MAX_PLACEMENTS or len(placements) != len(operations):
        _fail("CREATE_PLACEMENT_INVALID", "placement roster differs from operation roster")
    anchor_paths: dict[str, tuple[str | int, ...]] = {}
    for ordinal, (placement, operation) in enumerate(zip(placements, operations, strict=True)):
        if not isinstance(placement, CreateOperationPlacement):
            _fail("CREATE_PLACEMENT_INVALID", "placement entry is invalid")
        kind = operation["kind"]
        expected_action = _ACTION_BY_KIND.get(kind)
        expected_anchor = _ANCHOR_FIELD_BY_KIND.get(kind)
        if (
            placement.ordinal != ordinal
            or placement.operation_kind != kind
            or expected_action is None
            or placement.action != expected_action
            or expected_anchor is None
            or placement.anchor_ref != operation[expected_anchor]
        ):
            _fail("CREATE_PLACEMENT_INVALID", "placement does not exactly bind its operation")
        if not 1 <= len(placement.path) <= MAX_PATH_DEPTH or placement.path[0] != "endpoint":
            _fail("CREATE_PLACEMENT_INVALID", "placement path is outside the typed endpoint")
        for segment in placement.path:
            if isinstance(segment, bool) or not isinstance(segment, (str, int)):
                _fail("CREATE_PLACEMENT_INVALID", "placement path segment is invalid")
            if isinstance(segment, str) and PATH_KEY_RE.fullmatch(segment) is None:
                _fail("CREATE_PLACEMENT_INVALID", "placement path key is invalid")
            if isinstance(segment, int) and not 0 <= segment <= 20_000:
                _fail("CREATE_PLACEMENT_INVALID", "placement path index is invalid")
        # A structural authority is an occurrence identity, not a label.  Reusing
        # one anchor at two paths would let a later operation redirect a grant
        # from the host-selected occurrence to a different container.  The
        # current v1 contract has no endpoint exception: endpoint operations
        # that share an anchor are all rooted at the endpoint itself.
        previous_path = anchor_paths.setdefault(placement.anchor_ref, placement.path)
        if previous_path != placement.path:
            _fail(
                "CREATE_PLACEMENT_DRIFT",
                "one structural anchor cannot bind inconsistent placement paths",
            )
        if kind == "query.add_predicate":
            if placement.clause_intent not in {"include", "exclude", "promote"}:
                _fail("CREATE_PLACEMENT_INVALID", "predicate placement needs a clause intent")
        elif placement.clause_intent is not None:
            _fail("CREATE_PLACEMENT_INVALID", "placement has an inapplicable clause intent")
    return placements


def _all_operation_refs(operation: Mapping[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    for key, value in operation.items():
        if key in {"requirement_refs", "depends_on"}:
            continue
        if key.endswith("_ref") and isinstance(value, str):
            result.append(value)
        elif key.endswith("_refs") and isinstance(value, Sequence) and not isinstance(value, str):
            result.extend(item for item in value if isinstance(item, str))
        elif key == "bindings":
            for binding in value:
                result.extend((binding["parameter_ref"], binding["value_ref"]))
        elif key == "rows":
            for row in value:
                result.extend(row)
    return tuple(result)


def _enforce_requirement_authority(operation: Mapping[str, Any], issued: Issued) -> None:
    refs = _all_operation_refs(operation)
    for requirement_ref in operation["requirement_refs"]:
        allowed = frozenset(issued.private_registry.authority_refs_for_requirement(requirement_ref))
        for ref in refs:
            if ref not in allowed:
                _fail(
                    "CREATE_REQUIREMENT_AUTHORITY_MISMATCH",
                    "operation reference is not authorized by every cited requirement",
                )


def _resolve(
    issued: Issued,
    ref: str,
    alternatives: tuple[tuple[str, str], ...],
) -> Any:
    roles = issued.surface.issued_roles.get(ref)
    if roles is None:
        _fail("CREATE_AUTHORITY_UNKNOWN", "operation reference was not issued")
    matches = [(role, kind) for role, kind in alternatives if role in roles]
    if len(matches) != 1:
        _fail("CREATE_FRAGMENT_ROLE_MISMATCH", "operation reference role is not exact")
    role, expected_kind = matches[0]
    try:
        payload = issued.surface.resolve(
            ref,
            required_role=role,
            expected_surface_revision=issued.surface.surface_revision,
        )
    except BrainError as error:
        raise CreateExecutorError(error.code, error.message) from error
    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"fragment_kind", "fragment"}
        or payload["fragment_kind"] != expected_kind
    ):
        _fail("CREATE_FRAGMENT_ROLE_MISMATCH", "authority fragment kind differs from its role")
    return _strict_copy(payload["fragment"], label="authority fragment")


def _resolved_fields(operation: Mapping[str, Any], issued: Issued) -> dict[str, Any]:
    matrix = _FRAGMENT_MATRIX[operation["kind"]]
    result: dict[str, Any] = {}
    for field_name, alternatives in matrix.items():
        if field_name.startswith("binding."):
            nested = field_name.split(".", 1)[1]
            result[field_name] = [
                _resolve(issued, binding[nested], alternatives) for binding in operation["bindings"]
            ]
        elif field_name.endswith("_refs"):
            result[field_name] = [
                _resolve(issued, ref, alternatives) for ref in operation[field_name]
            ]
        elif field_name in operation:
            result[field_name] = _resolve(issued, operation[field_name], alternatives)
    return result


def _at(root: Any, path: Sequence[str | int], *, collection: bool = False) -> Any:
    current = root
    for segment in path:
        if isinstance(segment, str):
            if not isinstance(current, Mapping) or segment not in current:
                _fail("CREATE_PLACEMENT_UNKNOWN", "placement path does not exist")
            current = current[segment]
        else:
            if not isinstance(current, list) or segment >= len(current):
                _fail("CREATE_PLACEMENT_UNKNOWN", "placement index does not exist")
            current = current[segment]
    if collection and not isinstance(current, list):
        _fail("CREATE_PLACEMENT_UNKNOWN", "placement is not a collection")
    return current


def _assert_endpoint(endpoint: Mapping[str, Any], name: str) -> None:
    if endpoint.get("name") != name:
        _fail("CREATE_TARGET_DRIFT", "endpoint authority differs from target")


def _query_at(
    spec: Mapping[str, Any],
    placement: CreateOperationPlacement,
    authority: Any,
    anchored: dict[str, tuple[str | int, ...]],
) -> dict[str, Any]:
    query = _at(spec, placement.path)
    if not isinstance(query, dict):
        _fail("CREATE_PLACEMENT_UNKNOWN", "query placement is not mutable")
    if not isinstance(authority, str):
        _fail("CREATE_FRAGMENT_INVALID", "query slot identity is invalid")
    previous_path = anchored.setdefault(placement.anchor_ref, placement.path)
    if previous_path != placement.path:
        _fail("CREATE_PLACEMENT_DRIFT", "query authority placement differs from its anchor")
    return query


def _append_unique(collection: list[Any], value: Any, *, key: str, label: str) -> None:
    if not isinstance(value, Mapping) or key not in value:
        _fail("CREATE_FRAGMENT_INVALID", f"{label} fragment is invalid")
    if any(isinstance(item, Mapping) and item.get(key) == value[key] for item in collection):
        _fail("CREATE_FRAGMENT_CONFLICT", f"{label} identity is duplicated")
    collection.append(value)


def _endpoint_skeleton(value: Mapping[str, Any]) -> bool:
    """Reject a hidden initial blueprint masquerading as an endpoint slot."""

    return (
        value.get("params") == {"timeout": None, "expires": None, "paginate": None}
        and value.get("inputs") == []
        and value.get("needs_time") is False
        and value.get("attributes") == []
        and value.get("input_pipeline") == []
        and value.get("output_pipeline") == []
        and value.get("inheritance") == {"without_input": [], "without_output": []}
        and value.get("context") == []
        and value.get("blocks") == []
        and value.get("variants") == []
        and value.get("output") is None
    )


def _block_skeleton(value: Mapping[str, Any]) -> bool:
    """A block.create grant may identify a block, never hide its contents."""

    return (
        value.get("parameters") == []
        and value.get("title") is None
        and value.get("activation") is None
        and value.get("presentation")
        == {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}
        and value.get("fetches") == []
        and value.get("blocks") == []
        and value.get("uses") == []
        and value.get("output") is None
    )


def _predicate(operation: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    operator = fields["operator_ref"]
    field_name = fields["field_ref"]
    values = fields["value_refs"]
    if operator not in {"eq", "in", "gt", "gte", "lte"} or len(values) != 1:
        _fail(
            "CREATE_OPERATION_UNREPRESENTABLE",
            PLAN_V1_REQUIRED_EXTENSIONS["predicate_richness"],
            gap_report=CreateExecutionGapReport(
                (), (PLAN_V1_REQUIRED_EXTENSIONS["predicate_richness"],)
            ),
        )
    return {"op": operator, "field": field_name, "value": values[0]}


def _apply_operation(
    spec: dict[str, Any],
    operation: Mapping[str, Any],
    fields: Mapping[str, Any],
    placement: CreateOperationPlacement,
    *,
    target_name: str,
    anchored_queries: dict[str, tuple[str | int, ...]],
) -> None:
    kind = operation["kind"]
    if kind == "endpoint.create":
        if placement.path != ("endpoint",):
            _fail("CREATE_PLACEMENT_INVALID", "endpoint creation must replace the endpoint root")
        endpoint = fields["endpoint_ref"]
        if not isinstance(endpoint, dict):
            _fail("CREATE_FRAGMENT_INVALID", "endpoint fragment is invalid")
        _assert_endpoint(endpoint, target_name)
        if not _endpoint_skeleton(endpoint):
            _fail(
                "CREATE_HIDDEN_BLUEPRINT",
                "endpoint.create authority contains unselected structure",
            )
        spec["endpoint"] = endpoint
        return
    endpoint = _at(spec, ("endpoint",))
    if not isinstance(endpoint, dict):
        _fail("CREATE_FRAGMENT_INVALID", "endpoint is not mutable")

    if "endpoint_ref" in fields:
        _assert_endpoint(endpoint, fields["endpoint_ref"])
    if kind == "endpoint.set_metadata":
        if placement.path != ("endpoint",):
            _fail("CREATE_PLACEMENT_INVALID", "endpoint metadata must target the endpoint root")
        key = fields["key_ref"]
        value = fields["value_ref"]
        if key == "reference" and value.get("kind") == "lit" and value.get("lexical") == "text":
            endpoint["reference"] = value["value"]
        elif key == "needs_time" and value.get("kind") == "bool":
            endpoint["needs_time"] = value["value"]
        else:
            _fail("CREATE_OPERATION_UNREPRESENTABLE", "endpoint metadata key/value is not closed")
    elif kind == "input.declare":
        item = fields["input_ref"]
        if item["type"] != fields["type_ref"]:
            _fail("CREATE_FRAGMENT_DRIFT", "input type differs from its authority")
        default = fields.get("default_ref")
        if item["default"] != default:
            _fail("CREATE_FRAGMENT_DRIFT", "input default differs from its authority")
        _append_unique(_at(spec, placement.path, collection=True), item, key="name", label="input")
    elif kind == "context.bind":
        item = fields["context_ref"]
        if item.get("kind") != "transform" or item.get("value") != fields["value_ref"]:
            _fail(
                "CREATE_OPERATION_UNREPRESENTABLE",
                PLAN_V1_REQUIRED_EXTENSIONS["context_fetch"],
                gap_report=CreateExecutionGapReport(
                    (), (PLAN_V1_REQUIRED_EXTENSIONS["context_fetch"],)
                ),
            )
        _append_unique(
            _at(spec, placement.path, collection=True), item, key="name", label="context"
        )
    elif kind == "block.create":
        if not _block_skeleton(fields["block_ref"]):
            _fail(
                "CREATE_HIDDEN_BLUEPRINT",
                "block.create authority contains unselected structure",
            )
        _append_unique(
            _at(spec, placement.path, collection=True),
            fields["block_ref"],
            key="name",
            label="block",
        )
    elif kind == "block.set_parameter":
        block = _at(spec, placement.path)
        if not isinstance(block, dict) or block.get("name") != fields["block_ref"]:
            _fail("CREATE_PLACEMENT_DRIFT", "block placement differs from its authority")
        parameter = fields["parameter_ref"]
        parameter["default"] = fields["value_ref"]
        parameters = block.get("parameters")
        if not isinstance(parameters, list):
            _fail("CREATE_PLACEMENT_UNKNOWN", "block parameter collection is absent")
        existing = [
            index for index, item in enumerate(parameters) if item.get("name") == parameter["name"]
        ]
        if len(existing) > 1:
            _fail("CREATE_FRAGMENT_CONFLICT", "block parameter identity is duplicated")
        if existing:
            parameters[existing[0]] = parameter
        else:
            parameters.append(parameter)
    elif kind == "block.instantiate":
        block = fields["block_ref"]
        instance = fields["instance_ref"]
        args = [
            {"name": parameter["name"], "value": value}
            for parameter, value in zip(
                fields["binding.parameter_ref"], fields["binding.value_ref"], strict=True
            )
        ]
        if instance.get("kind") != "instance" or instance.get("block") != block:
            _fail("CREATE_FRAGMENT_DRIFT", "block instance differs from its declaration")
        if instance.get("args", []) != args:
            _fail("CREATE_FRAGMENT_DRIFT", "block instance arguments differ from bindings")
        collection = _at(spec, placement.path, collection=True)
        identity = "alias" if "alias" in instance else "block"
        _append_unique(collection, instance, key=identity, label="block instance")
    elif kind.startswith("query."):
        query = _query_at(spec, placement, fields["query_ref"], anchored_queries)
        if kind == "query.set_catalog":
            query["from"] = {"kind": "catalog", "catalog": fields["catalog_ref"]}
        elif kind == "query.add_predicate":
            query.setdefault("clauses", []).append(
                {"intent": placement.clause_intent, "where": [_predicate(operation, fields)]}
            )
        elif kind == "query.set_order":
            query.setdefault("order", []).append(
                {
                    "by": "field",
                    "direction": operation["direction"],
                    "field": fields["key_ref"],
                }
            )
        elif kind == "query.set_take":
            # ``query.set_take`` is the v1 total-cardinality operation.  A
            # page decision belongs to pagination and must never be silently
            # rendered as a total (or as a per-scope count) here.
            query["cardinality"] = {"mode": "total", "value": operation["count"]}
        elif kind == "query.set_view_all":
            if operation["enabled"] is False:
                query["presentation"]["view_all"] = None
            elif query["presentation"].get("view_all") is None:
                _fail(
                    "CREATE_OPERATION_UNREPRESENTABLE",
                    PLAN_V1_REQUIRED_EXTENSIONS["view_all_target"],
                    gap_report=CreateExecutionGapReport(
                        (), (PLAN_V1_REQUIRED_EXTENSIONS["view_all_target"],)
                    ),
                )
        else:  # protected by the unsupported-kind preflight
            _fail("CREATE_OPERATION_UNREPRESENTABLE", "query operation is unsupported")
    elif kind == "fallback.set":
        fallback = fields["fallback_slot_ref"]
        secondary = fields["secondary_ref"]
        secondary_name = secondary if isinstance(secondary, str) else secondary.get("name")
        if fallback.get("target") != secondary_name or fallback.get("mode") != operation["mode"]:
            _fail("CREATE_FRAGMENT_DRIFT", "fallback target or mode differs from authority")
        _at(spec, placement.path, collection=True).append(fallback)
    elif kind == "output.set_pipeline":
        pipeline = [fields["pipeline_ref"], *fields["step_refs"]]
        target = _at(spec, placement.path)
        if not isinstance(target, list):
            _fail("CREATE_PLACEMENT_UNKNOWN", "output pipeline placement is not a list")
        target[:] = pipeline
    else:
        _fail("CREATE_OPERATION_UNREPRESENTABLE", "operation is unsupported")


def prepare_create_delta_plan(
    admitted_plan: Mapping[str, Any],
    *,
    issued: Issued,
    placement_manifest: CreatePlacementManifest,
    parent_spec: Mapping[str, Any] | None = None,
    expected_parent_spec_sha256: str | None = None,
) -> PreparedCreateExecution:
    """Resolve and expand an admitted plan without releasing its typed spec."""

    if not isinstance(issued, Issued):
        _fail("CREATE_AUTHORITY_INVALID", "issued authority is invalid")
    try:
        plan = admit_create_delta_plan(
            admitted_plan,
            issued_refs=issued.surface.issued_roles,
            expected_context_revision=issued.context_revision,
            expected_semantic_revision=issued.semantic_revision,
            expected_surface_revision=issued.surface.surface_revision,
            expected_target_ref=issued.surface.target_ref,
            expected_basis_ref=issued.surface.basis_ref,
            expected_requirement_kinds=issued.surface.expected_requirement_kinds,
        )
    except (AttributeError, BrainError) as error:
        raise CreateExecutorError(
            "CREATE_DELTA_PLAN_INVALID", "create plan no longer matches admitted authority"
        ) from error
    report = _gap_report(plan, placement_manifest)
    if report.unsupported_kinds or report.required_extensions:
        _fail(
            "CREATE_PLAN_V1_INSUFFICIENT",
            "CreateDeltaPlan v1 cannot represent the requested construct set",
            gap_report=report,
        )
    placements = _validate_manifest(plan, issued, placement_manifest)

    if plan["mode"] == "initial":
        if parent_spec is not None or expected_parent_spec_sha256 is not None:
            _fail("CREATE_PARENT_INVALID", "initial creation cannot carry a parent spec")
        spec: dict[str, Any] = {
            "schema_version": 1,
            "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        }
    else:
        if parent_spec is None or not isinstance(expected_parent_spec_sha256, str):
            _fail("CREATE_PARENT_INVALID", "refinement requires an exact parent spec")
        if HASH_RE.fullmatch(expected_parent_spec_sha256) is None:
            _fail("CREATE_PARENT_INVALID", "parent spec hash is invalid")
        parent = _strict_copy(parent_spec, label="parent spec")
        if not hmac.compare_digest(_sha(parent), expected_parent_spec_sha256):
            _fail("CREATE_PARENT_DRIFT", "parent spec hash differs")
        spec = parent

    target_payload = issued.surface.resolve(
        issued.surface.target_ref,
        required_role="target",
        expected_surface_revision=issued.surface.surface_revision,
    )
    if (
        not isinstance(target_payload, Mapping)
        or target_payload.get("fragment_kind") not in {"identifier", "qualifiedIdentifier"}
        or not isinstance(target_payload.get("fragment"), str)
    ):
        _fail("CREATE_TARGET_INVALID", "target authority is not an endpoint identifier")
    target_name = target_payload["fragment"]
    if plan["mode"] == "refinement":
        endpoint = spec.get("endpoint")
        if not isinstance(endpoint, Mapping):
            _fail("CREATE_PARENT_INVALID", "parent spec has no endpoint")
        _assert_endpoint(endpoint, target_name)

    anchored_queries: dict[str, tuple[str | int, ...]] = {}
    completed: set[int] = set()
    for operation, placement in zip(plan["operations"], placements, strict=True):
        if not set(operation["depends_on"]).issubset(completed):
            _fail("CREATE_DEPENDENCY_INVALID", "operation dependency was not completed")
        _enforce_requirement_authority(operation, issued)
        fields = _resolved_fields(operation, issued)
        _apply_operation(
            spec,
            operation,
            fields,
            placement,
            target_name=target_name,
            anchored_queries=anchored_queries,
        )
        completed.add(operation["ordinal"])

    errors = sorted(
        Draft202012Validator(CREATE_ENDPOINT_SPEC_SCHEMA).iter_errors(spec),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    if errors:
        _fail("CREATE_SPEC_INVALID", "expanded spec violates the typed builder contract")
    spec_bytes = canonical_json(spec)
    return PreparedCreateExecution(
        plan_sha256=_sha(plan),
        grants_sha256=issued.surface.surface_revision,
        outline_sha256=_sha(_placement_body(placement_manifest)),
        spec_sha256=bytes_sha256(spec_bytes),
        operation_sha256=tuple(_sha(operation) for operation in plan["operations"]),
        target_ref=issued.surface.target_ref,
        basis_ref=issued.surface.basis_ref,
        # These are copied from the host-issued authority after the untrusted
        # plan has been compared with it.  Do not carry plan-owned revisions
        # across the later permit boundary.
        context_revision=issued.context_revision,
        semantic_revision=issued.semantic_revision,
        toolchain_binding=issued.toolchain_binding,
        generation=issued.generation,
        _spec_bytes=spec_bytes,
    )


def authorize_prepared_create(
    prepared: PreparedCreateExecution,
    *,
    permit_document: Mapping[str, Any],
    issued_permit_ref_roles: Mapping[str, Any],
    consumption_document: Mapping[str, Any],
    current_binding: Mapping[str, Any],
    now_ms: int,
) -> RenderAuthorizedCreateSpec:
    """Issue and burn one exact permit, then release a detached builder spec."""

    if not isinstance(prepared, PreparedCreateExecution):
        _fail("CREATE_EXECUTION_INVALID", "prepared execution is invalid")
    prepared._permit_state.burn()
    try:
        spec = json.loads(prepared._spec_bytes)
    except (TypeError, ValueError, UnicodeError) as error:
        raise CreateExecutorError(
            "CREATE_EXECUTION_TAMPERED", "prepared spec is invalid"
        ) from error
    if not hmac.compare_digest(bytes_sha256(canonical_json(spec)), prepared.spec_sha256):
        _fail("CREATE_EXECUTION_TAMPERED", "prepared spec integrity differs")
    if not isinstance(permit_document, Mapping) or not isinstance(current_binding, Mapping):
        _fail("CREATE_PERMIT_DRIFT", "permit binding is invalid")
    binding = permit_document.get("binding")
    seals = permit_document.get("operation_seals")
    if not isinstance(binding, Mapping) or not isinstance(seals, Sequence):
        _fail("CREATE_PERMIT_DRIFT", "permit document is incomplete")
    required = {
        "context_revision": prepared.context_revision,
        "semantic_source_revision": prepared.semantic_revision,
        "toolchain_binding": prepared.toolchain_binding,
        "conversation_generation": prepared.generation,
        "target_ref": prepared.target_ref,
        "outline_sha256": prepared.outline_sha256,
        "plan_sha256": prepared.plan_sha256,
        "grants_sha256": prepared.grants_sha256,
    }
    if any(binding.get(key) != value for key, value in required.items()):
        _fail("CREATE_PERMIT_DRIFT", "permit does not bind the prepared execution")
    if dict(binding) != dict(current_binding):
        _fail("CREATE_PERMIT_DRIFT", "live binding differs before permit issue")
    if len(seals) != len(prepared.operation_sha256) or any(
        not isinstance(seal, Mapping)
        or seal.get("ordinal") != ordinal
        or seal.get("operation_sha256") != digest
        for ordinal, (seal, digest) in enumerate(zip(seals, prepared.operation_sha256, strict=True))
    ):
        _fail("CREATE_PERMIT_DRIFT", "permit operation seals differ from the admitted plan")
    try:
        permit = issue_create_permit(
            permit_document,
            issued_ref_roles=issued_permit_ref_roles,
        )
        authorized: AuthorizedCreatePlan = CreatePermitConsumer(
            permit,
            issued_ref_roles=issued_permit_ref_roles,
        ).consume(
            consumption_document,
            current_binding=current_binding,
            now_ms=now_ms,
        )
    except Exception as error:
        if isinstance(error, CreateExecutorError):
            raise
        code = getattr(error, "code", "CREATE_PERMIT_INVALID")
        raise CreateExecutorError(code, str(error)) from error
    if (
        tuple(item.operation_sha256 for item in authorized.operation_seals)
        != prepared.operation_sha256
    ):
        _fail("CREATE_PERMIT_DRIFT", "consumed operation authority differs")
    return RenderAuthorizedCreateSpec(
        spec=copy.deepcopy(spec),
        spec_sha256=prepared.spec_sha256,
        receipt=authorized.receipt,
    )


__all__ = [
    "CREATE_EXECUTION_CONTRACT",
    "CREATE_PLACEMENT_CONTRACT",
    "PLAN_V1_REQUIRED_EXTENSIONS",
    "UNREPRESENTABLE_OPERATION_KINDS",
    "CreateExecutionGapReport",
    "CreateExecutorError",
    "CreateOperationPlacement",
    "CreatePlacementManifest",
    "PreparedCreateExecution",
    "RenderAuthorizedCreateSpec",
    "authorize_prepared_create",
    "prepare_create_delta_plan",
]
