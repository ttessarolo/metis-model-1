from __future__ import annotations

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_plan import (
    CREATE_DELTA_PLAN_CONTRACT,
    CREATE_DELTA_PLAN_SCHEMA,
    HOST_REF_ROLES,
    MAX_COLLECTION_ITEMS,
    MAX_DEPENDENCIES,
    MAX_JSON_BYTES,
    MAX_MATRIX_AXES,
    MAX_OPERATIONS,
    MAX_REQUIREMENTS,
    OPERATION_KINDS,
    admit_create_delta_plan,
    parse_create_delta_plan_json,
    validate_create_delta_plan,
)
from metis_model1.brain_protocol import BrainError

CONTEXT = "sha256:" + "a" * 64
SEMANTIC = "sha256:" + "b" * 64
SURFACE = "sha256:" + "c" * 64
TARGET = "hostref:target"
BASIS = "hostref:basis"
REQUIREMENT = "hostref:requirement-1"

ISSUED: dict[str, str | set[str]] = {
    TARGET: "target",
    BASIS: "basis",
    REQUIREMENT: "requirement",
    "hostref:endpoint": {"endpoint_slot", "endpoint"},
    "hostref:metadata-key": "metadata_key",
    "hostref:scalar": "scalar",
    "hostref:scalar-2": "scalar",
    "hostref:catalog-value": "catalog_value",
    "hostref:input": {"input_slot", "input"},
    "hostref:input-type": "input_type",
    "hostref:context": "context_slot",
    "hostref:block": {"block_slot", "block"},
    "hostref:block-instance": "block_instance_slot",
    "hostref:parameter": "parameter_key",
    "hostref:query": "query",
    "hostref:catalog": "catalog",
    "hostref:field": "field",
    "hostref:operator": "predicate_operator",
    "hostref:pipeline": "pipeline",
    "hostref:pipeline-step": "pipeline_step",
    "hostref:fallback": "fallback_slot",
    "hostref:result": "result",
    "hostref:response": "response_slot",
    "hostref:response-format": "response_format",
    "hostref:output": "output_slot",
    "hostref:expansion": "expansion_slot",
    "hostref:pattern": "expansion_pattern",
    "hostref:axis": "matrix_axis",
}


def _operation(kind: str) -> dict[str, object]:
    common: dict[str, object] = {
        "ordinal": 0,
        "kind": kind,
        "depends_on": [],
        "requirement_refs": [REQUIREMENT],
    }
    specific: dict[str, dict[str, object]] = {
        "endpoint.create": {"endpoint_ref": "hostref:endpoint"},
        "endpoint.set_metadata": {
            "endpoint_ref": "hostref:endpoint",
            "key_ref": "hostref:metadata-key",
            "value_ref": "hostref:scalar",
        },
        "input.declare": {
            "endpoint_ref": "hostref:endpoint",
            "input_ref": "hostref:input",
            "type_ref": "hostref:input-type",
            "default_ref": "hostref:scalar",
        },
        "context.bind": {
            "endpoint_ref": "hostref:endpoint",
            "context_ref": "hostref:context",
            "value_ref": "hostref:input",
        },
        "block.create": {
            "endpoint_ref": "hostref:endpoint",
            "block_ref": "hostref:block",
        },
        "block.set_parameter": {
            "block_ref": "hostref:block",
            "parameter_ref": "hostref:parameter",
            "value_ref": "hostref:catalog-value",
        },
        "block.instantiate": {
            "block_ref": "hostref:block",
            "instance_ref": "hostref:block-instance",
            "bindings": [
                {
                    "parameter_ref": "hostref:parameter",
                    "value_ref": "hostref:scalar",
                }
            ],
        },
        "query.set_catalog": {
            "query_ref": "hostref:query",
            "catalog_ref": "hostref:catalog",
        },
        "query.add_predicate": {
            "query_ref": "hostref:query",
            "field_ref": "hostref:field",
            "operator_ref": "hostref:operator",
            "value_refs": ["hostref:catalog-value"],
        },
        "query.set_order": {
            "query_ref": "hostref:query",
            "key_ref": "hostref:field",
            "direction": "descending",
        },
        "query.set_take": {"query_ref": "hostref:query", "count": 24},
        "query.set_pagination": {
            "query_ref": "hostref:query",
            "page_input_ref": "hostref:input",
            "default_size": 20,
        },
        "query.set_view_all": {"query_ref": "hostref:query", "enabled": True},
        "query.set_pipeline": {
            "query_ref": "hostref:query",
            "pipeline_ref": "hostref:pipeline",
            "step_refs": ["hostref:pipeline-step"],
        },
        "fallback.set": {
            "fallback_slot_ref": "hostref:fallback",
            "primary_ref": "hostref:query",
            "secondary_ref": "hostref:result",
            "mode": "append",
        },
        "response.set": {
            "response_ref": "hostref:response",
            "format_ref": "hostref:response-format",
            "source_ref": "hostref:result",
        },
        "output.set_pipeline": {
            "output_ref": "hostref:output",
            "pipeline_ref": "hostref:pipeline",
            "step_refs": ["hostref:pipeline-step"],
        },
        "repeat.expand": {
            "target_ref": "hostref:expansion",
            "pattern_ref": "hostref:pattern",
            "item_refs": ["hostref:scalar", "hostref:scalar-2"],
        },
        "matrix.expand": {
            "target_ref": "hostref:expansion",
            "pattern_ref": "hostref:pattern",
            "axis_refs": ["hostref:axis"],
            "rows": [["hostref:scalar"], ["hostref:scalar-2"]],
        },
    }
    return common | specific[kind]


