"""Pinned-compiler integration proof for descriptor-native filtered CREATE."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_authority_issuer_v2 import CreateV2HostRefIssuer
from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_capability_inventory_v2 import (
    CREATE_V2_AUTHORITY_POLICY_SHA256,
    build_pinned_create_v2_capability_inventory,
)
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2PermitConsumer,
    execute_create_delta_plan_v2,
    issue_create_delta_plan_v2_permit,
)
from metis_model1.brain_create_plan_v2 import (
    admit_create_delta_plan_v2,
    derive_create_plan_v2_decoder_constraint,
    initial_create_endpoint_skeleton,
)
from metis_model1.brain_create_structural_authority_v2 import (
    StructuralIntent,
    filtered_collection_intent,
    reviewed_descriptor_filter_index,
    validate_structural_intent,
)
from metis_model1.brain_create_surface import CreateAuthorityHistoryMessage
from metis_model1.brain_protocol import bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import BrainCompiler


def _digest(label: str) -> str:
    return bytes_sha256(label.encode("utf-8"))


def _history(*messages: str) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(index, message, bytes_sha256(message.encode("utf-8")))
        for index, message in enumerate(messages)
    )


def _snapshot(
    *, tenant: str, catalog: str, field: str, values: tuple[str, ...], binding: str
) -> ContextSnapshot:
    value_items = ", ".join(
        json.dumps(value) + ' means "Valore sintetico revisionato"' for value in values
    )
    catalog_source = (
        "metis 0.43\n"
        f"catalog {catalog} {{\n"
        '  means "Archivio sintetico per la prova di generalità"\n'
        f"  index {json.dumps(catalog.rsplit('.', 1)[-1])}\n"
        "  id record_id\n"
        "  fields {\n"
        "    record_id keyword\n"
        f"    {field} keyword values [{value_items}]"
        ' means "Attributo sintetico revisionato"\n'
        "  }\n"
        "}\n"
    )
    config = f'[tenant]\nid = "{tenant}"\n\n[stdlib]\nlanguage = "0.43"\n'.encode()
    source = catalog_source.encode("utf-8")
    files = (
        SnapshotFile("metis.toml", config, bytes_sha256(config)),
        SnapshotFile("catalogs/source.metis", source, bytes_sha256(source)),
    )
    return ContextSnapshot(
        tenant_alias=tenant,
        tenant_id=tenant,
        root_device=1,
        root_inode=1,
        revision=_digest(f"context:{tenant}"),
        toolchain_binding=binding,
        files=files,
        total_bytes=sum(len(item.content) for item in files),
    )


def _retrieval(
    *, snapshot: ContextSnapshot, catalog: str, field: str, values: tuple[str, ...]
) -> RetrievalResult:
    domain = {"kind": "inline", "size": len(values)}
    selection = {
        "catalog": catalog,
        "field": field,
        "type": "keyword",
        "modifiers": [],
        "domain": domain,
    }
    if len(values) == 1:
        selection["literal"] = values[0]
    else:
        selection.update({"literals": list(values), "value_mode": "any_of"})
    return RetrievalResult(
        context={
            "semantic_schema": 2,
            "catalog_reference_roster": [catalog],
            "context_revision": snapshot.revision,
            "semantic_source_revision": snapshot.semantic_source_revision(),
            "toolchain_binding": snapshot.toolchain_binding,
            "catalog": {"name": catalog, "semantic": {"state": "reviewed"}},
            "fields": [
                {
                    "name": field,
                    "type": "keyword",
                    "modifiers": [],
                    "domain": domain,
                    "semantic": {"state": "reviewed"},
                    "values": [
                        {"literal": value, "semantic": {"state": "reviewed"}} for value in values
                    ],
                }
            ],
        },
        grounding={
            "status": "resolved",
            "catalogs": [catalog],
            "selections": [selection],
            "resolutions": [
                {
                    "catalog": catalog,
                    "field": field,
                    "literal": values[0] if len(values) == 1 else None,
                    "review_state": "reviewed",
                }
            ],
            "candidates": [],
            "unresolved": [],
            "lookup": None,
            "lookups": [],
        },
        semantic_source_revision=snapshot.semantic_source_revision(),
    )


def _execute_filtered_collection(
    *,
    snapshot: ContextSnapshot,
    endpoint: str,
    catalog: str,
    field: str,
    values: tuple[str, ...],
    count: int,
) -> tuple[StructuralIntent, str]:
    history = _history(
        "Crea una collezione filtrata dai descrittori revisionati.",
        f"Restituisci esattamente {count} risultati totali.",
    )
    retrieved = _retrieval(snapshot=snapshot, catalog=catalog, field=field, values=values)
    semantic = reviewed_descriptor_filter_index(
        retrieved=retrieved,
        context_revision=snapshot.revision,
        semantic_revision=snapshot.semantic_source_revision(),
        toolchain_binding=snapshot.toolchain_binding,
    )
    intent = filtered_collection_intent(
        count=count,
        messages=history,
        semantic=semantic,
        policy_revision=CREATE_V2_AUTHORITY_POLICY_SHA256,
    )
    assert [(mutation.member, mutation.fragment_type) for mutation in intent.mutations] == [
        ("blocks", "container"),
        ("variants", "variant"),
    ]
    assert intent.mutations[0].fragment["name"] == "main"
    response_root = intent.mutations[1].fragment
    assert response_root["name"] == "response_root"
    assert response_root["uses"] == [{"kind": "direct", "block": "main"}]
    assert (
        validate_structural_intent(
            intent,
            policy_revision=CREATE_V2_AUTHORITY_POLICY_SHA256,
            semantic_authority=semantic,
            result_count=count,
        )
        is intent
    )
    inventory = build_pinned_create_v2_capability_inventory(
        toolchain_binding=snapshot.toolchain_binding
    )
    issuer = CreateV2HostRefIssuer(hmac_key=b"i" * 32)
    issued = issuer.issue_structural_authority(
        inventory=inventory,
        intent=intent,
        semantic_authority=semantic,
        result_count=count,
        session_id="s" * 43,
        conversation_id=_digest(f"conversation:{endpoint}"),
        request_fingerprint=_digest(f"request:{endpoint}"),
        history_revision=_digest(f"history:{endpoint}"),
        context_revision=snapshot.revision,
        semantic_revision=snapshot.semantic_source_revision(),
        toolchain_binding=snapshot.toolchain_binding,
        generation=0,
        endpoint=endpoint,
        candidate_filename=f"brain-drafts/{endpoint.rsplit('.', 1)[-1]}.metis",
        parent_spec_sha256=None,
        parent_ir_sha256=None,
        parent_proposal_ref=None,
    )
    constraint = derive_create_plan_v2_decoder_constraint(
        issued.projection, issued.active_requirement_handles
    )
    body = {"o": [operation.body() for operation in constraint.direct_operations]}
    assert len(body["o"]) == len(intent.mutations)
    plan = admit_create_delta_plan_v2(
        body,
        projection=issued.projection,
        mode="initial",
        context_revision=snapshot.revision,
        semantic_revision=snapshot.semantic_source_revision(),
        target_ref=issued.target_ref,
        basis_ref=None,
        active_requirement_handles=issued.active_requirement_handles,
    )
    base = initial_create_endpoint_skeleton(endpoint)
    permit = issue_create_delta_plan_v2_permit(
        plan,
        issued.projection,
        base_spec=base,
        toolchain_binding=snapshot.toolchain_binding,
        generation=0,
    )
    execution = execute_create_delta_plan_v2(
        plan,
        issued.projection,
        base_spec=base,
        parent_spec_sha256=None,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=snapshot.toolchain_binding,
        generation=0,
    )
    return intent, render_create_endpoint(execution.spec).metis_text


def _pinned_compiler() -> BrainCompiler:
    root = os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT")
    node = os.environ.get("METIS_MODEL1_NODE")
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    metis_root, node_path = Path(root), Path(node)
    assert metis_root.is_dir() and node_path.is_file(), "configured test authority is unavailable"
    return BrainCompiler(metis_root=metis_root, node_path=node_path)


@pytest.mark.parametrize(
    ("tenant", "catalog", "field", "values", "count", "endpoint", "predicate"),
    (
        (
            "tenant-amber",
            "amber.archive",
            "hue_alpha",
            ("Topaz",),
            7,
            "amber.filtered",
            '@hue_alpha is "Topaz"',
        ),
        (
            "tenant-orbit",
            "orbit.ledger",
            "constellation_beta",
            ("Orion", "Lyra"),
            11,
            "orbit.filtered",
            '@constellation_beta in ["Orion", "Lyra"]',
        ),
    ),
)
def test_renamed_descriptor_filtered_create_compiles_on_the_pinned_isolated_tenant(
    tenant: str,
    catalog: str,
    field: str,
    values: tuple[str, ...],
    count: int,
    endpoint: str,
    predicate: str,
) -> None:
    compiler = _pinned_compiler()
    try:
        snapshot = _snapshot(
            tenant=tenant,
            catalog=catalog,
            field=field,
            values=values,
            binding=compiler.toolchain_binding,
        )
        intent, source = _execute_filtered_collection(
            snapshot=snapshot,
            endpoint=endpoint,
            catalog=catalog,
            field=field,
            values=values,
            count=count,
        )
        catalog_ref = catalog.rsplit(".", 1)[-1]
        assert intent.family == "filtered_collection"
        assert f"take {count} from @{catalog_ref}" in source
        assert predicate in source
        assert "tipologia" not in source and "Film" not in source and "video" not in source

        result = compiler.compile_candidate(
            lease=OperationLease(
                session_id="s" * 43,
                client_id="descriptor-compiler-test",
                tenant_alias=tenant,
                capabilities=frozenset({"compile"}),
                snapshot=snapshot,
                cancellation=threading.Event(),
            ),
            source=source,
            filename=f"brain-drafts/{endpoint.rsplit('.', 1)[-1]}.metis",
            endpoint=endpoint,
        )
        assert result.receipt["status"] == result.receipt["compiler"]["status"] == "ok"
        assert result.manifest is not None and result.ir is not None
        assert result.receipt["candidate"]["source_sha256"] == canonical_sha256(source)
        variants = result.ir["variants"]
        assert len(variants) == 1, result.ir
        response = variants[0]
        # The pinned IR spells a block use `ref`; `block` is the input AST key.
        assert [use["ref"] for use in response["uses"]] == ["main"], result.ir
        assert [block["name"] for block in result.ir["blocks"]] == ["main"], result.ir
        assert result.ir["blocks"][0]["takes"], result.ir
    finally:
        compiler.close()
