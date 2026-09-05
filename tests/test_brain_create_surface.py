from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.brain_create_plan import (
    CREATE_DELTA_PLAN_CONTRACT,
    validate_create_delta_plan,
)
from metis_model1.brain_create_surface import (
    MAX_HISTORY_BYTES,
    MAX_HISTORY_MESSAGE_BYTES,
    MAX_HISTORY_MESSAGES,
    MAX_LABEL_CHARACTERS,
    MAX_PAYLOAD_ARRAY_ITEMS,
    CreateAuthorityGrant,
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurface,
    CreateAuthoritySurfaceError,
    RequirementEvidence,
    create_authority_history_revision,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

MESSAGES = (
    "Crea un endpoint dedicato ai film.",
    "Portalo a 24 film italiani.",
    "Se non trovi risultati usa film europei come fallback.",
)
TARGET = "hostref:target"
BASIS = "hostref:basis"
REQ_CREATE = "hostref:req-create"
REQ_TAKE = "hostref:req-take"
ENDPOINT = "hostref:endpoint"
QUERY = "hostref:query"


def _sha(value: object) -> str:
    return bytes_sha256(canonical_json(value))


def _history(messages: tuple[str, ...] = MESSAGES) -> list[CreateAuthorityHistoryMessage]:
    return [
        CreateAuthorityHistoryMessage(
            ordinal=ordinal,
            text=text,
            message_sha256=bytes_sha256(text.encode("utf-8")),
        )
        for ordinal, text in enumerate(messages)
    ]


def _evidence(
    message_ordinal: int,
    needle: str,
    *allowed_kinds: str,
    messages: tuple[str, ...] = MESSAGES,
) -> RequirementEvidence:
    message = messages[message_ordinal]
    character_start = message.index(needle)
    start = len(message[:character_start].encode("utf-8"))
    raw = needle.encode("utf-8")
    return RequirementEvidence(
        origin="operator",
        message_ordinal=message_ordinal,
        start_utf8=start,
        end_utf8=start + len(raw),
        evidence_sha256=bytes_sha256(raw),
        allowed_kinds=allowed_kinds,
    )


def _nonoperator_evidence(
    origin: str,
    payload: dict[str, object],
    *allowed_kinds: str,
) -> RequirementEvidence:
    return RequirementEvidence(
        origin=origin,
        message_ordinal=None,
        start_utf8=None,
        end_utf8=None,
        evidence_sha256=_sha(payload),
        allowed_kinds=allowed_kinds,
        evidence_payload=payload,
    )


def _grant(
    ref: str,
    roles: list[str] | tuple[str, ...],
    label: str,
    payload: object,
    *,
    requirement: RequirementEvidence | None = None,
) -> CreateAuthorityGrant:
    return CreateAuthorityGrant(
        ref=ref,
        roles=roles,
        label=label,
        payload=payload,
        payload_sha256=_sha(payload),
        requirement=requirement,
    )


def _grants(*, include_basis: bool = False) -> list[CreateAuthorityGrant]:
    grants = [
        _grant(TARGET, ["target"], "Destinazione della bozza", {"identity": "demo.brain"}),
        _grant(
            REQ_CREATE,
            ["requirement"],
            "Creazione richiesta",
            {"category": "creation"},
            requirement=_evidence(0, "Crea un endpoint", "endpoint.create"),
        ),
        _grant(
            REQ_TAKE,
            ["requirement"],
            "Quantità richiesta",
            {"category": "quantity"},
            requirement=_evidence(1, "24 film italiani", "query.set_take"),
        ),
        _grant(
            ENDPOINT,
            ["endpoint_slot", "endpoint"],
            "Nuovo endpoint",
            {"slot": "endpoint_root"},
        ),
        _grant(QUERY, ["query"], "Query principale", {"slot": "primary_query"}),
    ]
    if include_basis:
        grants.append(_grant(BASIS, ["basis"], "Bozza precedente", {"proposal": "prior_draft"}))
    return grants


def _surface(
    *,
    grants: list[CreateAuthorityGrant] | None = None,
    basis_ref: str | None = None,
    history: list[CreateAuthorityHistoryMessage] | None = None,
    history_revision: str | None = None,
) -> CreateAuthoritySurface:
    messages = _history() if history is None else history
    return CreateAuthoritySurface(
        history=messages,
        history_revision=(
            create_authority_history_revision(messages)
            if history_revision is None
            else history_revision
        ),
        target_ref=TARGET,
        basis_ref=basis_ref,
        grants=_grants(include_basis=basis_ref is not None) if grants is None else grants,
    )


def test_surface_outputs_plan_compatible_roles_requirements_and_revision() -> None:
    surface = _surface()
    plan = {
        "schema_version": 1,
        "contract_id": CREATE_DELTA_PLAN_CONTRACT,
        "mode": "initial",
        "context_revision": "sha256:" + "a" * 64,
        "semantic_revision": "sha256:" + "b" * 64,
        "surface_revision": surface.surface_revision,
        "target_ref": TARGET,
        "basis_ref": None,
        "requirements": [REQ_CREATE, REQ_TAKE],
        "operations": [
            {
                "ordinal": 0,
                "kind": "endpoint.create",
                "depends_on": [],
                "requirement_refs": [REQ_CREATE],
                "endpoint_ref": ENDPOINT,
            },
            {
                "ordinal": 1,
                "kind": "query.set_take",
                "depends_on": [0],
                "requirement_refs": [REQ_TAKE],
                "query_ref": QUERY,
                "count": 24,
            },
        ],
    }
    assert (
        validate_create_delta_plan(
            plan,
            issued_refs=surface.issued_roles,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_revision="sha256:" + "b" * 64,
            expected_surface_revision=surface.surface_revision,
            expected_target_ref=surface.target_ref,
            expected_basis_ref=surface.basis_ref,
            expected_requirement_kinds=surface.expected_requirement_kinds,
        )
        == []
    )


def test_history_is_canonical_ordered_bounded_and_sealed_into_surface_revision() -> None:
    history = _history()
    surface = _surface(history=history)
    expected_history_revision = create_authority_history_revision(history)
    assert surface.history_revision == expected_history_revision

    changed_history = _history((*MESSAGES[:2], "Usa drammi europei come fallback."))
    changed = _surface(history=changed_history)
    assert changed.history_revision != expected_history_revision
    assert changed.surface_revision != surface.surface_revision

    history.reverse()
    history[0] = CreateAuthorityHistoryMessage(
        ordinal=0,
        text="manomesso",
        message_sha256=bytes_sha256(b"manomesso"),
    )
    assert surface.history_revision == expected_history_revision
    assert surface.surface_revision != changed.surface_revision

    with pytest.raises(CreateAuthoritySurfaceError, match="history revision"):
        _surface(history_revision="sha256:" + "0" * 64)


def test_history_requires_exact_message_digests_and_contiguous_server_ordinals() -> None:
    wrong_digest = _history()
    wrong_digest[1] = CreateAuthorityHistoryMessage(
        ordinal=1,
        text=MESSAGES[1],
        message_sha256="sha256:" + "0" * 64,
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="message hash"):
        create_authority_history_revision(wrong_digest)

    out_of_order = _history()
    out_of_order[1] = CreateAuthorityHistoryMessage(
        ordinal=7,
        text=MESSAGES[1],
        message_sha256=bytes_sha256(MESSAGES[1].encode("utf-8")),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="contiguous and ordered"):
        create_authority_history_revision(out_of_order)

    oversized = _history(tuple(f"Messaggio {index}" for index in range(MAX_HISTORY_MESSAGES + 1)))
    with pytest.raises(CreateAuthoritySurfaceError, match="message bound"):
        create_authority_history_revision(oversized)


def test_history_accepts_64_messages_but_rejects_a_65th() -> None:
    bounded = _history(tuple(f"Messaggio {index}" for index in range(MAX_HISTORY_MESSAGES)))

    assert create_authority_history_revision(bounded).startswith("sha256:")

    overflow = _history(tuple(f"Messaggio {index}" for index in range(MAX_HISTORY_MESSAGES + 1)))
    with pytest.raises(CreateAuthoritySurfaceError, match="message bound"):
        create_authority_history_revision(overflow)


def test_history_total_byte_bound_remains_twenty_maximum_messages() -> None:
    assert MAX_HISTORY_BYTES == 20 * MAX_HISTORY_MESSAGE_BYTES
    at_total_bound = _history(tuple("x" * MAX_HISTORY_MESSAGE_BYTES for _ in range(20)))

    assert create_authority_history_revision(at_total_bound).startswith("sha256:")

    over_total_bound = _history(tuple("x" * MAX_HISTORY_MESSAGE_BYTES for _ in range(20)) + ("x",))
    with pytest.raises(CreateAuthoritySurfaceError, match="byte bound"):
        create_authority_history_revision(over_total_bound)


def test_model_projection_contains_only_safe_fields_and_requirement_kinds() -> None:
    projection = _surface().model_projection()
    assert projection
    for item in projection:
        expected_keys = {"ref", "roles", "label"}
        if item["roles"] == ["requirement"]:
            expected_keys.add("allowed_kinds")
            assert item["allowed_kinds"] in [["endpoint.create"], ["query.set_take"]]
        assert set(item) == expected_keys
    assert all(len(item["label"]) <= MAX_LABEL_CHARACTERS for item in projection)
    serialized = repr(projection)
    assert "payload" not in serialized
    assert "sha256" not in serialized
    assert "start_utf8" not in serialized
    assert "message_ordinal" not in serialized
    assert "origin" not in serialized


def test_renderer_resolution_is_revision_and_role_checked_and_detached() -> None:
    payload = {"slot": ["primary_query"]}
    grants = _grants()
    grants[-1] = _grant(QUERY, ["query"], "Query principale", payload)
    surface = _surface(grants=grants)

    resolved = surface.resolve(
        QUERY,
        required_role="query",
        expected_surface_revision=surface.surface_revision,
    )
    assert resolved == payload
    resolved["slot"].append("mutated")
    assert surface.resolve(
        QUERY,
        required_role="query",
        expected_surface_revision=surface.surface_revision,
    ) == {"slot": ["primary_query"]}

    with pytest.raises(BrainError) as stale:
        surface.resolve(
            QUERY,
            required_role="query",
            expected_surface_revision="sha256:" + "f" * 64,
        )
    assert stale.value.code == "CREATE_SURFACE_STALE"
    with pytest.raises(BrainError) as wrong_role:
        surface.resolve(
            QUERY,
            required_role="catalog",
            expected_surface_revision=surface.surface_revision,
        )
    assert wrong_role.value.code == "CREATE_SURFACE_ROLE_MISMATCH"
    with pytest.raises(BrainError) as unknown:
        surface.resolve(
            "hostref:unknown",
            required_role="query",
            expected_surface_revision=surface.surface_revision,
        )
    assert unknown.value.code == "CREATE_SURFACE_REF_UNKNOWN"


def test_input_and_returned_mutations_cannot_change_the_sealed_surface() -> None:
    payload = {"slot": ["primary_query"]}
    roles = ["query"]
    grants = _grants()
    grants[-1] = _grant(QUERY, roles, "Query principale", payload)
    surface = _surface(grants=grants)
    revision = surface.surface_revision

    payload["slot"].append("tampered")
    roles.append("catalog")
    grants.reverse()
    issued = surface.issued_roles
    expected = surface.expected_requirement_kinds
    projection = surface.model_projection()
    issued[QUERY] = frozenset({"catalog"})
    expected[REQ_CREATE] = frozenset({"query.set_take"})
    projection[0]["roles"].append("catalog")
    projection[0]["label"] = "tampered"

    assert surface.surface_revision == revision
    assert surface.issued_roles[QUERY] == frozenset({"query"})
    assert surface.expected_requirement_kinds[REQ_CREATE] == frozenset({"endpoint.create"})
    assert surface.resolve(
        QUERY,
        required_role="query",
        expected_surface_revision=revision,
    ) == {"slot": ["primary_query"]}
    assert all(item["label"] != "tampered" for item in surface.model_projection())


def test_canonical_revision_is_order_independent_but_seals_every_authority() -> None:
    grants = _grants()
    first = _surface(grants=grants)
    second = _surface(grants=list(reversed(grants)))
    assert first.surface_revision == second.surface_revision

    changed_payload = _grants()
    changed_payload[-1] = _grant(QUERY, ["query"], "Query principale", {"slot": "secondary_query"})
    assert _surface(grants=changed_payload).surface_revision != first.surface_revision

    changed_label = _grants()
    changed_label[-1] = _grant(QUERY, ["query"], "Query secondaria", {"slot": "primary_query"})
    assert _surface(grants=changed_label).surface_revision != first.surface_revision

    refinement = _surface(basis_ref=BASIS)
    assert refinement.surface_revision != first.surface_revision
    assert refinement.basis_ref == BASIS


@pytest.mark.parametrize("origin", ["clarification", "policy"])
def test_nonoperator_evidence_uses_private_payload_not_operator_span(origin: str) -> None:
    payload = (
        {"decision_kind": "result_count", "selected_count": 24}
        if origin == "clarification"
        else {"policy_id": "default_result_count", "policy_revision": "sha256:" + "c" * 64}
    )
    grants = _grants()
    grants[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità autorizzata",
        {"category": "quantity"},
        requirement=_nonoperator_evidence(origin, payload, "query.set_take"),
    )
    surface = _surface(grants=grants)
    revision = surface.surface_revision

    payload["tampered"] = True
    assert surface.surface_revision == revision
    projection = next(item for item in surface.model_projection() if item["ref"] == REQ_TAKE)
    assert projection == {
        "ref": REQ_TAKE,
        "roles": ["requirement"],
        "label": "Quantità autorizzata",
        "allowed_kinds": ["query.set_take"],
    }
    assert "decision_kind" not in repr(surface.model_projection())
    assert "policy_revision" not in repr(surface.model_projection())


def test_evidence_origins_are_disjoint_and_fail_closed() -> None:
    operator_with_payload = _grants()
    original = _evidence(1, "24 film italiani", "query.set_take")
    operator_with_payload[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità richiesta",
        {"category": "quantity"},
        requirement=RequirementEvidence(
            origin="operator",
            message_ordinal=original.message_ordinal,
            start_utf8=original.start_utf8,
            end_utf8=original.end_utf8,
            evidence_sha256=original.evidence_sha256,
            allowed_kinds=original.allowed_kinds,
            evidence_payload={"decision_kind": "result_count"},
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="cannot carry"):
        _surface(grants=operator_with_payload)

    clarification_with_span = _grants()
    clarification_with_span[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità chiarita",
        {"category": "quantity"},
        requirement=RequirementEvidence(
            origin="clarification",
            message_ordinal=1,
            start_utf8=0,
            end_utf8=5,
            evidence_sha256=_sha({"decision_kind": "result_count"}),
            allowed_kinds=("query.set_take",),
            evidence_payload={"decision_kind": "result_count"},
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="cannot claim"):
        _surface(grants=clarification_with_span)

    missing_payload = _grants()
    missing_payload[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità chiarita",
        {"category": "quantity"},
        requirement=RequirementEvidence(
            origin="policy",
            message_ordinal=None,
            start_utf8=None,
            end_utf8=None,
            evidence_sha256=_sha({}),
            allowed_kinds=("query.set_take",),
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="non-empty JSON payload"):
        _surface(grants=missing_payload)

    wrong_decision_digest = _grants()
    wrong_decision_digest[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità chiarita",
        {"category": "quantity"},
        requirement=RequirementEvidence(
            origin="clarification",
            message_ordinal=None,
            start_utf8=None,
            end_utf8=None,
            evidence_sha256="sha256:" + "0" * 64,
            allowed_kinds=("query.set_take",),
            evidence_payload={"decision_kind": "result_count", "selected_count": 24},
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="payload hash"):
        _surface(grants=wrong_decision_digest)

    unknown_origin = _grants()
    unknown_origin[2] = _grant(
        REQ_TAKE,
        ["requirement"],
        "Quantità importata",
        {"category": "quantity"},
        requirement=RequirementEvidence(
            origin="model",
            message_ordinal=None,
            start_utf8=None,
            end_utf8=None,
            evidence_sha256=_sha({"claim": "model"}),
            allowed_kinds=("query.set_take",),
            evidence_payload={"claim": "model"},
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="origin is invalid"):
        _surface(grants=unknown_origin)


def test_payload_hash_duplicate_refs_and_role_roster_fail_closed() -> None:
    invalid_hash = _grants()
    invalid_hash[-1] = CreateAuthorityGrant(
        ref=QUERY,
        roles=["query"],
        label="Query principale",
        payload={"slot": "primary_query"},
        payload_sha256="sha256:" + "0" * 64,
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="hash does not match"):
        _surface(grants=invalid_hash)

    duplicate = _grants()
    duplicate.append(deepcopy(duplicate[-1]))
    with pytest.raises(CreateAuthoritySurfaceError, match="not unique"):
        _surface(grants=duplicate)

    duplicate_roles = _grants()
    duplicate_roles[-1] = _grant(
        QUERY, ["query", "query"], "Query principale", {"slot": "primary_query"}
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="roles are invalid"):
        _surface(grants=duplicate_roles)

    unknown_role = _grants()
    unknown_role[-1] = _grant(
        QUERY, ["query_source"], "Query principale", {"slot": "primary_query"}
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="roles are invalid"):
        _surface(grants=unknown_role)


def test_target_basis_and_requirement_grants_are_exact() -> None:
    target_extra_role = _grants()
    target_extra_role[0] = _grant(
        TARGET,
        ["target", "query"],
        "Destinazione della bozza",
        {"identity": "demo.brain"},
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="target root is not exact"):
        _surface(grants=target_extra_role)

    basis_without_root = _grants()
    with pytest.raises(CreateAuthoritySurfaceError, match="basis root is not exact"):
        _surface(grants=basis_without_root, basis_ref=BASIS)

    unexpected_basis = _grants(include_basis=True)
    with pytest.raises(CreateAuthoritySurfaceError, match="cannot contain a basis"):
        _surface(grants=unexpected_basis)

    missing_evidence = _grants()
    missing_evidence[1] = _grant(
        REQ_CREATE, ["requirement"], "Creazione richiesta", {"category": "creation"}
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="present together"):
        _surface(grants=missing_evidence)

    evidence_on_nonrequirement = _grants()
    evidence_on_nonrequirement[-1] = _grant(
        QUERY,
        ["query"],
        "Query principale",
        {"slot": "primary_query"},
        requirement=_evidence(1, "24 film italiani", "query.set_take"),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="present together"):
        _surface(grants=evidence_on_nonrequirement)


def test_requirement_evidence_uses_exact_utf8_boundaries_digest_and_kind_allowlist() -> None:
    wrong_digest = _grants()
    wrong_digest[1] = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=RequirementEvidence(
            origin="operator",
            message_ordinal=0,
            start_utf8=0,
            end_utf8=len(b"Crea un endpoint"),
            evidence_sha256="sha256:" + "0" * 64,
            allowed_kinds=("endpoint.create",),
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="evidence hash"):
        _surface(grants=wrong_digest)

    wrong_message = _grants()
    create_span = _evidence(0, "Crea un endpoint", "endpoint.create")
    wrong_message[1] = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=RequirementEvidence(
            origin="operator",
            message_ordinal=1,
            start_utf8=create_span.start_utf8,
            end_utf8=create_span.end_utf8,
            evidence_sha256=create_span.evidence_sha256,
            allowed_kinds=create_span.allowed_kinds,
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="evidence hash"):
        _surface(grants=wrong_message)

    unknown_message = _grants()
    unknown_message[1] = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=RequirementEvidence(
            origin="operator",
            message_ordinal=99,
            start_utf8=0,
            end_utf8=1,
            evidence_sha256=bytes_sha256(b"C"),
            allowed_kinds=("endpoint.create",),
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="not in authority history"):
        _surface(grants=unknown_message)

    unknown_kind = _grants()
    unknown_kind[1] = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=_evidence(0, "Crea un endpoint", "endpoint.clone"),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="allowlist"):
        _surface(grants=unknown_kind)

    duplicate_kind = _grants()
    duplicate_kind[1] = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=_evidence(
            0,
            "Crea un endpoint",
            "endpoint.create",
            "endpoint.create",
        ),
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="allowlist"):
        _surface(grants=duplicate_kind)

    accented_instruction = "Crea qualità"
    accented_raw = accented_instruction.encode("utf-8")
    split = accented_raw.index("à".encode()) + 1
    split_grant = _grant(
        REQ_CREATE,
        ["requirement"],
        "Creazione richiesta",
        {"category": "creation"},
        requirement=RequirementEvidence(
            origin="operator",
            message_ordinal=0,
            start_utf8=split,
            end_utf8=len(accented_raw),
            evidence_sha256=bytes_sha256(accented_raw[split:]),
            allowed_kinds=("endpoint.create",),
        ),
    )
    base = [grant for grant in _grants() if grant.ref not in {REQ_CREATE, REQ_TAKE}]
    with pytest.raises(CreateAuthoritySurfaceError, match="split a UTF-8"):
        history = _history((accented_instruction,))
        CreateAuthoritySurface(
            history=history,
            history_revision=create_authority_history_revision(history),
            target_ref=TARGET,
            basis_ref=None,
            grants=[*base, split_grant],
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "hidden"},
        {"value": "take 20 from catalog"},
        {"value": "@video"},
        {"value": "/tmp/golden.metis"},
        {"value": "catalogs/video.json"},
        {"value": "{{endpoint_template}}"},
        {"value": float("inf")},
        {"value": 9_007_199_254_740_992},
        {"value": ("tuple",)},
    ],
)
def test_payload_rejects_raw_authority_dsl_paths_templates_and_non_json_values(
    payload: object,
) -> None:
    grants = _grants()
    grants[-1] = CreateAuthorityGrant(
        ref=QUERY,
        roles=["query"],
        label="Query principale",
        payload=payload,
        payload_sha256="sha256:" + "0" * 64,
    )
    with pytest.raises(CreateAuthoritySurfaceError):
        _surface(grants=grants)


@pytest.mark.parametrize(
    "label",
    [
        "endpoint demo { take 20 }",
        "/tmp/golden.metis",
        "{{endpoint_template}}",
        "source code Metis",
        "sha256:" + "a" * 64,
        "x" * (MAX_LABEL_CHARACTERS + 1),
    ],
)
def test_public_labels_reject_dsl_paths_templates_hashes_and_oversize(label: str) -> None:
    grants = _grants()
    grants[-1] = _grant(QUERY, ["query"], label, {"slot": "primary_query"})
    with pytest.raises(CreateAuthoritySurfaceError):
        _surface(grants=grants)


def test_payload_structural_and_byte_bounds_are_enforced() -> None:
    oversized_array = _grants()
    oversized_array[-1] = _grant(
        QUERY,
        ["query"],
        "Query principale",
        {"values": list(range(MAX_PAYLOAD_ARRAY_ITEMS + 1))},
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="array exceeds"):
        _surface(grants=oversized_array)

    deep: object = "leaf"
    for _ in range(8):
        deep = {"nested": deep}
    excessive_depth = _grants()
    excessive_depth[-1] = _grant(QUERY, ["query"], "Query principale", {"value": deep})
    with pytest.raises(CreateAuthoritySurfaceError, match="structural bound"):
        _surface(grants=excessive_depth)

    large_bytes = _grants()
    large_bytes[-1] = _grant(
        QUERY,
        ["query"],
        "Query principale",
        {"values": ["x" * 128 for _ in range(MAX_PAYLOAD_ARRAY_ITEMS)]},
    )
    with pytest.raises(CreateAuthoritySurfaceError, match="byte bound"):
        _surface(grants=large_bytes)


def test_revision_from_another_surface_cannot_replay_private_resolution() -> None:
    original = _surface()
    grants = _grants()
    grants[-1] = _grant(QUERY, ["query"], "Query secondaria", {"slot": "secondary_query"})
    successor = _surface(grants=grants)
    with pytest.raises(BrainError) as raised:
        successor.resolve(
            QUERY,
            required_role="query",
            expected_surface_revision=original.surface_revision,
        )
    assert raised.value.code == "CREATE_SURFACE_STALE"