def _plan(kind: str = "endpoint.create") -> dict[str, object]:
    initial = kind == "endpoint.create"
    return {
        "schema_version": 1,
        "contract_id": CREATE_DELTA_PLAN_CONTRACT,
        "mode": "initial" if initial else "refinement",
        "context_revision": CONTEXT,
        "semantic_revision": SEMANTIC,
        "surface_revision": SURFACE,
        "target_ref": TARGET,
        "basis_ref": None if initial else BASIS,
        "requirements": [REQUIREMENT],
        "operations": [_operation(kind)],
    }


def _validate(
    value: object,
    *,
    kind: str = "endpoint.create",
    issued: dict[str, str | set[str]] = ISSUED,
    basis: str | None = None,
    requirement_kinds: dict[str, set[str]] | None = None,
) -> list[str]:
    return validate_create_delta_plan(
        value,
        issued_refs=issued,
        expected_context_revision=CONTEXT,
        expected_semantic_revision=SEMANTIC,
        expected_surface_revision=SURFACE,
        expected_target_ref=TARGET,
        expected_basis_ref=basis,
        expected_requirement_kinds=requirement_kinds
        if requirement_kinds is not None
        else {REQUIREMENT: {kind}},
    )


def test_schema_vocabulary_and_census_bounds_are_pinned() -> None:
    assert Draft202012Validator.check_schema(CREATE_DELTA_PLAN_SCHEMA) is None
    assert len(OPERATION_KINDS) == 19
    assert MAX_OPERATIONS == 96
    assert MAX_REQUIREMENTS == 64
    assert MAX_DEPENDENCIES == 16
    assert MAX_COLLECTION_ITEMS == 32
    assert MAX_MATRIX_AXES == 8
    assert MAX_JSON_BYTES == 65_536
    assert "requirement" in HOST_REF_ROLES
    assert _validate(_plan()) == []


@pytest.mark.parametrize("kind", sorted(OPERATION_KINDS - {"endpoint.create"}))
def test_every_refinement_operation_has_one_closed_valid_shape(kind: str) -> None:
    assert _validate(_plan(kind), kind=kind, basis=BASIS) == []


@pytest.mark.parametrize(
    "forbidden_key",
    ["source", "source_path", "path", "template", "metis_source", "dsl", "snippet"],
)
def test_raw_dsl_source_path_and_template_payloads_are_explicitly_forbidden(
    forbidden_key: str,
) -> None:
    value = _plan()
    value["operations"][0][forbidden_key] = "endpoint leaked { take 20 }"
    assert _validate(value) == [
        "CreateDeltaPlan cannot contain raw DSL, source, path, or template payloads"
    ]


