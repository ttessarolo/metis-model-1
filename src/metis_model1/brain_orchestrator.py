"""Brain's bounded retrieval -> generation -> compile -> repair pipeline."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.brain_candidate_grounding import (
    candidate_grounding_diagnostic,
    candidate_target_diagnostic,
    source_endpoint_has_fallback,
    source_take_contract,
    take_contract,
)
from metis_model1.brain_clarifications import (
    DEFAULT_MAX_RESULT_COUNT,
    ClarificationChoice,
    ClarificationStore,
)
from metis_model1.brain_grounded_renderer import render_grounded_create
from metis_model1.brain_intent_ir import (
    BrainIntentCompiler,
    IntentCompileRequest,
    IntentCompileResult,
    IntentIR,
)
from metis_model1.brain_lossless_edit import render_lossless_existing
from metis_model1.brain_model_runtime import BrainModelRuntime, ModelCandidate, ModelRequest
from metis_model1.brain_output_contract import OutputRequestSurface, parse_output_request
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import BrainRetriever, RetrievalResult
from metis_model1.brain_sessions import SessionManager
from metis_model1.brain_turns import TurnRecord, TurnRequest


def _server_decision(request: TurnRequest, kind: str) -> Mapping[str, Any] | None:
    """Return the latest server-owned decision of ``kind`` for this request."""

    context = request.server_clarification
    if not isinstance(context, Mapping):
        return None
    decisions = context.get("decisions")
    if isinstance(decisions, Sequence) and not isinstance(decisions, (str, bytes)):
        for decision in reversed(decisions):
            if isinstance(decision, Mapping) and decision.get("kind") == kind:
                return decision
    return context if context.get("kind") == kind else None


def _current_server_decision(request: TurnRequest, kind: str) -> Mapping[str, Any] | None:
    """Return only the decision consumed by this turn.

    Historical decisions remain useful session memory, but a refinement's
    explicit output surface must not be overridden by an answer already
    incorporated into its proposal basis.  A top-level decision without the
    conversation roster is retained for direct/internal callers.
    """

    context = request.server_clarification
    if not isinstance(context, Mapping):
        return None
    current = context.get("current_decision")
    if isinstance(current, Mapping):
        return current if current.get("kind") == kind else None
    if "decisions" not in context and context.get("kind") == kind:
        return context
    return None


class BrainOrchestrator:
    def __init__(
        self,
        *,
        retriever: BrainRetriever,
        model: BrainModelRuntime,
        compiler: Any,
        clarifications: ClarificationStore | None = None,
        max_repairs: int = 2,
        intent_compiler: BrainIntentCompiler | None = None,
    ) -> None:
        if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
            raise BrainError("INVALID_CONFIG", 500, "repair budget is invalid")
        self._retriever = retriever
        self._model = model
        self._compiler = compiler
        self._clarifications = clarifications or ClarificationStore()
        self._max_repairs = max_repairs
        self._intent_compiler = intent_compiler

    def run(
        self,
        *,
        manager: SessionManager,
        session_id: str,
        token: str,
        request: TurnRequest,
        record: TurnRecord,
    ) -> dict[str, Any]:
        with manager.operation(
            session_id=session_id,
            token=token,
            capability="chat.turn",
            expected_revision=request.expected_context_revision,
        ) as lease:
            if record.cancellation.is_set() or lease.cancellation.is_set():
                raise BrainError("SESSION_REVOKED", 409, "turn was revoked")
            retrieval_started = time.monotonic()
            record.emit("retrieval.started", "retrieval_started", "Recupero contesto")
            with record.heartbeat_while(
                phase="retrieval_running", label="Recupero contesto in corso"
            ):
                retrieved = self._retriever.retrieve(lease=lease, request=request)
            self._check_semantic_revision(request, retrieved)
            record.emit(
                "retrieval.completed",
                "retrieval_completed",
                "Contesto recuperato",
                count=len(retrieved.context),
                duration_ms=max(0, int((time.monotonic() - retrieval_started) * 1000)),
            )
            request, retrieved = self._retry_with_flash(
                lease=lease,
                request=request,
                retrieved=retrieved,
                record=record,
            )
            record.request = request
            candidates = retrieved.catalog_candidates
            if len(candidates) > 1:
                selected = self._selected_catalog(request, retrieved)
                if selected is None:
                    record.emit(
                        "catalog.clarification_required",
                        "clarification_required",
                        "Serve una scelta di catalogo",
                        count=len(candidates),
                    )
                    return self._catalog_clarification(
                        session_id=session_id,
                        record=record,
                        request=request,
                        retrieved=retrieved,
                    )
                record.emit("catalog.auto_selected", "catalog_selected", "Catalogo confermato")
            elif len(candidates) == 1:
                record.emit("catalog.auto_selected", "catalog_selected", "Catalogo selezionato")
            elif not retrieved.grounding.get("catalogs"):
                return self._unsupported(record, request, retrieved)
            if retrieved.grounding.get("status") == "clarify" and retrieved.grounding.get(
                "candidates"
            ):
                return self._semantic_clarification(
                    session_id=session_id,
                    record=record,
                    request=request,
                    retrieved=retrieved,
                )
            if retrieved.grounding.get("status") not in {None, "resolved"}:
                return self._unsupported(record, request, retrieved)

            snapshot_previous = lease.snapshot.source_map().get(request.target["relative_path"])
            previous = record.basis_source if record.basis_source is not None else snapshot_previous
            output_clarification = self._prepare_output_contract(
                session_id=session_id,
                record=record,
                request=request,
                retrieved=retrieved,
                previous_source=previous,
            )
            if output_clarification is not None:
                return output_clarification

            inference_started = time.monotonic()
            record.emit(
                "inference.started",
                "inference_started",
                "Preparazione locale del draft",
            )
            with record.heartbeat_while(
                phase="inference_running",
                label="Verifica lossless del compilatore in corso",
            ):
                lossless = render_lossless_existing(
                    compiler=self._compiler,
                    lease=lease,
                    request=request,
                    grounding=retrieved.grounding,
                    source=previous,
                )
            lossless_proof = lossless.proof if lossless is not None else None
            if lossless is not None:
                candidate = lossless.candidate
            else:
                model_request = ModelRequest(
                    instruction=request.instruction,
                    intent=request.intent,
                    target_path=request.target["relative_path"],
                    endpoint=request.target["endpoint"],
                    context=retrieved.context,
                    grounding=retrieved.grounding,
                    reference=request.target.get("reference"),
                    previous_source=previous,
                    cancellation=record.cancellation,
                )
                candidate = render_grounded_create(
                    request=request,
                    retrieved=retrieved,
                    model_revision=str(getattr(self._model, "model_revision", "unavailable")),
                    adapter_sha256=str(getattr(self._model, "adapter_sha256", "unavailable")),
                )
                if candidate is None:
                    with record.heartbeat_while(
                        phase="inference_running", label="Model 1 sta preparando il draft"
                    ):
                        candidate = self._generate(model_request)
            record.emit(
                "inference.completed",
                "inference_completed",
                "Candidato ricevuto",
                bytes=len(candidate.source.encode()),
                duration_ms=max(0, int((time.monotonic() - inference_started) * 1000)),
            )

            diagnostics: list[dict[str, Any]] = []
            compile_receipt: dict[str, Any] | None = None
            attempts = 0
            repairs_used = 0
            while True:
                if record.cancellation.is_set() or lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "turn was revoked")
                grounding_diagnostic = candidate_target_diagnostic(
                    candidate.source, request.target
                ) or candidate_grounding_diagnostic(candidate.source, retrieved.grounding)
                if grounding_diagnostic is not None:
                    if candidate.generator == "lossless_renderer":
                        raise BrainError(
                            "LOSSLESS_INVALID",
                            503,
                            "lossless candidate differs from reviewed grounding",
                        )
                    if repairs_used >= self._max_repairs:
                        diagnostic_code = grounding_diagnostic.get("code")
                        if diagnostic_code not in {
                            "CANDIDATE_GROUNDING_MISMATCH",
                            "CANDIDATE_TARGET_MISMATCH",
                        }:
                            diagnostic_code = "CANDIDATE_GROUNDING_MISMATCH"
                        raise BrainError(
                            diagnostic_code,
                            422,
                            "candidate does not match the requested target and reviewed grounding",
                        )
                    repairs_used += 1
                    record.emit(
                        "repair.started",
                        "repair_started",
                        "Correzione delimitata della selezione",
                        attempt=repairs_used,
                    )
                    repair_request = ModelRequest(
                        instruction=request.instruction,
                        intent=request.intent,
                        target_path=request.target["relative_path"],
                        endpoint=request.target["endpoint"],
                        context=retrieved.context,
                        grounding=retrieved.grounding,
                        reference=request.target.get("reference"),
                        previous_source=candidate.source,
                        diagnostics=(grounding_diagnostic,),
                        cancellation=record.cancellation,
                    )
                    repair_started = time.monotonic()
                    with record.heartbeat_while(
                        phase="repair_running", label="Correzione verificata in corso"
                    ):
                        candidate = self._generate(repair_request)
                    record.emit(
                        "repair.completed",
                        "repair_completed",
                        "Correzione della selezione ricevuta",
                        attempt=repairs_used,
                        duration_ms=max(0, int((time.monotonic() - repair_started) * 1000)),
                    )
                    continue
                attempts += 1
                record.emit(
                    "compile.started",
                    "compile_started",
                    "Compilazione del candidato",
                    attempt=attempts,
                )
                compile_started = time.monotonic()
                try:
                    with record.heartbeat_while(
                        phase="compile_running", label="Validazione del compilatore in corso"
                    ):
                        compile_receipt = self._compiler.compile(
                            lease=lease,
                            source=candidate.source,
                            filename=request.target["relative_path"],
                            execution_mode=("endpoint" if request.target["endpoint"] else "source"),
                            endpoint=request.target["endpoint"],
                        )
                except BrainError:
                    raise
                except Exception as error:
                    raise BrainError("COMPILER_FAILED", 503, "compiler failed") from error
                status = compile_receipt.get("compiler", compile_receipt).get("status")
                if status == "ok":
                    record.emit(
                        "compile.completed",
                        "compile_completed",
                        "Compilazione riuscita",
                        attempt=attempts,
                        duration_ms=max(0, int((time.monotonic() - compile_started) * 1000)),
                    )
                    break
                diagnostics = self._diagnostics(compile_receipt)
                record.emit(
                    "compile.completed",
                    "compile_completed",
                    "Compilazione con diagnostica",
                    attempt=attempts,
                    duration_ms=max(0, int((time.monotonic() - compile_started) * 1000)),
                )
                if candidate.generator == "lossless_renderer":
                    raise BrainError(
                        "LOSSLESS_INVALID",
                        503,
                        "lossless candidate failed compiler validation",
                    )
                if repairs_used >= self._max_repairs:
                    break
                repairs_used += 1
                record.emit(
                    "repair.started",
                    "repair_started",
                    "Correzione delimitata",
                    attempt=repairs_used,
                )
                repair_request = ModelRequest(
                    instruction=request.instruction,
                    intent=request.intent,
                    target_path=request.target["relative_path"],
                    endpoint=request.target["endpoint"],
                    context=retrieved.context,
                    grounding=retrieved.grounding,
                    reference=request.target.get("reference"),
                    previous_source=candidate.source,
                    diagnostics=tuple(diagnostics[:32]),
                    cancellation=record.cancellation,
                )
                repair_started = time.monotonic()
                with record.heartbeat_while(
                    phase="repair_running", label="Correzione verificata in corso"
                ):
                    candidate = self._generate(repair_request)
                record.emit(
                    "repair.completed",
                    "repair_completed",
                    "Correzione ricevuta",
                    attempt=repairs_used,
                    duration_ms=max(0, int((time.monotonic() - repair_started) * 1000)),
                )

            if compile_receipt is None:
                raise BrainError("COMPILER_FAILED", 503, "compiler returned no receipt")
            compiler_result = compile_receipt.get("compiler", compile_receipt)
            if not isinstance(compiler_result, dict) or compiler_result.get("status") != "ok":
                raise BrainError(
                    "COMPILER_REJECTED",
                    422,
                    "candidate remains invalid after bounded repair",
                )
            result = self._proposal(
                record=record,
                request=request,
                retrieved=retrieved,
                candidate=candidate,
                receipt=compile_receipt,
                attempts=attempts,
                previous=previous,
                diagnostics=diagnostics,
                lossless_proof=lossless_proof,
            )
            proposal = result.get("proposal")
            if request.server_clarification is not None and isinstance(proposal, Mapping):
                self._clarifications.set_latest_proposal(
                    session_id=session_id,
                    request_fingerprint=record.conversation_id or request.request_fingerprint,
                    proposal_ref=proposal["proposal_ref"],
                )
            return result

    def _retry_with_flash(
        self,
        *,
        lease: Any,
        request: TurnRequest,
        retrieved: RetrievalResult,
        record: TurnRecord,
    ) -> tuple[TurnRequest, RetrievalResult]:
        """Retry unresolved retrieval with validated exact operator spans only."""

        if self._intent_compiler is None or retrieved.grounding.get("status") != "unsupported":
            return request, retrieved
        compile_request = IntentCompileRequest(
            instruction=request.instruction,
            intent=request.intent,
            target_mode=request.target["mode"],
            cancellation=record.cancellation,
        )
        started = time.monotonic()
        server_value = request.server_flash_intent
        if server_value is None:
            record.emit(
                "intent.started",
                "intent_started",
                "Interpreto i requisiti non risolti",
            )
            try:
                with record.heartbeat_while(
                    phase="intent_running", label="Interpretazione locale in corso"
                ):
                    compiled = self._intent_compiler.compile(compile_request)
            except BrainError:
                raise
            except Exception as error:
                raise BrainError(
                    "FLASH_COMPILER_FAILED", 503, "local Flash intent compilation failed"
                ) from error
            if not isinstance(compiled, IntentCompileResult):
                raise BrainError(
                    "FLASH_COMPILER_INVALID", 503, "local Flash intent compiler is invalid"
                )
            intent_ir = compiled.intent_ir
            server_value = {
                "schema_version": 1,
                "intent_ir": intent_ir.payload(),
                "model_revision": compiled.model_revision,
                "schema_sha256": compiled.schema_sha256,
                "decoder": compiled.decoder,
            }
            replayed = False
        else:
            record.emit(
                "intent.started",
                "intent_started",
                "Riprendo l'interpretazione della sessione",
                replayed=True,
            )
            intent_ir = self._validated_server_intent(server_value, compile_request)
            replayed = True
        semantic_instruction = intent_ir.exact_semantic_instruction
        record.emit(
            "intent.completed",
            "intent_completed",
            (
                "Interpretazione delimitata pronta"
                if semantic_instruction is not None
                else "Interpretazione non applicabile in sicurezza"
            ),
            count=len(intent_ir.value["concepts"]),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            replayed=replayed,
        )
        if semantic_instruction is None:
            return request, retrieved
        request = request.with_server_flash_intent(server_value)
        retry_started = time.monotonic()
        record.emit(
            "retrieval.started",
            "retrieval_retry_started",
            "Riprovo il grounding sui requisiti esatti",
        )
        with record.heartbeat_while(
            phase="retrieval_running", label="Grounding delimitato in corso"
        ):
            retried = self._retriever.retrieve(lease=lease, request=request)
        self._check_semantic_revision(request, retried)
        record.emit(
            "retrieval.completed",
            "retrieval_retry_completed",
            "Grounding delimitato completato",
            count=len(retried.context),
            duration_ms=max(0, int((time.monotonic() - retry_started) * 1000)),
        )
        return request, retried

    def _validated_server_intent(
        self, value: Mapping[str, Any], request: IntentCompileRequest
    ) -> IntentIR:
        if (
            set(value)
            != {
                "schema_version",
                "intent_ir",
                "model_revision",
                "schema_sha256",
                "decoder",
            }
            or value.get("schema_version") != 1
        ):
            raise BrainError("FLASH_INTENT_STALE", 409, "session Flash intent is invalid")
        expected = {
            "model_revision": getattr(self._intent_compiler, "model_revision", None),
            "schema_sha256": getattr(self._intent_compiler, "schema_sha256", None),
            "decoder": getattr(self._intent_compiler, "decoder", None),
        }
        if any(value.get(key) != item for key, item in expected.items()):
            raise BrainError("FLASH_INTENT_STALE", 409, "session Flash intent identity differs")
        try:
            return IntentIR.parse(value["intent_ir"], request=request)
        except BrainError as error:
            raise BrainError(
                "FLASH_INTENT_STALE", 409, "session Flash intent is invalid"
            ) from error

    @staticmethod
    def _check_semantic_revision(request: TurnRequest, retrieved: RetrievalResult) -> None:
        if retrieved.semantic_source_revision != request.expected_semantic_source_revision:
            raise BrainError("SEMANTIC_SOURCE_STALE", 409, "semantic source revision differs")

    def _generate(self, request: ModelRequest) -> ModelCandidate:
        try:
            value = self._model.generate(request)
        except BrainError:
            raise
        except Exception as error:
            raise BrainError("MODEL_FAILED", 503, "local model generation failed") from error
        if isinstance(value, ModelCandidate):
            return value
        if isinstance(value, str):
            return ModelCandidate(
                value,
                str(getattr(self._model, "model_revision", "unavailable")),
                str(getattr(self._model, "adapter_sha256", "unavailable")),
            )
        if isinstance(value, dict) and isinstance(value.get("source"), str):
            return ModelCandidate(
                value["source"],
                str(
                    value.get(
                        "model_revision", getattr(self._model, "model_revision", "unavailable")
                    )
                ),
                str(
                    value.get(
                        "adapter_sha256", getattr(self._model, "adapter_sha256", "unavailable")
                    )
                ),
            )
        raise BrainError("MODEL_INVALID", 503, "local model returned an invalid candidate")

    @staticmethod
    def _selected_catalog(
        request: TurnRequest, retrieved: RetrievalResult
    ) -> dict[str, str] | None:
        clarification = _server_decision(request, "catalog")
        if clarification is None:
            return None
        selected_value = clarification.get("resolved_value")
        for item in retrieved.catalog_candidates:
            if item.get("option_ref") == selected_value or item.get("catalog") == selected_value:
                return item
        raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "catalog option is unavailable")

    @staticmethod
    def _grounding(retrieved: RetrievalResult) -> dict[str, Any]:
        value = dict(retrieved.grounding)
        value["semantic_source_revision"] = retrieved.semantic_source_revision
        value.setdefault("resolutions", [])
        value.setdefault("unresolved", [])
        return value

    def _clarification_terminal(
        self,
        *,
        session_id: str,
        record: TurnRecord,
        request: TurnRequest,
        retrieved: RetrievalResult,
        kind: str,
        question: str,
        question_key: str,
        options: Sequence[ClarificationChoice] = (),
        min_value: int = 1,
        max_value: int = 1000,
        assumptions: Sequence[str] = (),
    ) -> dict[str, Any]:
        pending = self._clarifications.create_pending(
            session_id=session_id,
            parent_turn_id=record.turn_id,
            request_fingerprint=request.request_fingerprint,
            context_revision=request.expected_context_revision,
            semantic_source_revision=request.expected_semantic_source_revision,
            kind=kind,
            question=question,
            question_key=question_key,
            options=options,
            min_value=min_value,
            max_value=max_value,
            assumptions=assumptions,
            conversation_key=record.conversation_id or request.request_fingerprint,
        )
        memory = self._clarifications.conversation(
            session_id=session_id,
            request_fingerprint=record.conversation_id or request.request_fingerprint,
        ).payload()
        return {
            "schema_version": request.schema_version,
            "turn_id": record.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "outcome": "needs_clarification",
            "route": "local",
            "clarification": pending.payload(),
            "session_memory": memory,
            "identity": self._identity(record, retrieved),
            "grounding": self._grounding(retrieved),
            "claims": {
                "compile_clean": None,
                "semantic_grounded": False,
                "semantic_correctness": False,
                "tenant_modified": False,
            },
        }

    def _catalog_clarification(
        self,
        *,
        session_id: str,
        record: TurnRecord,
        request: TurnRequest,
        retrieved: RetrievalResult,
    ) -> dict[str, Any]:
        if len(retrieved.catalog_candidates) > 5:
            raise BrainError(
                "CLARIFICATION_TOO_MANY_OPTIONS",
                409,
                "catalog ambiguity exceeds the interactive option bound",
            )
        options: list[ClarificationChoice] = []
        for item in retrieved.catalog_candidates:
            catalog = item.get("catalog", "")
            options.append(
                ClarificationChoice(
                    label=item.get("label", catalog),
                    value=catalog,
                    description=item.get("description", "Catalogo autorizzato"),
                    catalog=catalog,
                )
            )
        return self._clarification_terminal(
            session_id=session_id,
            record=record,
            request=request,
            retrieved=retrieved,
            kind="catalog",
            question="Quale catalogo vuoi usare?",
            question_key="catalog-selection",
            options=options,
        )

    def _semantic_clarification(
        self,
        *,
        session_id: str,
        record: TurnRecord,
        request: TurnRequest,
        retrieved: RetrievalResult,
    ) -> dict[str, Any]:
        candidates = [
            item for item in retrieved.grounding.get("candidates", []) if isinstance(item, Mapping)
        ]
        if not candidates:
            return self._unsupported(record, request, retrieved)
        clause = candidates[0].get("clause")
        clause_ref = candidates[0].get("clause_ref")
        same_clause = [
            item
            for item in candidates
            if not isinstance(clause_ref, str) or item.get("clause_ref") == clause_ref
        ]
        if len(same_clause) < 2:
            return self._unsupported(record, request, retrieved)
        if len(same_clause) > 5:
            raise BrainError(
                "CLARIFICATION_TOO_MANY_OPTIONS",
                409,
                "semantic ambiguity exceeds the interactive option bound",
            )
        option_refs = [item.get("option_ref") for item in same_clause]
        if any(not isinstance(item, str) or not item for item in option_refs) or len(
            set(option_refs)
        ) != len(option_refs):
            raise BrainError(
                "RETRIEVAL_INVALID", 409, "semantic clarification candidates are not distinct"
            )
        options = [
            ClarificationChoice(
                label=str(item.get("label", item.get("field", "Significato Metis"))),
                value=str(item.get("option_ref", "")),
                description=str(item.get("description", "Significato verificato nel catalogo")),
            )
            for item in same_clause
        ]
        surface = clause if isinstance(clause, str) and clause else request.instruction[:120]
        return self._clarification_terminal(
            session_id=session_id,
            record=record,
            request=request,
            retrieved=retrieved,
            kind="semantic_choice",
            question=f"Che cosa intendi con «{surface}»?",
            question_key="semantic-"
            + canonical_sha256(
                {
                    "clause_ref": clause_ref,
                    "options": sorted(str(item) for item in option_refs),
                }
            )[7:39],
            options=options,
        )

    def _prepare_output_contract(
        self,
        *,
        session_id: str,
        record: TurnRecord,
        request: TurnRequest,
        retrieved: RetrievalResult,
        previous_source: str | None = None,
    ) -> dict[str, Any] | None:
        # Schema 1 clients can answer only option_ref clarifications.  Preserve
        # their legacy non-interactive cardinality path instead of emitting a
        # result_count question they cannot represent.  Native interactive
        # cardinality and total-vs-page negotiation are a schema 2 contract.
        if request.schema_version != 2 or retrieved.context.get("semantic_schema") != 2:
            return None
        output_request = retrieved.output_request or parse_output_request(request.instruction)
        if (
            not isinstance(output_request, OutputRequestSurface)
            or output_request.instruction != request.instruction
        ):
            raise BrainError(
                "RETRIEVAL_INVALID", 409, "output request is not bound to the instruction"
            )
        if output_request.invalid_numeric_pagination or output_request.invalid_numeric_output:
            raise BrainError(
                "OUTPUT_CONTRACT_INVALID",
                422,
                "numeric pagination request is invalid",
            )
        basis_output = (
            request.server_basis_grounding.get("output_contract")
            if isinstance(request.server_basis_grounding, Mapping)
            else None
        )
        if isinstance(basis_output, Mapping):
            basis_fallback = basis_output.get("fallback")
            if basis_fallback is not None and (
                not isinstance(basis_fallback, Mapping) or dict(basis_fallback) != {"mode": "none"}
            ):
                raise BrainError(
                    "OUTPUT_CONTRACT_UNAVAILABLE",
                    422,
                    "proposal fallback cannot be preserved safely",
                )
        elif request.target["mode"] == "existing":
            endpoint = request.target.get("endpoint")
            if previous_source is None or not isinstance(endpoint, str):
                raise BrainError(
                    "OUTPUT_CONTRACT_UNAVAILABLE",
                    422,
                    "target endpoint fallback is unavailable",
                )
            if source_endpoint_has_fallback(previous_source, endpoint):
                raise BrainError(
                    "OUTPUT_CONTRACT_UNAVAILABLE",
                    422,
                    "target endpoint fallback cannot be preserved safely",
                )
        shape_decision = _current_server_decision(request, "response_shape")
        if shape_decision is not None:
            resolved = shape_decision.get("resolved_value")
            matched = re.fullmatch(r"(count|page):([1-9][0-9]{0,3})", str(resolved))
            if matched is None:
                raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "output shape is unavailable")
            count = int(matched.group(2))
            if count > DEFAULT_MAX_RESULT_COUNT:
                raise BrainError(
                    "RESULT_COUNT_OUT_OF_RANGE", 422, "result count exceeds the safe bound"
                )
            if matched.group(1) == "count":
                retrieval_take = {
                    "mode": "count",
                    "value": count,
                    "source": "operator_confirmed",
                }
                assumptions = [f"Numero complessivo confermato: {count} risultati."]
            else:
                retrieval_take = {
                    "mode": "page",
                    "page_size": {
                        "mode": "local_default",
                        "value": count,
                        "source": "operator_confirmed",
                    },
                }
                assumptions = [f"Paginazione confermata: {count} risultati per pagina."]
        decision = _current_server_decision(request, "result_count")
        if shape_decision is not None:
            pass
        elif decision is not None:
            answer = decision.get("answer")
            count = answer.get("integer") if isinstance(answer, Mapping) else None
            if type(count) is not int or not 1 <= count <= DEFAULT_MAX_RESULT_COUNT:
                raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "result count is unavailable")
            retrieval_take = {
                "mode": "count",
                "value": count,
                "source": "operator_confirmed",
            }
            assumptions = [f"Numero complessivo confermato dall'operatore: {count} risultati."]
        else:
            explicit_contracts = list(output_request.contracts)
            if any(count > DEFAULT_MAX_RESULT_COUNT for _mode, count in explicit_contracts):
                raise BrainError(
                    "RESULT_COUNT_OUT_OF_RANGE",
                    422,
                    "result count exceeds the safe bound",
                )
            generic_pagination = output_request.generic_pagination
            if len(explicit_contracts) > 1:
                if generic_pagination and all(
                    mode == "count" for mode, _count in explicit_contracts
                ):
                    raise BrainError(
                        "OUTPUT_CONTRACT_AMBIGUOUS",
                        422,
                        "multiple cardinalities cannot be bound to pagination",
                    )
                if len(explicit_contracts) > 5:
                    raise BrainError(
                        "CLARIFICATION_TOO_MANY_OPTIONS",
                        409,
                        "output ambiguity exceeds the interactive option bound",
                    )
                options = tuple(
                    ClarificationChoice(
                        label=(
                            f"{count} risultati complessivi"
                            if mode == "count"
                            else f"{count} risultati per pagina"
                        ),
                        value=f"{mode}:{count}",
                        description=(
                            f"Genera `take {count}` senza paginazione."
                            if mode == "count"
                            else f"Genera `take page default {count}`."
                        ),
                    )
                    for mode, count in explicit_contracts
                )
                return self._clarification_terminal(
                    session_id=session_id,
                    record=record,
                    request=request,
                    retrieved=retrieved,
                    kind="response_shape",
                    question="Hai indicato più cardinalità: quale vuoi applicare?",
                    question_key="output-contracts-"
                    + canonical_sha256({"contracts": explicit_contracts})[7:39],
                    options=options,
                )
            if len(explicit_contracts) == 1:
                mode, count = explicit_contracts[0]
            else:
                mode, count = None, None
            if mode == "page":
                retrieval_take = {
                    "mode": "page",
                    "page_size": {
                        "mode": "local_default",
                        "value": count,
                        "source": "operator_confirmed",
                    },
                }
                assumptions = [f"Paginazione richiesta: {count} risultati per pagina."]
            elif generic_pagination and mode == "count":
                return self._clarification_terminal(
                    session_id=session_id,
                    record=record,
                    request=request,
                    retrieved=retrieved,
                    kind="response_shape",
                    question=f"Il numero {count} indica il totale o i risultati per pagina?",
                    question_key=f"count-pagination-{count}",
                    options=(
                        ClarificationChoice(
                            label=f"{count} risultati complessivi",
                            value=f"count:{count}",
                            description=f"Genera `take {count}` senza paginazione.",
                        ),
                        ClarificationChoice(
                            label=f"{count} risultati per pagina",
                            value=f"page:{count}",
                            description=f"Genera `take page default {count}`.",
                        ),
                    ),
                )
            elif generic_pagination:
                retrieval_take = {
                    "mode": "page",
                    "page_size": {"mode": "tenant"},
                }
                assumptions = ["Paginazione richiesta; dimensione pagina ereditata dal tenant."]
            elif mode == "count":
                retrieval_take = {
                    "mode": "count",
                    "value": count,
                    "source": "operator_confirmed",
                }
                assumptions = [f"Numero complessivo richiesto: {count} risultati."]
            elif output_request.ambiguous_count:
                return self._clarification_terminal(
                    session_id=session_id,
                    record=record,
                    request=request,
                    retrieved=retrieved,
                    kind="result_count",
                    question="Quanti risultati complessivi vuoi?",
                    question_key="result-count",
                    min_value=1,
                    max_value=DEFAULT_MAX_RESULT_COUNT,
                )
            else:
                basis = request.server_basis_grounding
                prior_take = take_contract(basis) if isinstance(basis, Mapping) else None
                if prior_take is not None:
                    if prior_take.value is not None and prior_take.value > DEFAULT_MAX_RESULT_COUNT:
                        raise BrainError(
                            "RESULT_COUNT_OUT_OF_RANGE",
                            422,
                            "result count exceeds the safe bound",
                        )
                    output_contract = basis.get("output_contract")
                    raw_take = (
                        output_contract.get("take")
                        if isinstance(output_contract, Mapping)
                        else None
                    )
                    if not isinstance(raw_take, Mapping):
                        raise BrainError(
                            "GROUNDING_INVALID", 500, "grounding take contract is invalid"
                        )
                    if prior_take.mode == "count":
                        retrieval_take = {
                            "mode": "count",
                            "value": prior_take.value,
                            "source": raw_take["source"],
                        }
                        summary = f"{prior_take.value} risultati complessivi"
                    elif prior_take.value is None:
                        retrieval_take = {
                            "mode": "page",
                            "page_size": {"mode": "tenant"},
                        }
                        summary = "paginazione con dimensione del tenant"
                    else:
                        raw_page_size = raw_take.get("page_size")
                        if not isinstance(raw_page_size, Mapping):
                            raise BrainError(
                                "GROUNDING_INVALID",
                                500,
                                "grounding page contract is invalid",
                            )
                        retrieval_take = {
                            "mode": "page",
                            "page_size": {
                                "mode": "local_default",
                                "value": prior_take.value,
                                "source": raw_page_size["source"],
                            },
                        }
                        summary = f"paginazione da {prior_take.value} risultati"
                    assumptions = [
                        "Cardinalità mantenuta dalla proposta precedente della sessione: "
                        f"{summary}."
                    ]
                elif request.target["mode"] == "existing":
                    endpoint = request.target.get("endpoint")
                    if previous_source is None or not isinstance(endpoint, str):
                        raise BrainError(
                            "OUTPUT_CONTRACT_UNAVAILABLE",
                            422,
                            "target endpoint cardinality is unavailable",
                        )
                    existing_take = source_take_contract(previous_source, endpoint)
                    if (
                        existing_take.value is not None
                        and existing_take.value > DEFAULT_MAX_RESULT_COUNT
                    ):
                        raise BrainError(
                            "RESULT_COUNT_OUT_OF_RANGE",
                            422,
                            "result count exceeds the safe bound",
                        )
                    if existing_take.mode == "count":
                        retrieval_take = {
                            "mode": "count",
                            "value": existing_take.value,
                            "source": "existing_source",
                        }
                        summary = f"{existing_take.value} risultati complessivi"
                    elif existing_take.value is None:
                        retrieval_take = {
                            "mode": "page",
                            "page_size": {"mode": "tenant"},
                        }
                        summary = "paginazione con dimensione del tenant"
                    else:
                        retrieval_take = {
                            "mode": "page",
                            "page_size": {
                                "mode": "local_default",
                                "value": existing_take.value,
                                "source": "existing_source",
                            },
                        }
                        summary = f"paginazione da {existing_take.value} risultati"
                    assumptions = [
                        f"Cardinalità preservata dal sorgente fissato dell'endpoint: {summary}."
                    ]
                else:
                    return self._clarification_terminal(
                        session_id=session_id,
                        record=record,
                        request=request,
                        retrieved=retrieved,
                        kind="result_count",
                        question="Quanti risultati complessivi vuoi?",
                        question_key="result-count",
                        min_value=1,
                        max_value=DEFAULT_MAX_RESULT_COUNT,
                    )
        retrieved.grounding["output_contract"] = {
            "take": retrieval_take,
            "fallback": {"mode": "none"},
        }
        retrieved.grounding["assumptions"] = assumptions + [
            "Nessun fallback aggiunto senza una richiesta esplicita.",
        ]
        retrieved.context["output_contract"] = dict(retrieved.grounding["output_contract"])
        return None

    def _unsupported(
        self, record: TurnRecord, request: TurnRequest, retrieved: RetrievalResult
    ) -> dict[str, Any]:
        grounding = self._grounding(retrieved)
        if not grounding.get("unresolved"):
            grounding["unresolved"] = [request.instruction[:256]]
        return {
            "schema_version": request.schema_version,
            "turn_id": record.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "outcome": "unsupported_metadata",
            "route": "local",
            "grounding": grounding,
            "identity": self._identity(record, retrieved),
            "claims": {
                "compile_clean": None,
                "semantic_grounded": False,
                "semantic_correctness": False,
                "tenant_modified": False,
            },
        }

    @staticmethod
    def _diagnostics(receipt: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics = receipt.get("diagnostics")
        if diagnostics is None and isinstance(receipt.get("compiler"), dict):
            diagnostics = receipt["compiler"].get("diagnostics")
        if not isinstance(diagnostics, list):
            return []
        return [item for item in diagnostics[:32] if isinstance(item, dict)]

    def _identity(self, record: TurnRecord, retrieved: RetrievalResult) -> dict[str, Any]:
        identity: dict[str, Any] = {
            "model_revision": getattr(self._model, "model_revision", "unavailable"),
            "adapter_sha256": getattr(self._model, "adapter_sha256", "unavailable"),
            "context_revision": record.request.expected_context_revision,
            "semantic_source_revision": retrieved.semantic_source_revision,
            "toolchain_binding": "unknown",
        }
        intent = record.request.server_flash_intent
        if isinstance(intent, Mapping):
            identity["intent_compiler"] = {
                key: intent[key]
                for key in ("model_revision", "schema_sha256", "decoder")
                if isinstance(intent.get(key), str)
            }
        return identity

    @staticmethod
    def _session_memory(request: TurnRequest, grounding: Mapping[str, Any]) -> dict[str, Any]:
        conversation = (
            request.server_clarification.get("conversation")
            if isinstance(request.server_clarification, Mapping)
            else None
        )
        decisions = (
            [dict(item) for item in conversation.get("decisions", []) if isinstance(item, Mapping)]
            if isinstance(conversation, Mapping)
            else []
        )
        inherited = (
            [item for item in conversation.get("assumptions", []) if isinstance(item, str)]
            if isinstance(conversation, Mapping)
            else []
        )
        visible = [item for item in grounding.get("assumptions", []) if isinstance(item, str)]
        assumptions = list(dict.fromkeys(inherited + visible))[:8]
        return {
            "scope": "session",
            "persistent": False,
            "rounds_used": (
                conversation.get("rounds_used", 0) if isinstance(conversation, Mapping) else 0
            ),
            "max_rounds": 3,
            "decisions": decisions[:3],
            "assumptions": assumptions,
        }

    def _proposal(
        self,
        *,
        record: TurnRecord,
        request: TurnRequest,
        retrieved: RetrievalResult,
        candidate: Any,
        receipt: dict[str, Any],
        attempts: int,
        previous: str | None,
        diagnostics: list[dict[str, Any]],
        lossless_proof: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean = receipt.get("compiler", receipt).get("status") == "ok"
        source_hash = bytes_sha256(candidate.source.encode("utf-8"))
        proposal = {
            "proposal_ref": "proposal-" + secrets.token_urlsafe(24),
            "operation": "create" if request.target["mode"] == "create" else "replace",
            "relative_path": request.target["relative_path"],
            "endpoint": request.target["endpoint"],
            "reference": request.target.get("reference"),
            "base_sha256": request.target["base_sha256"],
            "source": candidate.source,
            "source_sha256": source_hash,
            "proposal_basis": {
                "context_revision": request.expected_context_revision,
                "semantic_source_revision": retrieved.semantic_source_revision,
            },
        }
        identity = self._identity(record, retrieved)
        identity["model_revision"] = candidate.model_revision
        identity["adapter_sha256"] = candidate.adapter_sha256
        identity["generation_strategy"] = candidate.generator
        if candidate.metrics:
            identity["generation_metrics"] = dict(candidate.metrics)
        toolchain = receipt.get("toolchain_binding")
        if isinstance(toolchain, str):
            identity["toolchain_binding"] = toolchain
        validation = {
            "status": "ok" if clean else "invalid",
            "diagnostics": diagnostics,
            "attempts": attempts,
            "compiler_receipt_sha256": receipt.get("receipt_sha256", "unavailable"),
            "compiled_endpoint_sha256": (
                receipt.get("compiler", {}).get("endpoint_sha256")
                if isinstance(receipt.get("compiler"), Mapping)
                else None
            ),
        }
        if lossless_proof is not None:
            expected_lossless_fields = {
                "contract",
                "proof_mode",
                "receipt_sha256",
                "sha_before",
                "sha_after",
                "touched_count",
            }
            if set(lossless_proof) != expected_lossless_fields:
                raise BrainError(
                    "LOSSLESS_INVALID",
                    503,
                    "public lossless proof has an invalid field roster",
                )
            validation["lossless"] = dict(lossless_proof)
        grounding = self._grounding(retrieved)
        semantically_grounded = (
            grounding.get("status") in {None, "resolved"}
            and not grounding.get("candidates")
            and not grounding.get("unresolved")
        )
        return {
            "schema_version": request.schema_version,
            "turn_id": record.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "outcome": "no_change" if previous == candidate.source else "proposed",
            "route": "local",
            "proposal": None if previous == candidate.source else proposal,
            "validation": validation,
            "grounding": grounding,
            "session_memory": self._session_memory(request, grounding),
            "identity": identity,
            "claims": {
                "compile_clean": clean,
                "semantic_grounded": semantically_grounded,
                "semantic_correctness": False,
                "tenant_modified": False,
            },
        }
