from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_authority_issuer import Issued, PrivateAuthorityRegistry
from metis_model1.brain_create_builder import CREATE_ENDPOINT_SPEC_CONTRACT
from metis_model1.brain_create_executor import (
    CREATE_PLACEMENT_CONTRACT,
    PLAN_V1_REQUIRED_EXTENSIONS,
    CreateExecutorError,
    CreateOperationPlacement,
    CreatePlacementManifest,
    authorize_prepared_create,
    prepare_create_delta_plan,
)
from metis_model1.brain_create_permit import (
    CREATE_CONSUMPTION_CONTRACT,
    CREATE_PERMIT_CONTRACT,
)
from metis_model1.brain_create_plan import CREATE_DELTA_PLAN_CONTRACT
from metis_model1.brain_create_surface import (
    CreateAuthorityGrant,
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurface,
    RequirementEvidence,
    create_authority_history_revision,
)
from metis_model1.brain_protocol import bytes_sha256, canonical_json


def _sha(char: str) -> str:
    return "sha256:" + char * 64


def _ref(namespace: str, number: int) -> str:
    return f"hostref:{namespace}:{number:048x}"


TARGET = _ref("target", 1)
BASIS = _ref("basis", 1)
REQ = _ref("requirement", 1)
REQ2 = _ref("requirement", 2)
ENDPOINT_SLOT = _ref("grant", 1)
ENDPOINT = _ref("grant", 2)
QUERY = _ref("grant", 3)
CATALOG = _ref("grant", 4)
FIELD = _ref("grant", 5)
OPERATOR = _ref("grant", 6)
VALUE = _ref("grant", 7)
INPUT = _ref("grant", 8)
INPUT_TYPE = _ref("grant", 9)
EXPANSION = _ref("grant", 20)
PATTERN = _ref("grant", 21)
AXIS = _ref("grant", 22)
CONTEXT = _sha("a")
SEMANTIC = _sha("b")
TOOLCHAIN = _sha("3")


def _lit(value: str) -> dict[str, Any]:
    return {"kind": "lit", "lexical": "text", "value": value}


def _presentation() -> dict[str, Any]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _fetch() -> dict[str, Any]:
    return {
        "from": {"kind": "catalog", "catalog": "video"},
        "cardinality": {"mode": "total", "value": 20},
        "over_fetch": None,
        "alias": None,
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "clauses": [],
        "group_by": None,
        "order": [],
        "output": None,
    }


def _endpoint(*, with_query: bool = True) -> dict[str, Any]:
    block = {
        "name": "main",
        "parameters": [],
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "fetches": [_fetch()] if with_query else [],
        "blocks": [],
        "uses": [],
        "output": None,
    }
    return {
        "name": "play.brain_create",
        "reference": "brainCreate",
        "params": {"timeout": None, "expires": None, "paginate": None},
        "inputs": [],
        "needs_time": False,
        "attributes": [],
        "input_pipeline": [],
        "output_pipeline": [],
        "inheritance": {"without_input": [], "without_output": []},
        "context": [],
        "blocks": [block] if with_query else [],
        "variants": [],
        "output": None,
    }


def _grant(
    ref: str,
    roles: tuple[str, ...],
    fragment_kind: str,
    fragment: Any,
    *,
    requirement: RequirementEvidence | None = None,
) -> CreateAuthorityGrant:
    payload = {"fragment_kind": fragment_kind, "fragment": fragment}
    return CreateAuthorityGrant(
        ref=ref,
        roles=roles,
        label=roles[0],
        payload=payload,
        payload_sha256=bytes_sha256(canonical_json(payload)),
        requirement=requirement,
    )