def test_closed_schema_rejects_unknown_fields_and_wrong_discriminator_shape() -> None:
    value = _plan("query.set_take")
    value["operations"][0]["free_text"] = "ignored"
    assert _validate(value, kind="query.set_take", basis=BASIS)

    value = _plan("query.set_take")
    value["operations"][0]["kind"] = "query.set_catalog"
    assert _validate(value, kind="query.set_take", basis=BASIS)


def test_host_refs_must_be_issued_and_have_the_exact_admitted_role() -> None:
    unknown = _plan("query.add_predicate")
    unknown["operations"][0]["field_ref"] = "hostref:model-invented"
    assert "not issued" in _validate(unknown, kind="query.add_predicate", basis=BASIS)[0]

    role_swapped = _plan("query.add_predicate")
    role_swapped["operations"][0]["field_ref"] = "hostref:catalog"
    assert (
        "role incompatible" in _validate(role_swapped, kind="query.add_predicate", basis=BASIS)[0]
    )

    invalid_roster = dict(ISSUED)
    invalid_roster["hostref:field"] = "file_path"
    assert (
        "invalid role"
        in _validate(
            _plan("query.add_predicate"),
            kind="query.add_predicate",
            basis=BASIS,
            issued=invalid_roster,
        )[0]
    )


def test_initial_and_refinement_modes_bind_the_basis_and_endpoint_root() -> None:
    value = _plan()
    value["mode"] = "refinement"
    assert "mode" in _validate(value)[0]

    value = _plan()
    value["operations"] = [_operation("query.set_take")]
    assert (
        "endpoint.create"
        in _validate(
            value,
            kind="query.set_take",
            requirement_kinds={REQUIREMENT: {"query.set_take"}},
        )[0]
    )

    value = _plan("query.set_take")
    value["operations"] = [_operation("endpoint.create")]
    assert (
        "recreate"
        in _validate(
            value,
            basis=BASIS,
            requirement_kinds={REQUIREMENT: {"endpoint.create"}},
        )[0]
    )


def test_ordinals_form_a_backward_only_dag_connected_to_initial_create() -> None:
    valid = _plan()
    second = _operation("query.set_take")
    second["ordinal"] = 1
    second["depends_on"] = [0]
    valid["operations"].append(second)
    assert (
        _validate(
            valid,
            requirement_kinds={REQUIREMENT: {"endpoint.create", "query.set_take"}},
        )
        == []
    )

    gap = deepcopy(valid)
    gap["operations"][1]["ordinal"] = 2
    assert (
        "contiguous"
        in _validate(
            gap,
            requirement_kinds={REQUIREMENT: {"endpoint.create", "query.set_take"}},
        )[0]
    )

    forward = deepcopy(valid)
    forward["operations"][1]["depends_on"] = [1]
    assert (
        "forward or self"
        in _validate(
            forward,
            requirement_kinds={REQUIREMENT: {"endpoint.create", "query.set_take"}},
        )[0]
    )

    disconnected = deepcopy(valid)
    disconnected["operations"][1]["depends_on"] = []
    assert (
        "disconnected"
        in _validate(
            disconnected,
            requirement_kinds={REQUIREMENT: {"endpoint.create", "query.set_take"}},
        )[0]
    )


def test_coverage_is_exact_and_kind_authorized() -> None:
    missing = _plan()
    missing["requirements"].append("hostref:requirement-2")
    issued = dict(ISSUED) | {"hostref:requirement-2": "requirement"}
    expected = {
        REQUIREMENT: {"endpoint.create"},
        "hostref:requirement-2": {"query.set_take"},
    }
    assert "does not cover" in _validate(missing, issued=issued, requirement_kinds=expected)[0]

    wrong_kind = _plan()
    assert (
        "cannot cover"
        in _validate(wrong_kind, requirement_kinds={REQUIREMENT: {"query.set_take"}})[0]
    )

    reordered = deepcopy(missing)
    reordered["requirements"].reverse()
    assert "roster differs" in _validate(reordered, issued=issued, requirement_kinds=expected)[0]


