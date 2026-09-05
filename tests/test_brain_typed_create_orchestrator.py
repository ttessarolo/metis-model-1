"""Adversarial integration gate for the schema-2 typed CREATE route.

These tests deliberately use the real one-pass pipeline through
``BrainOrchestrator.run`` while every legacy generation, renderer, repair and
compiler route is a tripwire.  They are a host-boundary gate: a future routing
change cannot make typed CREATE silently fall back to whole-source generation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import pytest

import metis_model1.brain_orchestrator as orchestrator_module
from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_authority_provider_v2 import (
    AskCreateV2Authority,
    ReadyCreateV2Authority,
    UnavailableCreateV2AuthorityProvider,
    selected_catalogs_from_dialogue,
)
from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    FragmentLeafBinding,
    NodeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
    initial_create_endpoint_skeleton,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    BoundDecision,
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_model_runtime import CreatePlanV2Candidate
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import CandidateCompileResult
from metis_model1.brain_turns import TurnRecord, TurnRequest
from metis_model1.brain_typed_create_pipeline import TypedCreateV2RequestBinding

SESSION_ID = "s" * 43
TURN_ID = "t" * 24
ENDPOINT = "demo.typed_create"
FILENAME = "brain-drafts/typed-create.metis"
TOOLCHAIN = bytes_sha256(b"typed-orchestrator-toolchain")
SURFACE = bytes_sha256(b"typed-orchestrator-surface")
REQUIREMENT_REF = "hostref:typed-requirement"
EVIDENCE_REF = "hostref:typed-evidence"
TARGET_REF = "hostref:typed-target"
BASIS_REF = "hostref:typed-basis"
SLOT_REF = "hostref:typed-needs-time-slot"
NODE_REF = "hostref:typed-needs-time-value"


def _metrics() -> dict[str, Any]:
    return {
        "worker_load_ms": 1,
        "generation_ms": 2,
        "prompt_tokens": 12,
        "generation_tokens": 7,
        "cached_tokens": 0,
        "prompt_tps": 100.0,
        "generation_tps": 100.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }


def _snapshot() -> ContextSnapshot:
    raw = b"[tenant]\nid = 'typed-orchestrator'\n"
    snapshot_file = SnapshotFile("metis.toml", raw, bytes_sha256(raw))
    return ContextSnapshot(
        tenant_alias="demo",
        tenant_id="typed-orchestrator",
        root_device=1,
        root_inode=2,
        revision=bytes_sha256(b"typed-orchestrator-context"),
        toolchain_binding=TOOLCHAIN,
        files=(snapshot_file,),
        total_bytes=len(raw),
    )


def _lease(snapshot: ContextSnapshot) -> OperationLease:
    return OperationLease(
        session_id=SESSION_ID,
        client_id="visix",
        tenant_alias="demo",
        capabilities=frozenset({"chat.turn", "compile"}),
        snapshot=snapshot,
        cancellation=threading.Event(),
    )


class _Manager:
    def __init__(self, lease: OperationLease) -> None:
        self.lease = lease

    @contextmanager
    def operation(self, **_kwargs: Any):
        yield self.lease


def _history(*texts: str) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=index,
            text=text,
            message_sha256=bytes_sha256(text.encode("utf-8")),
        )
        for index, text in enumerate(texts)
    )


def _dialogue(
    snapshot: ContextSnapshot,
    *,
    choices: tuple[BoundChoice, ...] = (),
    target_key: str = "catalog.selection",
) -> PrivateDialogueState:
    history = _history("Crea un endpoint video con l'orario corrente.")
    semantic = snapshot.semantic_source_revision()
    binding = DialogueBinding(
        context_revision=snapshot.revision,
        semantic_revision=semantic,
        toolchain_binding=snapshot.toolchain_binding,
        history_revision=create_authority_history_revision(history),
        parent_fingerprint=bytes_sha256(b"typed-orchestrator-parent"),
    )
    decisions: tuple[BoundDecision, ...] = ()
    if choices:
        decisions = (
            BoundDecision(
                decision_key="catalog-choice",
                target_key=target_key,
                kind="catalog",
                question_ref="q_catalog",
                answer_kind="option_refs",
                binding=binding,
                choices=choices,
            ),
        )
    return PrivateDialogueState(
        conversation_id=bytes_sha256(b"typed-orchestrator-conversation"),
        binding=binding,
        messages=history,
        decisions=decisions,
    )


def _catalog_choice(
    *,
    authority_key: str = "catalog:demo.video",
    roles: tuple[str, ...] = ("catalog",),
) -> BoundChoice:
    return BoundChoice(
        label="Video",
        authority_keys=(authority_key,),
        candidate_revision=bytes_sha256(b"catalog-choice"),
        required_roles=roles,
        option_ref="opt_video",
    )


def _request(
    snapshot: ContextSnapshot,
    dialogue: PrivateDialogueState,
    *,
    basis: dict[str, str] | None = None,
) -> TurnRequest:
    return TurnRequest(
        schema_version=2,
        request_id="123e4567-e89b-12d3-a456-426614174000",
        expected_context_revision=snapshot.revision,
        expected_semantic_source_revision=snapshot.semantic_source_revision(),
        intent="create",
        instruction=dialogue.messages[-1].text,
        target={
            "mode": "create",
            "relative_path": FILENAME,
            "endpoint": ENDPOINT,
            "base_sha256": None,
            "reference": None,
        },
        basis=basis,
        clarification_response=None,
        server_dialogue=dialogue,
    )


def _record(request: TurnRequest) -> TurnRecord:
    return TurnRecord(TURN_ID, SESSION_ID, request, request.payload_hash)


def _projection(*, generation: int = 0) -> CompactAuthorityProjection:
    requirement = RequirementHandle(
        0,
        REQUIREMENT_REF,
        "Endpoint requires current time",
        frozenset({"set"}),
    )
    slot = SlotGrant(
        10,
        SLOT_REF,
        "Current time switch",
        TARGET_REF,
        "needs_time",
        "one",
        ("boolean",),
        frozenset({"set"}),
        "replace",
        None,
        generation,
    )
    node = NodeGrant(
        20,
        NODE_REF,
        "Enable current time",
        "new",
        "boolean",
        True,
        bytes_sha256(canonical_json(True)),
        (
            FragmentLeafBinding(
                "",
                EVIDENCE_REF,
                (REQUIREMENT_REF,),
                "operator",
            ),
        ),
        None,
        None,
        SLOT_REF,
        False,
    )
    authorities = (slot, node)
    return CompactAuthorityProjection(
        compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=(requirement,),
            authorities=authorities,
        ),
        SURFACE,
        (requirement,),
        authorities,
    )


def _binding(
    request: TurnRequest,
    dialogue: PrivateDialogueState,
    *,
    filename: str = FILENAME,
) -> TypedCreateV2RequestBinding:
    return TypedCreateV2RequestBinding(
        history=dialogue.messages,
        history_revision=dialogue.binding.history_revision,
        context_revision=request.expected_context_revision,
        semantic_revision=request.expected_semantic_source_revision,
        candidate_filename=filename,
        endpoint=ENDPOINT,
    )


def _ready(
    request: TurnRequest,
    dialogue: PrivateDialogueState,
    *,
    generation: int = 0,
    base_spec: dict[str, Any] | None = None,
    basis_ref: str | None = None,
    parent_spec_sha256: str | None = None,
    parent_ir: dict[str, Any] | None = None,
    parent_ir_sha256: str | None = None,
    filename: str = FILENAME,
) -> ReadyCreateV2Authority:
    return ReadyCreateV2Authority(
        binding=_binding(request, dialogue, filename=filename),
        projection=_projection(generation=generation),
        active_requirement_handles=(0,),
        base_spec=base_spec or initial_create_endpoint_skeleton(ENDPOINT),
        target_ref=TARGET_REF,
        basis_ref=basis_ref,
        generation=generation,
        parent_spec_sha256=parent_spec_sha256,
        parent_ir=parent_ir,
        parent_ir_sha256=parent_ir_sha256,
    )


def test_ready_authority_rejects_noncanonical_initial_base_before_orchestration() -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue)
    altered = initial_create_endpoint_skeleton(ENDPOINT)
    altered["endpoint"]["needs_time"] = True

    with pytest.raises(BrainError) as raised:
        _ready(request, dialogue, base_spec=altered)

    assert raised.value.code == "CREATE_TYPED_AUTHORITY_INVALID"


def test_schema2_create_with_unavailable_provider_fails_closed_instead_of_using_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue)
    record = _record(request)
    model = _Model()
    compiler = _Compiler()
    retriever = _Retriever(snapshot)
    monkeypatch.setattr(orchestrator_module, "render_grounded_create", _unexpected_legacy)
    monkeypatch.setattr(BrainOrchestrator, "_generate", _unexpected_legacy)
    monkeypatch.setattr(BrainOrchestrator, "_compile_candidate", _unexpected_legacy)

    with pytest.raises(BrainError) as raised:
        BrainOrchestrator(
            retriever=retriever,
            model=model,
            compiler=compiler,
            create_authority_provider=UnavailableCreateV2AuthorityProvider(),
        ).run(
            manager=_Manager(_lease(snapshot)),
            session_id=SESSION_ID,
            token="test-token",
            request=request,
            record=record,
        )

    assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNAVAILABLE"
    assert model.plan_v2_calls == model.plan_v1_calls == model.generate_calls == 0
    assert compiler.candidate_calls == compiler.legacy_calls == 0


class _Provider:
    def __init__(
        self, factory: Callable[..., AskCreateV2Authority | ReadyCreateV2Authority]
    ) -> None:
        self._factory = factory
        self.calls = 0
        self.calls_kwargs: list[dict[str, Any]] = []

    def prepare(self, **kwargs: Any) -> AskCreateV2Authority | ReadyCreateV2Authority:
        self.calls += 1
        self.calls_kwargs.append(kwargs)
        return self._factory(**kwargs)


class _Retriever:
    def __init__(self, snapshot: ContextSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0
        self.catalog_hints: list[tuple[str, ...]] = []

    def retrieve(self, *, lease: OperationLease, request: TurnRequest) -> RetrievalResult:
        assert lease.snapshot is self.snapshot
        self.calls += 1
        self.catalog_hints.append(request.server_target_catalogs)
        return RetrievalResult(
            context={"toolchain_binding": self.snapshot.toolchain_binding},
            grounding={
                "status": "resolved",
                "catalogs": ["demo.video"],
                "selections": [],
                "candidates": [],
                "unresolved": [],
                "resolutions": [],
            },
            semantic_source_revision=self.snapshot.semantic_source_revision(),
            catalog_candidates=({"catalog": "demo.video", "label": "Video"},),
        )


class _Model:
    def __init__(self, *, loaded: bool = True) -> None:
        self.model_loaded = loaded
        self.model_revision = "Qwen3.8-27B-test"
        self.adapter_sha256 = "adapter-test"
        self.plan_v2_calls = 0
        self.plan_v1_calls = 0
        self.generate_calls = 0

    def plan_create_v2(self, _request: Any) -> CreatePlanV2Candidate:
        self.plan_v2_calls += 1
        return CreatePlanV2Candidate(
            {"o": [{"k": "s", "q": [0], "s": 10, "v": 20}]},
            self.model_revision,
            self.adapter_sha256,
            metrics=_metrics(),
        )

    def plan_create(self, _request: Any) -> None:
        self.plan_v1_calls += 1
        raise AssertionError("legacy typed CREATE planner must not run")

    def generate(self, _request: Any) -> None:
        self.generate_calls += 1
        raise AssertionError("whole-source generation or repair must not run")


class _Compiler:
    def __init__(self) -> None:
        self.toolchain_binding = TOOLCHAIN
        self.candidate_calls = 0
        self.legacy_calls = 0

    def compile(self, **_kwargs: Any) -> None:
        self.legacy_calls += 1
        raise AssertionError("legacy compiler path must not run")

    def compile_candidate(
        self, *, lease: OperationLease, source: str, filename: str, endpoint: str
    ) -> CandidateCompileResult:
        self.candidate_calls += 1
        endpoint_sha256 = canonical_sha256({"endpoint": endpoint, "source": source})
        manifest = {
            "schema_version": 1,
            "endpoint": endpoint,
            "endpoint_sha256": endpoint_sha256,
            "containers": [{"path": "endpoint", "kind": "endpoint"}],
            "fetches": [],
        }
        ir = {
            "node": "Endpoint",
            "name": endpoint,
            "irVersion": "0.43",
            "needsTime": True,
        }
        compiler = {
            "schema_version": 1,
            "operation": "compile",
            "status": "ok",
            "diagnostics": [],
            "endpoint": endpoint,
            "endpoint_sha256": endpoint_sha256,
            "runtime_context_sha256": bytes_sha256(b"runtime-context"),
        }
        receipt_body = {
            "schema_version": 1,
            "status": "ok",
            "session_id": lease.session_id,
            "tenant_alias": lease.tenant_alias,
            "context_revision": lease.snapshot.revision,
            "toolchain_binding": self.toolchain_binding,
            "candidate": {
                "filename": filename,
                "execution_mode": "endpoint",
                "endpoint": endpoint,
                "source_sha256": canonical_sha256(source),
                "context_revision": lease.snapshot.revision,
            },
            "compiler": compiler,
            "claims": {
                "archive_snapshot": True,
                "network_denied": True,
                "writes_denied": True,
                "tenant_modified": False,
                "semantic_correctness": False,
            },
        }
        receipt = {**receipt_body, "receipt_sha256": canonical_sha256(receipt_body)}
        return CandidateCompileResult(
            receipt,
            manifest,
            canonical_sha256(manifest),
            ir,
            canonical_sha256(ir),
        )


def _run(
    *,
    snapshot: ContextSnapshot,
    request: TurnRequest,
    record: TurnRecord,
    provider: _Provider,
    retriever: _Retriever,
    model: _Model,
    compiler: _Compiler,
) -> dict[str, Any]:
    return BrainOrchestrator(
        retriever=retriever,
        model=model,
        compiler=compiler,
        create_authority_provider=provider,
    ).run(
        manager=_Manager(_lease(snapshot)),
        session_id=SESSION_ID,
        token="test-token",
        request=request,
        record=record,
    )


def _unexpected_legacy(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("typed CREATE entered a legacy route")


def test_typed_create_provider_question_needs_clarification_before_model_or_compiler() -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue)
    record = _record(request)
    model = _Model()
    compiler = _Compiler()
    provider = _Provider(
        lambda **_kwargs: AskCreateV2Authority(
            (
                QuestionSlot(
                    "result-count",
                    "response.total",
                    "result_count",
                    "Quanti risultati complessivi vuoi?",
                    "integer",
                    minimum=1,
                    maximum=200,
                    value_contract="total",
                ),
            )
        )
    )
    retriever = _Retriever(snapshot)

    terminal = _run(
        snapshot=snapshot,
        request=request,
        record=record,
        provider=provider,
        retriever=retriever,
        model=model,
        compiler=compiler,
    )

    assert terminal["schema_version"] == 2
    assert terminal["outcome"] == "needs_clarification"
    assert terminal["claims"]["compile_clean"] is None
    assert terminal["clarification"]["questions"][0]["kind"] == "result_count"
    assert provider.calls == 1
    assert model.plan_v2_calls == model.plan_v1_calls == model.generate_calls == 0
    assert compiler.candidate_calls == compiler.legacy_calls == 0
    assert record.candidate_create_spec is None
    assert record.candidate_create_ir is None


def test_typed_create_ready_is_one_plan_one_compile_draft_and_never_uses_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot, choices=(_catalog_choice(),))
    request = _request(snapshot, dialogue)
    record = _record(request)
    model = _Model()
    compiler = _Compiler()
    provider = _Provider(lambda **kwargs: _ready(kwargs["request"], kwargs["dialogue"]))
    retriever = _Retriever(snapshot)
    monkeypatch.setattr(orchestrator_module, "render_grounded_create", _unexpected_legacy)
    monkeypatch.setattr(orchestrator_module, "render_lossless_existing", _unexpected_legacy)
    monkeypatch.setattr(orchestrator_module, "render_structural_existing", _unexpected_legacy)
    monkeypatch.setattr(BrainOrchestrator, "_generate", _unexpected_legacy)
    monkeypatch.setattr(BrainOrchestrator, "_repair_grounding", _unexpected_legacy)
    monkeypatch.setattr(BrainOrchestrator, "_compile_candidate", _unexpected_legacy)

    terminal = _run(
        snapshot=snapshot,
        request=request,
        record=record,
        provider=provider,
        retriever=retriever,
        model=model,
        compiler=compiler,
    )

    assert terminal["outcome"] == "proposed"
    assert terminal["proposal"] is not None
    assert terminal["validation"]["status"] == "ok"
    assert terminal["validation"]["attempts"] == 1
    assert terminal["identity"]["generation_strategy"] == "model_create_plan_v2"
    assert retriever.catalog_hints == [("demo.video",)]
    assert provider.calls == 1
    assert model.plan_v2_calls == 1
    assert model.plan_v1_calls == model.generate_calls == 0
    assert compiler.candidate_calls == 1
    assert compiler.legacy_calls == 0
    assert record.candidate_create_generation == 0
    assert record.candidate_create_spec is not None
    assert record.candidate_create_ir is not None
    assert record.candidate_create_proof is not None
    assert record.candidate_manifest is not None
    assert "hostref:" not in canonical_json(terminal).decode("utf-8")


def test_typed_create_invalid_model_has_no_compile_and_no_draft() -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue)
    record = _record(request)
    model = _Model(loaded=False)
    compiler = _Compiler()
    provider = _Provider(lambda **kwargs: _ready(kwargs["request"], kwargs["dialogue"]))

    with pytest.raises(BrainError) as raised:
        _run(
            snapshot=snapshot,
            request=request,
            record=record,
            provider=provider,
            retriever=_Retriever(snapshot),
            model=model,
            compiler=compiler,
        )

    assert raised.value.code == "MODEL_UNAVAILABLE"
    assert model.plan_v2_calls == model.plan_v1_calls == model.generate_calls == 0
    assert compiler.candidate_calls == compiler.legacy_calls == 0
    assert record.candidate_create_spec is None
    assert record.candidate_create_ir is None
    assert record.candidate_manifest is None


def test_typed_create_provider_binding_drift_is_rejected_before_model() -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue)
    record = _record(request)
    model = _Model()
    compiler = _Compiler()
    provider = _Provider(
        lambda **kwargs: _ready(
            kwargs["request"], kwargs["dialogue"], filename="brain-drafts/drifted.metis"
        )
    )

    with pytest.raises(BrainError) as raised:
        _run(
            snapshot=snapshot,
            request=request,
            record=record,
            provider=provider,
            retriever=_Retriever(snapshot),
            model=model,
            compiler=compiler,
        )

    assert raised.value.code == "CREATE_TYPED_AUTHORITY_STALE"
    assert model.plan_v2_calls == model.plan_v1_calls == model.generate_calls == 0
    assert compiler.candidate_calls == compiler.legacy_calls == 0
    assert record.candidate_create_spec is None
    assert record.candidate_create_ir is None


def test_typed_create_refinement_binds_parent_and_attaches_only_private_stage_state() -> None:
    snapshot = _snapshot()
    dialogue = _dialogue(snapshot)
    request = _request(snapshot, dialogue, basis={"kind": "proposal", "proposal_ref": "base"})
    record = _record(request)
    base_spec = initial_create_endpoint_skeleton(ENDPOINT)
    parent_ir = {
        "node": "Endpoint",
        "name": ENDPOINT,
        "irVersion": "0.43",
        "needsTime": False,
    }
    parent_ir_sha256 = canonical_sha256(parent_ir)
    record.basis_create_spec = base_spec
    record.basis_create_spec_sha256 = canonical_sha256(base_spec)
    record.basis_create_ir = parent_ir
    record.basis_create_ir_sha256 = parent_ir_sha256
    record.basis_create_proof = create_ir_stage_proof(None, parent_ir)
    record.basis_create_generation = 0
    record.basis_create_history = dialogue.messages
    record.basis_create_history_revision = dialogue.binding.history_revision
    model = _Model()
    compiler = _Compiler()
    provider = _Provider(
        lambda **kwargs: _ready(
            kwargs["request"],
            kwargs["dialogue"],
            generation=1,
            base_spec=base_spec,
            basis_ref=BASIS_REF,
            parent_spec_sha256=canonical_sha256(base_spec),
            parent_ir=parent_ir,
            parent_ir_sha256=parent_ir_sha256,
        )
    )

    terminal = _run(
        snapshot=snapshot,
        request=request,
        record=record,
        provider=provider,
        retriever=_Retriever(snapshot),
        model=model,
        compiler=compiler,
    )

    assert terminal["outcome"] == "proposed"
    assert model.plan_v2_calls == 1
    assert compiler.candidate_calls == 1
    assert record.candidate_create_generation == 1
    assert record.candidate_create_history == dialogue.messages
    assert record.candidate_create_history_revision == dialogue.binding.history_revision
    assert record.candidate_create_spec_sha256 is not None
    assert record.candidate_create_ir_sha256 is not None
    assert record.candidate_create_proof is not None
    assert record.candidate_create_proof.parent_ir_sha256 == parent_ir_sha256
    assert record.candidate_create_spec is not record.basis_create_spec
    assert record.candidate_create_ir is not record.basis_create_ir


def test_selected_catalogs_accepts_only_exact_server_bound_catalog_choices() -> None:
    snapshot = _snapshot()
    exact = _dialogue(snapshot, choices=(_catalog_choice(),))
    assert selected_catalogs_from_dialogue(exact) == ("demo.video",)

    role_drift = _dialogue(snapshot, choices=(_catalog_choice(roles=("field",)),))
    with pytest.raises(BrainError) as bad_role:
        selected_catalogs_from_dialogue(role_drift)
    assert bad_role.value.code == "CREATE_TYPED_AUTHORITY_INVALID"

    key_drift = _dialogue(snapshot, choices=(_catalog_choice(authority_key="field:video"),))
    with pytest.raises(BrainError) as bad_key:
        selected_catalogs_from_dialogue(key_drift)
    assert bad_key.value.code == "CREATE_TYPED_AUTHORITY_INVALID"


def test_selected_catalogs_uses_only_the_latest_exact_replacement() -> None:
    snapshot = _snapshot()
    initial = _dialogue(snapshot, choices=(_catalog_choice(),)).decisions[0]
    replacement = BoundDecision(
        decision_key=initial.decision_key,
        target_key=initial.target_key,
        kind=initial.kind,
        question_ref="q_catalog_replacement",
        answer_kind="option_refs",
        binding=initial.binding,
        choices=(_catalog_choice(authority_key="catalog:demo.users"),),
        supersedes=initial.decision_sha256,
    )
    base = _dialogue(snapshot)
    dialogue = PrivateDialogueState(
        conversation_id=base.conversation_id,
        binding=base.binding,
        messages=base.messages,
        decisions=(initial, replacement),
    )

    assert selected_catalogs_from_dialogue(dialogue) == ("demo.users",)


@pytest.mark.parametrize("target_key", ("target.catalogs", "target.untrusted_catalogs"))
def test_selected_catalogs_rejects_legacy_or_untrusted_target_key_before_retrieval(
    target_key: str,
) -> None:
    snapshot = _snapshot()
    drifted = _dialogue(
        snapshot,
        choices=(_catalog_choice(),),
        target_key=target_key,
    )
    with pytest.raises(BrainError) as raised:
        selected_catalogs_from_dialogue(drifted)
    assert raised.value.code == "CREATE_TYPED_AUTHORITY_INVALID"