def _issued(
    *,
    mode: str = "initial",
    endpoint_fragment_kind: str = "endpoint",
    requirement_authorities: dict[str, tuple[str, ...]] | None = None,
    requirements: tuple[str, ...] = (REQ,),
    allowed_kinds: tuple[str, ...] = (
        "endpoint.create",
        "query.set_catalog",
        "query.add_predicate",
        "query.set_order",
        "query.set_take",
        "input.declare",
        "repeat.expand",
        "matrix.expand",
    ),
) -> Issued:
    history = (CreateAuthorityHistoryMessage(0, "crea", bytes_sha256(b"crea")),)
    history_revision = create_authority_history_revision(history)
    authorities = [
        _grant(TARGET, ("target",), "qualifiedIdentifier", "play.brain_create"),
        _grant(
            ENDPOINT_SLOT,
            ("endpoint_slot",),
            endpoint_fragment_kind,
            _endpoint(with_query=False),
        ),
        _grant(ENDPOINT, ("endpoint",), "qualifiedIdentifier", "play.brain_create"),
        _grant(QUERY, ("query",), "identifier", "query_0"),
        _grant(CATALOG, ("catalog",), "identifier", "video"),
        _grant(FIELD, ("field",), "identifier", "paesiorigine"),
        _grant(OPERATOR, ("predicate_operator",), "identifier", "eq"),
        _grant(VALUE, ("catalog_value",), "value", _lit("Italia")),
        _grant(
            INPUT,
            ("input_slot",),
            "input",
            {
                "name": "query",
                "type": "text",
                "required": True,
                "not_empty": True,
                "default": None,
            },
        ),
        _grant(INPUT_TYPE, ("input_type",), "identifier", "text"),
        _grant(EXPANSION, ("expansion_slot",), "identifier", "rows"),
        _grant(PATTERN, ("expansion_pattern",), "use", {"kind": "direct", "block": "main"}),
        _grant(
            AXIS,
            ("matrix_axis",),
            "parameter",
            {"name": "genre", "required": True, "type": None, "default": None},
        ),
    ]
    if mode == "refinement":
        authorities.append(_grant(BASIS, ("basis",), "identifier", "current_proposal"))
    for index, requirement_ref in enumerate(requirements):
        evidence = RequirementEvidence(
            origin="operator",
            message_ordinal=0,
            start_utf8=0,
            end_utf8=4,
            evidence_sha256=bytes_sha256(b"crea"),
            allowed_kinds=allowed_kinds,
        )
        authorities.append(
            _grant(
                requirement_ref,
                ("requirement",),
                "identifier",
                f"requirement_{index}",
                requirement=evidence,
            )
        )
    surface = CreateAuthoritySurface(
        history=history,
        history_revision=history_revision,
        target_ref=TARGET,
        basis_ref=BASIS if mode == "refinement" else None,
        grants=authorities,
    )
    all_authorities = tuple(
        ref
        for ref in (
            ENDPOINT_SLOT,
            ENDPOINT,
            QUERY,
            CATALOG,
            FIELD,
            OPERATOR,
            VALUE,
            INPUT,
            INPUT_TYPE,
            EXPANSION,
            PATTERN,
            AXIS,
        )
    )
    registry = PrivateAuthorityRegistry(
        surface=surface,
        key_to_ref={"target": TARGET},
        requirement_authorities=requirement_authorities
        or {requirement_ref: all_authorities for requirement_ref in requirements},
    )
    return Issued(
        surface=surface,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        toolchain_binding=TOOLCHAIN,
        generation=0 if mode == "initial" else 1,
        private_registry=registry,
    )


def _op(kind: str, ordinal: int, *, requirements: list[str] | None = None) -> dict[str, Any]:
    common = {
        "ordinal": ordinal,
        "kind": kind,
        "depends_on": [] if ordinal == 0 else [ordinal - 1],
        "requirement_refs": requirements or [REQ],
    }
    fields = {
        "endpoint.create": {"endpoint_ref": ENDPOINT_SLOT},
        "query.set_catalog": {"query_ref": QUERY, "catalog_ref": CATALOG},
        "query.add_predicate": {
            "query_ref": QUERY,
            "field_ref": FIELD,
            "operator_ref": OPERATOR,
            "value_refs": [VALUE],
        },
        "query.set_order": {"query_ref": QUERY, "key_ref": FIELD, "direction": "descending"},
        "query.set_take": {"query_ref": QUERY, "count": 24},
        "input.declare": {
            "endpoint_ref": ENDPOINT,
            "input_ref": INPUT,
            "type_ref": INPUT_TYPE,
        },
        "repeat.expand": {
            "target_ref": EXPANSION,
            "pattern_ref": PATTERN,
            "item_refs": [VALUE],
        },
        "matrix.expand": {
            "target_ref": EXPANSION,
            "pattern_ref": PATTERN,
            "axis_refs": [AXIS],
            "rows": [[VALUE]],
        },
    }
    return common | fields[kind]