def test_matrix_rows_and_parameter_bindings_are_structurally_unique() -> None:
    matrix = _plan("matrix.expand")
    matrix["operations"][0]["rows"][1] = ["hostref:scalar"]
    assert "duplicate matrix" in _validate(matrix, kind="matrix.expand", basis=BASIS)[0]

    wrong_width = _plan("matrix.expand")
    wrong_width["operations"][0]["axis_refs"].append("hostref:axis-2")
    issued = dict(ISSUED) | {"hostref:axis-2": "matrix_axis"}
    assert (
        "row width"
        in _validate(
            wrong_width,
            kind="matrix.expand",
            basis=BASIS,
            issued=issued,
        )[0]
    )

    bindings = _plan("block.instantiate")
    bindings["operations"][0]["bindings"].append(
        {"parameter_ref": "hostref:parameter", "value_ref": "hostref:scalar-2"}
    )
    assert "duplicate parameter" in _validate(bindings, kind="block.instantiate", basis=BASIS)[0]


def test_collection_and_operation_bounds_fail_closed() -> None:
    repeat = _plan("repeat.expand")
    issued = dict(ISSUED)
    repeat["operations"][0]["item_refs"] = []
    for index in range(MAX_COLLECTION_ITEMS):
        ref = f"hostref:item-{index}"
        issued[ref] = "scalar"
        repeat["operations"][0]["item_refs"].append(ref)
    assert (
        _validate(
            repeat,
            kind="repeat.expand",
            basis=BASIS,
            issued=issued,
        )
        == []
    )
    extra_ref = f"hostref:item-{MAX_COLLECTION_ITEMS}"
    issued[extra_ref] = "scalar"
    repeat["operations"][0]["item_refs"].append(extra_ref)
    assert _validate(
        repeat,
        kind="repeat.expand",
        basis=BASIS,
        issued=issued,
    )

    oversized = _plan("query.set_take")
    oversized["operations"] = []
    for ordinal in range(MAX_OPERATIONS):
        operation = _operation("query.set_take")
        operation["ordinal"] = ordinal
        oversized["operations"].append(operation)
    assert _validate(oversized, kind="query.set_take", basis=BASIS) == []
    extra_operation = _operation("query.set_take")
    extra_operation["ordinal"] = MAX_OPERATIONS
    oversized["operations"].append(extra_operation)
    assert _validate(oversized, kind="query.set_take", basis=BASIS)


def test_request_bound_revisions_target_and_basis_are_independent() -> None:
    mutations = [
        ("context_revision", "context"),
        ("semantic_revision", "semantic"),
        ("surface_revision", "surface"),
        ("target_ref", "target"),
        ("basis_ref", "basis"),
    ]
    for field, expected_word in mutations:
        value = _plan("query.set_take")
        value[field] = "sha256:" + "d" * 64 if field.endswith("revision") else "hostref:other"
        assert expected_word in _validate(value, kind="query.set_take", basis=BASIS)[0]


def test_strict_json_rejects_duplicates_constants_trailing_data_and_size() -> None:
    kwargs = {
        "issued_refs": ISSUED,
        "expected_context_revision": CONTEXT,
        "expected_semantic_revision": SEMANTIC,
        "expected_surface_revision": SURFACE,
        "expected_target_ref": TARGET,
        "expected_basis_ref": None,
        "expected_requirement_kinds": {REQUIREMENT: {"endpoint.create"}},
    }
    assert parse_create_delta_plan_json(json.dumps(_plan()), **kwargs)["mode"] == "initial"

    invalid_payloads = [
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":NaN}',
        json.dumps(_plan()) + " false",
        " " * (MAX_JSON_BYTES + 1),
    ]
    for raw in invalid_payloads:
        with pytest.raises(BrainError) as raised:
            parse_create_delta_plan_json(raw, **kwargs)
        assert raised.value.code == "CREATE_DELTA_PLAN_INVALID"
        assert raised.value.status == 502


def test_admission_returns_a_detached_plan() -> None:
    value = _plan()
    admitted = admit_create_delta_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=CONTEXT,
        expected_semantic_revision=SEMANTIC,
        expected_surface_revision=SURFACE,
        expected_target_ref=TARGET,
        expected_basis_ref=None,
        expected_requirement_kinds={REQUIREMENT: {"endpoint.create"}},
    )
    value["operations"][0]["endpoint_ref"] = "hostref:model-invented"
    assert admitted["operations"][0]["endpoint_ref"] == "hostref:endpoint"
