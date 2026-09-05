from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_authority_provider_impl_v2 import (
    PinnedCreateV2AuthorityProvider,
)
from metis_model1.brain_create_authority_provider_v2 import (
    AskCreateV2Authority,
    PrivateCreateV2Basis,
    ReadyCreateV2Authority,
)
from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_plan_v2 import NodeGrant, initial_create_endpoint_skeleton
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import DialogueBinding, PrivateDialogueState
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_turns import TurnRequest

TOOLCHAIN = bytes_sha256(b"production-toolchain")
SESSION_ID = "s" * 43


def _authorities(
    instruction: str | tuple[str, ...],
) -> tuple[
    OperationLease,
    TurnRequest,
    PrivateDialogueState,
    RetrievalResult,
]:
    source = b"catalog demo.video { fields { title text } }"
    source_hash = bytes_sha256(source)
    snapshot = ContextSnapshot(
        tenant_alias="demo",
        tenant_id="tenant-demo",
        root_device=1,
        root_inode=2,
        revision=bytes_sha256(b"context"),
        toolchain_binding=TOOLCHAIN,
        files=(SnapshotFile("catalogs/video.metis", source, source_hash),),
        total_bytes=len(source),
    )
    semantic = snapshot.semantic_source_revision()
    texts = (instruction,) if isinstance(instruction, str) else instruction
    history = tuple(
        CreateAuthorityHistoryMessage(index, text, bytes_sha256(text.encode()))
        for index, text in enumerate(texts)
    )
    binding = DialogueBinding(
        context_revision=snapshot.revision,
        semantic_revision=semantic,
        toolchain_binding=TOOLCHAIN,
        history_revision=create_authority_history_revision(history),
        parent_fingerprint=bytes_sha256(b"parent"),
    )
    dialogue = PrivateDialogueState(
        conversation_id=bytes_sha256(b"conversation"),
        binding=binding,
        messages=history,
    )
    request = TurnRequest(
        schema_version=2,
        request_id="request-0001",
        expected_context_revision=snapshot.revision,
        expected_semantic_source_revision=semantic,
        intent="create",
        instruction=texts[-1],
        target={
            "mode": "create",
            "relative_path": "brain-drafts/demo.metis",
            "endpoint": "demo.endpoint",
            "base_sha256": None,
            "reference": None,
        },
        basis=None,
        clarification_response=None,
        server_dialogue=dialogue,
    )
    lease = OperationLease(
        session_id=SESSION_ID,
        client_id="visix",
        tenant_alias="demo",
        capabilities=frozenset({"create"}),
        snapshot=snapshot,
        cancellation=threading.Event(),
    )
    retrieved = RetrievalResult(
        context={
            "context_revision": snapshot.revision,
            "semantic_source_revision": semantic,
            "toolchain_binding": TOOLCHAIN,
        },
        grounding={"status": "unsupported", "catalogs": [], "selections": []},
        semantic_source_revision=semantic,
    )
    return lease, request, dialogue, retrieved


def _provider() -> PinnedCreateV2AuthorityProvider:
    return PinnedCreateV2AuthorityProvider(hmac_key=b"p" * 32, toolchain_binding=TOOLCHAIN)


def test_exact_code_owned_capability_yields_canonical_generation_zero_authority() -> None:
    lease, request, dialogue, retrieved = _authorities("Abilita l'ora corrente")

    result = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(result) is ReadyCreateV2Authority
    assert result.generation == 0
    assert result.base_spec["endpoint"]["needs_time"] is False
    nodes = tuple(item for item in result.projection.authorities if type(item) is NodeGrant)
    assert len(nodes) == 1
    assert nodes[0].fragment is True


def test_explicit_ambiguity_yields_one_bounded_host_question() -> None:
    lease, request, dialogue, retrieved = _authorities("Configura l'ora corrente")

    result = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(result) is AskCreateV2Authority
    assert len(result.slots) == 1
    assert result.slots[0].answer_kind == "option_ref"
    assert len(result.slots[0].choices) == 2
    assert result.slots[0].question_ref is None


@pytest.mark.parametrize(
    "instruction",
    (
        "Crea un endpoint di film italiani",
        "Abilita l'ora corrente e aggiungi una fallback",
        "Abilita l'ora corrente nel catalogo video",
    ),
)
def test_unknown_or_mixed_structure_fails_closed(instruction: str) -> None:
    lease, request, dialogue, retrieved = _authorities(instruction)

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
    assert caught.value.status == 422


def test_session_mismatch_fails_before_ref_issue() -> None:
    lease, request, dialogue, retrieved = _authorities("Abilita l'ora corrente")

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id="t" * 43,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_STALE"


def test_refinement_is_bound_to_the_exact_private_basis() -> None:
    first = "Abilita l'ora corrente"
    lease, request, dialogue, retrieved = _authorities((first, "Disabilita l'ora corrente"))
    spec = initial_create_endpoint_skeleton("demo.endpoint")
    spec["endpoint"]["needs_time"] = True
    ir = {"kind": "Endpoint", "name": "demo.endpoint", "needs_time": True}
    first_message = dialogue.messages[:1]
    basis = PrivateCreateV2Basis(
        spec=spec,
        spec_sha256=canonical_sha256(spec),
        ir=ir,
        ir_sha256=canonical_sha256(ir),
        proof=create_ir_stage_proof(None, ir),
        generation=0,
        history=first_message,
        history_revision=create_authority_history_revision(first_message),
        proposal_ref="proposal_parent_0001",
    )

    result = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=basis,
    )

    assert type(result) is ReadyCreateV2Authority
    assert result.generation == 1
    assert result.base_spec == spec
    assert result.parent_spec_sha256 == basis.spec_sha256
    assert result.parent_ir_sha256 == basis.ir_sha256
    assert result.basis_ref is not None
    node = next(item for item in result.projection.authorities if type(item) is NodeGrant)
    assert node.fragment is False


def test_reviewed_catalog_evidence_cannot_escape_the_partial_structural_boundary() -> None:
    lease, request, dialogue, retrieved = _authorities("Abilita l'ora corrente")
    semantic = lease.snapshot.semantic_source_revision()
    domain = {"kind": "inline", "size": 1}
    semantic_state = {"state": "reviewed"}
    selected = {
        "catalog": "demo.video",
        "field": "genre",
        "literal": "Film",
        "type": "keyword",
        "modifiers": [],
        "domain": domain,
    }
    retrieved = replace(
        retrieved,
        context={
            "semantic_schema": 2,
            "context_revision": lease.snapshot.revision,
            "semantic_source_revision": semantic,
            "toolchain_binding": TOOLCHAIN,
            "catalog": {"name": "demo.video", "semantic": semantic_state},
            "fields": [
                {
                    "name": "genre",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": domain,
                    "semantic": semantic_state,
                    "values": [{"literal": "Film", "semantic": semantic_state}],
                }
            ],
        },
        grounding={
            "status": "resolved",
            "catalogs": ["demo.video"],
            "selections": [selected],
            "resolutions": [
                {
                    "catalog": "demo.video",
                    "field": "genre",
                    "literal": "Film",
                    "review_state": "reviewed",
                }
            ],
            "candidates": [],
            "unresolved": [],
            "lookups": [],
            "lookup": None,
        },
    )

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
    assert "partial production provider" in caught.value.message