def _plan(
    issued: Issued, operations: list[dict[str, Any]], requirements: list[str] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_DELTA_PLAN_CONTRACT,
        "mode": "initial" if issued.surface.basis_ref is None else "refinement",
        "context_revision": _sha("a"),
        "semantic_revision": _sha("b"),
        "surface_revision": issued.surface.surface_revision,
        "target_ref": TARGET,
        "basis_ref": issued.surface.basis_ref,
        "requirements": requirements or [REQ],
        "operations": operations,
    }


def _placement(
    issued: Issued,
    operations: list[dict[str, Any]],
    *,
    paths: list[tuple[str | int, ...]] | None = None,
    required_constructs: tuple[str, ...] = (),
) -> CreatePlacementManifest:
    default_query = ("endpoint", "blocks", 0, "fetches", 0)
    defaults = {
        "endpoint.create": ("endpoint",),
        "input.declare": ("endpoint", "inputs"),
        "query.set_catalog": default_query,
        "query.add_predicate": default_query,
        "query.set_order": default_query,
        "query.set_take": default_query,
    }
    action = {
        "endpoint.create": "replace_endpoint",
        "input.declare": "append_input",
        "query.set_catalog": "mutate_query",
        "query.add_predicate": "mutate_query",
        "query.set_order": "mutate_query",
        "query.set_take": "mutate_query",
        "repeat.expand": "unsupported",
        "matrix.expand": "unsupported",
    }
    anchor = {
        "endpoint.create": "endpoint_ref",
        "input.declare": "input_ref",
        "query.set_catalog": "query_ref",
        "query.add_predicate": "query_ref",
        "query.set_order": "query_ref",
        "query.set_take": "query_ref",
        "repeat.expand": "target_ref",
        "matrix.expand": "target_ref",
    }
    result = []
    for index, operation in enumerate(operations):
        kind = operation["kind"]
        result.append(
            CreateOperationPlacement(
                ordinal=index,
                operation_kind=kind,
                anchor_ref=operation[anchor[kind]],
                action=action[kind],
                path=(paths[index] if paths else defaults.get(kind, ("endpoint",))),
                clause_intent="include" if kind == "query.add_predicate" else None,
            )
        )
    return CreatePlacementManifest(
        surface_revision=issued.surface.surface_revision,
        placements=tuple(result),
        required_constructs=required_constructs,
        contract_id=CREATE_PLACEMENT_CONTRACT,
    )


def _permit(
    prepared, *, parent: bool = False
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    operations = [
        {
            "ordinal": ordinal,
            "operation_ref": f"hostref:operation:{ordinal + 1:032x}",
            "operation_sha256": digest,
        }
        for ordinal, digest in enumerate(prepared.operation_sha256)
    ]
    binding = {
        "session_id": "s" * 43,
        "turn_id": "t" * 32,
        "request_sha256": _sha("1"),
        "instruction_sha256": _sha("2"),
        "context_revision": prepared.context_revision,
        "semantic_source_revision": prepared.semantic_revision,
        "toolchain_binding": prepared.toolchain_binding,
        "target_ref": prepared.target_ref,
        "target_sha256": _sha("4"),
        "conversation_id": _sha("5"),
        "conversation_generation": prepared.generation,
        "parent_proposal_ref": f"hostref:parent_proposal:{1:032x}" if parent else None,
        "parent_proposal_sha256": _sha("6") if parent else None,
        "parent_source_sha256": _sha("7") if parent else None,
        "parent_manifest_sha256": _sha("8") if parent else None,
        "parent_ir_sha256": _sha("9") if parent else None,
        "outline_sha256": prepared.outline_sha256,
        "plan_sha256": prepared.plan_sha256,
        "grants_sha256": prepared.grants_sha256,
    }
    document = {
        "schema_version": 1,
        "contract_id": CREATE_PERMIT_CONTRACT,
        "permit_id": f"hostref:permit:{1:032x}",
        "nonce": f"hostref:nonce:{1:032x}",
        "issued_at_ms": 1_000,
        "expires_at_ms": 61_000,
        "binding": binding,
        "operation_seals": operations,
    }
    roles = {
        document["permit_id"]: "permit",
        document["nonce"]: "nonce",
        binding["target_ref"]: "target",
        **{item["operation_ref"]: "operation" for item in operations},
    }
    if parent:
        roles[binding["parent_proposal_ref"]] = "parent_proposal"
    consumption = {
        "schema_version": 1,
        "contract_id": CREATE_CONSUMPTION_CONTRACT,
        "permit_id": document["permit_id"],
        "nonce": document["nonce"],
        "permit_sha256": "placeholder",
        "operation_seals": copy.deepcopy(operations),
    }
    return document, roles, consumption


def _authorize(prepared, *, parent: bool = False):
    document, roles, consumption = _permit(prepared, parent=parent)
    from metis_model1.brain_create_permit import issue_create_permit

    permit = issue_create_permit(document, issued_ref_roles=roles)
    consumption["permit_sha256"] = permit.permit_sha256
    return authorize_prepared_create(
        prepared,
        permit_document=document,
        issued_permit_ref_roles=roles,
        consumption_document=consumption,
        current_binding=copy.deepcopy(document["binding"]),
        now_ms=2_000,
    )


def test_supported_plan_expands_deterministically_and_releases_only_after_burn() -> None:
    issued = _issued()
    operations = [
        _op("endpoint.create", 0),
        _op("input.declare", 1),
    ]
    plan = _plan(issued, operations)
    manifest = _placement(issued, operations)
    first = prepare_create_delta_plan(plan, issued=issued, placement_manifest=manifest)
    second = prepare_create_delta_plan(
        copy.deepcopy(plan), issued=issued, placement_manifest=manifest
    )
    assert first.plan_sha256 == second.plan_sha256
    assert first.outline_sha256 == second.outline_sha256
    assert first.spec_sha256 == second.spec_sha256
    assert first.operation_sha256 == second.operation_sha256
    assert first.context_revision == CONTEXT
    assert first.semantic_revision == SEMANTIC
    assert first.toolchain_binding == TOOLCHAIN
    assert first.generation == 0
    assert not hasattr(first, "spec")

    authorized = _authorize(first)
    assert authorized.spec["endpoint"]["inputs"] == [
        {
            "name": "query",
            "type": "text",
            "required": True,
            "not_empty": True,
            "default": None,
        }
    ]


@pytest.mark.parametrize("revision_key", ["context_revision", "semantic_revision"])
def test_untrusted_plan_revision_cannot_define_its_own_expected_authority(
    revision_key: str,
) -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0)]
    plan = _plan(issued, operations)
    plan[revision_key] = _sha("f")

    with pytest.raises(CreateExecutorError) as raised:
        prepare_create_delta_plan(
            plan,
            issued=issued,
            placement_manifest=_placement(issued, operations),
        )
    assert raised.value.code == "CREATE_DELTA_PLAN_INVALID"


def test_query_set_take_is_explicit_total_cardinality_not_page_or_scope() -> None:
    issued = _issued(mode="refinement", allowed_kinds=("query.set_take",))
    parent = {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": _endpoint(),
    }
    operation = _op("query.set_take", 0)
    operation["depends_on"] = []
    prepared = prepare_create_delta_plan(
        _plan(issued, [operation]),
        issued=issued,
        placement_manifest=_placement(issued, [operation]),
        parent_spec=parent,
        expected_parent_spec_sha256=bytes_sha256(canonical_json(parent)),
    )

    authorized = _authorize(prepared, parent=True)
    fetch = authorized.spec["endpoint"]["blocks"][0]["fetches"][0]
    assert fetch["cardinality"] == {"mode": "total", "value": 24}
    assert "count" not in fetch


def test_one_structural_anchor_cannot_bind_two_paths() -> None:
    issued = _issued(mode="refinement", allowed_kinds=("query.set_catalog", "query.set_take"))
    parent = {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": _endpoint(),
    }
    operations = [_op("query.set_catalog", 0), _op("query.set_take", 1)]
    operations[0]["depends_on"] = []
    manifest = _placement(
        issued,
        operations,
        paths=[
            ("endpoint", "blocks", 0, "fetches", 0),
            ("endpoint", "blocks", 0, "fetches", 1),
        ],
    )

    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations),
            issued=issued,
            placement_manifest=manifest,
            parent_spec=parent,
            expected_parent_spec_sha256=bytes_sha256(canonical_json(parent)),
        )
    assert caught.value.code == "CREATE_PLACEMENT_DRIFT"


def test_role_compatible_ref_bound_to_wrong_requirement_is_rejected() -> None:
    issued = _issued(
        requirements=(REQ, REQ2),
        requirement_authorities={
            REQ: (ENDPOINT_SLOT,),
            REQ2: (ENDPOINT, INPUT_TYPE),  # INPUT deliberately absent although role-compatible
        },
    )
    operations = [
        _op("endpoint.create", 0, requirements=[REQ]),
        _op("input.declare", 1, requirements=[REQ2]),
    ]
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations, requirements=[REQ, REQ2]),
            issued=issued,
            placement_manifest=_placement(issued, operations),
        )
    assert caught.value.code == "CREATE_REQUIREMENT_AUTHORITY_MISMATCH"


def test_exact_role_fragment_matrix_rejects_a_role_compatible_wrong_fragment() -> None:
    issued = _issued(endpoint_fragment_kind="container")
    operations = [_op("endpoint.create", 0)]
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations),
            issued=issued,
            placement_manifest=_placement(issued, operations),
        )
    assert caught.value.code == "CREATE_FRAGMENT_ROLE_MISMATCH"


def test_unknown_and_drifted_placements_fail_closed() -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0), _op("input.declare", 1)]
    manifest = _placement(
        issued,
        operations,
        paths=[("endpoint",), ("endpoint", "missing")],
    )
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations), issued=issued, placement_manifest=manifest
        )
    assert caught.value.code == "CREATE_PLACEMENT_UNKNOWN"

    stale = replace(manifest, surface_revision=_sha("f"))
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations), issued=issued, placement_manifest=stale
        )
    assert caught.value.code == "CREATE_PLACEMENT_STALE"


def test_refinement_copies_parent_and_binds_its_exact_hash() -> None:
    issued = _issued(mode="refinement", allowed_kinds=("input.declare",))
    parent = {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": _endpoint(with_query=False),
    }
    parent_hash = bytes_sha256(canonical_json(parent))
    operations = [_op("input.declare", 0)]
    operations[0]["depends_on"] = []
    prepared = prepare_create_delta_plan(
        _plan(issued, operations),
        issued=issued,
        placement_manifest=_placement(issued, operations),
        parent_spec=parent,
        expected_parent_spec_sha256=parent_hash,
    )
    parent["endpoint"]["inputs"].append({"tampered": True})
    authorized = _authorize(prepared, parent=True)
    assert authorized.spec["endpoint"]["inputs"] == [
        {
            "name": "query",
            "type": "text",
            "required": True,
            "not_empty": True,
            "default": None,
        }
    ]

    pristine = {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": _endpoint(with_query=False),
    }
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations),
            issued=issued,
            placement_manifest=_placement(issued, operations),
            parent_spec=pristine,
            expected_parent_spec_sha256=_sha("0"),
        )
    assert caught.value.code == "CREATE_PARENT_DRIFT"


@pytest.mark.parametrize("kind", ["repeat.expand", "matrix.expand"])
def test_repeat_and_matrix_fail_with_exact_gap_instead_of_inventing_a_recipe(kind: str) -> None:
    issued = _issued(mode="refinement", allowed_kinds=(kind,))
    operation = _op(kind, 0)
    operation["depends_on"] = []
    parent = {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": _endpoint(with_query=False),
    }
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, [operation]),
            issued=issued,
            placement_manifest=_placement(issued, [operation]),
            parent_spec=parent,
            expected_parent_spec_sha256=bytes_sha256(canonical_json(parent)),
        )
    assert caught.value.code == "CREATE_PLAN_V1_INSUFFICIENT"
    assert caught.value.gap_report is not None
    assert caught.value.gap_report.unsupported_kinds == (kind,)
    assert len(caught.value.gap_report.required_extensions) == 1


@pytest.mark.parametrize("kind", ["repeat.expand", "matrix.expand"])
def test_repeat_and_matrix_public_collection_bound_is_rechecked(kind: str) -> None:
    issued = _issued(mode="refinement", allowed_kinds=(kind,))
    operation = _op(kind, 0)
    operation["depends_on"] = []
    refs = [_ref("grant", 100 + index) for index in range(33)]
    if kind == "repeat.expand":
        operation["item_refs"] = refs
    else:
        operation["rows"] = [[ref] for ref in refs]
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, [operation]),
            issued=issued,
            placement_manifest=_placement(issued, [operation]),
            parent_spec={
                "schema_version": 1,
                "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
                "endpoint": _endpoint(with_query=False),
            },
            expected_parent_spec_sha256=_sha("0"),
        )
    assert caught.value.code == "CREATE_DELTA_PLAN_INVALID"


def test_frozen_ten_journey_construct_gap_is_complete_and_machine_readable() -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0)]
    manifest = _placement(
        issued,
        operations,
        required_constructs=tuple(PLAN_V1_REQUIRED_EXTENSIONS),
    )
    with pytest.raises(CreateExecutorError) as caught:
        prepare_create_delta_plan(
            _plan(issued, operations),
            issued=issued,
            placement_manifest=manifest,
        )
    assert caught.value.code == "CREATE_PLAN_V1_INSUFFICIENT"
    assert caught.value.gap_report is not None
    assert caught.value.gap_report.unsupported_kinds == ()
    assert len(caught.value.gap_report.required_extensions) == len(PLAN_V1_REQUIRED_EXTENSIONS)
    assert set(caught.value.gap_report.required_extensions) == set(
        PLAN_V1_REQUIRED_EXTENSIONS.values()
    )


def test_permit_drift_burns_prepared_authority_and_replay_is_rejected() -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0)]
    prepared = prepare_create_delta_plan(
        _plan(issued, operations),
        issued=issued,
        placement_manifest=_placement(issued, operations),
    )
    document, roles, consumption = _permit(prepared)
    from metis_model1.brain_create_permit import issue_create_permit

    permit = issue_create_permit(document, issued_ref_roles=roles)
    consumption["permit_sha256"] = permit.permit_sha256
    drifted = copy.deepcopy(document["binding"])
    drifted["request_sha256"] = _sha("e")
    with pytest.raises(CreateExecutorError) as drift:
        authorize_prepared_create(
            prepared,
            permit_document=document,
            issued_permit_ref_roles=roles,
            consumption_document=consumption,
            current_binding=drifted,
            now_ms=2_000,
        )
    assert drift.value.code == "CREATE_PERMIT_DRIFT"
    with pytest.raises(CreateExecutorError) as replay:
        authorize_prepared_create(
            prepared,
            permit_document=document,
            issued_permit_ref_roles=roles,
            consumption_document=consumption,
            current_binding=document["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "CREATE_PERMIT_REPLAY"


@pytest.mark.parametrize(
    ("binding_key", "drifted_value"),
    [
        ("context_revision", _sha("e")),
        ("semantic_source_revision", _sha("e")),
        ("toolchain_binding", _sha("e")),
        ("conversation_generation", 99),
    ],
)
def test_permit_uses_issued_authoritative_binding(
    binding_key: str, drifted_value: str | int
) -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0)]
    prepared = prepare_create_delta_plan(
        _plan(issued, operations),
        issued=issued,
        placement_manifest=_placement(issued, operations),
    )
    document, roles, consumption = _permit(prepared)
    document["binding"][binding_key] = drifted_value

    with pytest.raises(CreateExecutorError) as caught:
        authorize_prepared_create(
            prepared,
            permit_document=document,
            issued_permit_ref_roles=roles,
            consumption_document=consumption,
            current_binding=copy.deepcopy(document["binding"]),
            now_ms=2_000,
        )
    assert caught.value.code == "CREATE_PERMIT_DRIFT"


def test_post_prepare_private_bytes_tamper_is_detected_before_release() -> None:
    issued = _issued()
    operations = [_op("endpoint.create", 0)]
    prepared = prepare_create_delta_plan(
        _plan(issued, operations),
        issued=issued,
        placement_manifest=_placement(issued, operations),
    )
    object.__setattr__(prepared, "_spec_bytes", b"{}")
    with pytest.raises(CreateExecutorError) as caught:
        _authorize(prepared)
    assert caught.value.code == "CREATE_EXECUTION_TAMPERED"
