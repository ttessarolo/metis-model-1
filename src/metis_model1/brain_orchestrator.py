"""Brain's bounded retrieval -> generation -> compile -> repair pipeline."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from metis_model1.brain_candidate_grounding import (
    adjudicate_candidate_manifest,
    adjudicate_manifest_preservation,
    candidate_grounding_diagnostic,
    candidate_target_diagnostic,
    source_endpoint_catalogs,
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
from metis_model1.brain_semantic_retrieval import (
    EXACT_REVIEWED_VALUE_AUTHORITY_CONTRACT,
)
from metis_model1.brain_sessions import SessionManager
from metis_model1.brain_structural_edit import (
    STRUCTURAL_LOSSLESS_PROOF_CONTRACT,
    STRUCTURAL_SEMANTIC_DELTA_CONTRACT,
    render_structural_existing,
    structural_edit_requested,
)
from metis_model1.brain_turns import TurnRecord, TurnRequest

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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
            snapshot_previous = lease.snapshot.source_map().get(request.target["relative_path"])
            previous = record.basis_source if record.basis_source is not None else snapshot_previous
            if request.target["mode"] == "existing":
                endpoint = request.target.get("endpoint")
                if previous is not None and isinstance(endpoint, str):
                    try:
                        target_catalogs = source_endpoint_catalogs(previous, endpoint)
                    except BrainError as error:
                        if error.code != "CATALOG_CONTEXT_UNAVAILABLE":
                            raise
                        target_catalogs = ()
                    request = request.with_server_target_catalogs(target_catalogs)
            structural_requested = request.target[
                "mode"
            ] == "existing" and structural_edit_requested(request.instruction)
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
            # The compiler-owned structural path consumes the complete operator
            # instruction against exact AST occurrences.  Flash must not rewrite
            # or reject that evidence before the structural ledger can judge it.
            if not structural_requested:
                request, retrieved = self._retry_with_flash(
                    lease=lease,
                    request=request,
                    retrieved=retrieved,
                    record=record,
                )
            record.request = request
            if not structural_requested:
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

            if structural_requested and request.basis is None:
                # The edit-surface + one-shot permit + validating lossless receipt
                # already bind the immutable baseline byte spans.  Avoid a separate
                # full baseline compile; the candidate compile below creates the
                # private manifest needed by a later proposal refinement.
                basis_manifest = None
            else:
                basis_manifest, _basis_manifest_sha256 = self._basis_manifest(
                    lease=lease,
                    request=request,
                    record=record,
                    previous_source=previous,
                )
            if not structural_requested:
                output_clarification = self._prepare_output_contract(
                    session_id=session_id,
                    record=record,
                    request=request,
                    retrieved=retrieved,
                    previous_source=previous,
                    basis_manifest=basis_manifest,
                )
                if output_clarification is not None:
                    return output_clarification

            inference_started = time.monotonic()
            record.emit(
                "inference.started",
                "inference_started",
                "Preparazione locale del draft",
            )
            reviewed_value_resolver = (
                getattr(self._retriever, "resolve_exact_reviewed_values", None)
                if structural_requested
                else None
            )
            if not callable(reviewed_value_resolver):
                reviewed_value_resolver = None
            with record.heartbeat_while(
                phase="inference_running",
                label="Verifica lossless del compilatore in corso",
            ):
                lossless = (
                    render_structural_existing(
                        compiler=self._compiler,
                        lease=lease,
                        request=request,
                        record=record,
                        grounding=retrieved.grounding,
                        source=previous,
                        reviewed_value_resolver=reviewed_value_resolver,
                    )
                    if structural_requested
                    else render_lossless_existing(
                        compiler=self._compiler,
                        lease=lease,
                        request=request,
                        grounding=retrieved.grounding,
                        source=previous,
                    )
                )
            if structural_requested and lossless is None:
                raise BrainError(
                    "STRUCTURAL_EDIT_UNRESOLVED",
                    422,
                    "structural edit could not be resolved exactly",
                )
            lossless_proof = lossless.proof if lossless is not None else None
            semantic_delta = lossless.semantic_delta if lossless is not None else None
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
            candidate_manifest: dict[str, Any] | None = None
            candidate_manifest_sha256: str | None = None
            attempts = 0
            repairs_used = 0
            while True:
                if record.cancellation.is_set() or lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "turn was revoked")
                endpoint = request.target.get("endpoint")
                compiled_manifest_path = isinstance(endpoint, str)
                if not compiled_manifest_path:
                    grounding_diagnostic = candidate_target_diagnostic(
                        candidate.source, request.target
                    ) or candidate_grounding_diagnostic(candidate.source, retrieved.grounding)
                    if grounding_diagnostic is not None:
                        candidate = self._repair_grounding(
                            candidate=candidate,
                            diagnostic=grounding_diagnostic,
                            request=request,
                            retrieved=retrieved,
                            record=record,
                            repairs_used=repairs_used,
                        )
                        repairs_used += 1
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
                        if compiled_manifest_path:
                            (
                                compile_receipt,
                                candidate_manifest,
                                candidate_manifest_sha256,
                            ) = self._compile_candidate(
                                lease=lease,
                                source=candidate.source,
                                filename=request.target["relative_path"],
                                endpoint=endpoint,
                            )
                        else:
                            compile_receipt = self._compiler.compile(
                                lease=lease,
                                source=candidate.source,
                                filename=request.target["relative_path"],
                                execution_mode="source",
                                endpoint=None,
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
                    if compiled_manifest_path:
                        if candidate_manifest is None or candidate_manifest_sha256 is None:
                            raise BrainError(
                                "COMPILER_FAILED", 503, "compiler returned no candidate manifest"
                            )
                        grounding_diagnostic = self._compiled_grounding_diagnostic(
                            candidate=candidate,
                            request=request,
                            grounding=retrieved.grounding,
                            candidate_manifest=candidate_manifest,
                            basis_manifest=basis_manifest,
                            lossless_proof=lossless_proof,
                        )
                        if grounding_diagnostic is not None:
                            candidate = self._repair_grounding(
                                candidate=candidate,
                                diagnostic=grounding_diagnostic,
                                request=request,
                                retrieved=retrieved,
                                record=record,
                                repairs_used=repairs_used,
                            )
                            repairs_used += 1
                            continue
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
            if candidate_manifest is not None:
                record.candidate_manifest = deepcopy(candidate_manifest)
                record.candidate_manifest_sha256 = candidate_manifest_sha256
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
                semantic_delta=semantic_delta,
            )
            proposal = result.get("proposal")
            if request.server_clarification is not None and isinstance(proposal, Mapping):
                self._clarifications.set_latest_proposal(
                    session_id=session_id,
                    request_fingerprint=record.conversation_id or request.request_fingerprint,
                    proposal_ref=proposal["proposal_ref"],
                )
            return result

    def _basis_manifest(
        self,
        *,
        lease: Any,
        request: TurnRequest,
        record: TurnRecord,
        previous_source: str | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Return private structural authority for a named endpoint.

        A proposal basis already owns the compiler manifest of the accepted
        candidate.  Recompiling that proposal would create a second authority
        observation and needlessly double the compiler cost, so the exact
        revision-bound manifest is reused.  A first edit of an existing source
        compiles that immutable source once before candidate generation.
        """

        endpoint = request.target.get("endpoint")
        if not isinstance(endpoint, str):
            return None, None
        if record.basis_manifest is not None:
            manifest, manifest_sha256 = self._validate_private_manifest(
                manifest=record.basis_manifest,
                manifest_sha256=record.basis_manifest_sha256,
                endpoint=endpoint,
            )
            return deepcopy(manifest), manifest_sha256
        if request.basis is not None:
            raise BrainError("PROPOSAL_STALE", 409, "proposal structural authority is unavailable")
        if request.target.get("mode") != "existing":
            return None, None
        if previous_source is None:
            raise BrainError("OUTPUT_CONTRACT_UNAVAILABLE", 422, "target source is unavailable")
        receipt, manifest, manifest_sha256 = self._compile_candidate(
            lease=lease,
            source=previous_source,
            filename=request.target["relative_path"],
            endpoint=endpoint,
        )
        status = receipt.get("compiler", receipt).get("status")
        if status != "ok" or manifest is None or manifest_sha256 is None:
            raise BrainError(
                "OUTPUT_CONTRACT_UNAVAILABLE",
                422,
                "target endpoint structural authority is unavailable",
            )
        record.basis_manifest = deepcopy(manifest)
        record.basis_manifest_sha256 = manifest_sha256
        return manifest, manifest_sha256

    def _compile_candidate(
        self,
        *,
        lease: Any,
        source: str,
        filename: str,
        endpoint: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
        compile_candidate = getattr(self._compiler, "compile_candidate", None)
        if not callable(compile_candidate):
            raise BrainError("COMPILER_FAILED", 503, "candidate compiler is unavailable")
        result = compile_candidate(
            lease=lease,
            source=source,
            filename=filename,
            endpoint=endpoint,
        )
        receipt = getattr(result, "receipt", None)
        manifest = getattr(result, "manifest", None)
        manifest_sha256 = getattr(result, "manifest_sha256", None)
        if not isinstance(receipt, dict):
            raise BrainError("COMPILER_FAILED", 503, "candidate compiler returned no receipt")
        compiler_result = receipt.get("compiler", receipt)
        status = compiler_result.get("status") if isinstance(compiler_result, Mapping) else None
        if status == "ok":
            checked, checked_sha256 = self._validate_private_manifest(
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                endpoint=endpoint,
            )
            return receipt, deepcopy(checked), checked_sha256
        if status != "invalid" or manifest is not None or manifest_sha256 is not None:
            raise BrainError("COMPILER_FAILED", 503, "candidate compiler result is invalid")
        return receipt, None, None

    @staticmethod
    def _validate_private_manifest(
        *,
        manifest: Any,
        manifest_sha256: Any,
        endpoint: str,
    ) -> tuple[dict[str, Any], str]:
        if (
            not isinstance(manifest, dict)
            or manifest.get("endpoint") != endpoint
            or not isinstance(manifest_sha256, str)
            or canonical_sha256(manifest) != manifest_sha256
        ):
            raise BrainError("COMPILER_FAILED", 503, "candidate compiler manifest is invalid")
        return manifest, manifest_sha256

    @staticmethod
    def _manifest_requires_preservation(manifest: Mapping[str, Any]) -> bool:
        containers = manifest.get("containers")
        fetches = manifest.get("fetches")
        if not isinstance(containers, list) or not isinstance(fetches, list):
            raise BrainError("GROUNDING_INVALID", 500, "compiled candidate manifest is invalid")
        if len(containers) != 1 or len(fetches) != 1:
            return True
        return any(
            isinstance(item, Mapping) and item.get("fallback_sha256") is not None
            for item in [*containers, *fetches]
        )

    def _compiled_grounding_diagnostic(
        self,
        *,
        candidate: ModelCandidate,
        request: TurnRequest,
        grounding: Mapping[str, Any],
        candidate_manifest: Mapping[str, Any],
        basis_manifest: Mapping[str, Any] | None,
        lossless_proof: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        target_diagnostic = candidate_target_diagnostic(candidate.source, request.target)
        if target_diagnostic is not None:
            return target_diagnostic
        if (
            candidate.generator == "lossless_renderer"
            and lossless_proof is not None
            and lossless_proof.get("contract") == STRUCTURAL_LOSSLESS_PROOF_CONTRACT
        ):
            return None
        if basis_manifest is not None:
            if request.target["mode"] == "existing":
                if candidate.generator == "lossless_renderer" and lossless_proof is not None:
                    return candidate_grounding_diagnostic(candidate.source, grounding)
                return adjudicate_manifest_preservation(
                    basis_manifest, candidate_manifest
                ).diagnostic
            preservation = adjudicate_manifest_preservation(basis_manifest, candidate_manifest)
            if preservation.diagnostic is None:
                return candidate_grounding_diagnostic(candidate.source, grounding)
            return {
                "code": "CANDIDATE_STRUCTURE_MISMATCH",
                "reason": "create refinement has no reviewed structural delta authority",
                "deltas": preservation.diagnostic["deltas"],
            }
        manifest_diagnostic = adjudicate_candidate_manifest(
            candidate_manifest, grounding
        ).diagnostic
        if manifest_diagnostic is not None:
            return manifest_diagnostic
        # The occurrence manifest owns catalog lineage and finite predicates;
        # the retained simple scanner still binds create cardinality/fallback
        # until those surfaces receive their own reviewed delta authority.
        return candidate_grounding_diagnostic(candidate.source, grounding)

    def _repair_grounding(
        self,
        *,
        candidate: ModelCandidate,
        diagnostic: dict[str, Any],
        request: TurnRequest,
        retrieved: RetrievalResult,
        record: TurnRecord,
        repairs_used: int,
    ) -> ModelCandidate:
        if candidate.generator == "lossless_renderer":
            raise BrainError(
                "LOSSLESS_INVALID",
                503,
                "lossless candidate differs from reviewed grounding",
            )
        if repairs_used >= self._max_repairs:
            diagnostic_code = diagnostic.get("code")
            if diagnostic_code not in {
                "CANDIDATE_GROUNDING_MISMATCH",
                "CANDIDATE_STRUCTURE_MISMATCH",
                "CANDIDATE_TARGET_MISMATCH",
            }:
                diagnostic_code = "CANDIDATE_GROUNDING_MISMATCH"
            raise BrainError(
                diagnostic_code,
                422,
                "candidate does not match the requested target and reviewed grounding",
            )
        attempt = repairs_used + 1
        record.emit(
            "repair.started",
            "repair_started",
            "Correzione delimitata della selezione",
            attempt=attempt,
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
            diagnostics=(diagnostic,),
            cancellation=record.cancellation,
        )
        repair_started = time.monotonic()
        with record.heartbeat_while(phase="repair_running", label="Correzione verificata in corso"):
            repaired = self._generate(repair_request)
        record.emit(
            "repair.completed",
            "repair_completed",
            "Correzione della selezione ricevuta",
            attempt=attempt,
            duration_ms=max(0, int((time.monotonic() - repair_started) * 1000)),
        )
        return repaired

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
            except BrainError as error:
                if error.code != "FLASH_INTENT_REJECTED":
                    raise
                record.emit(
                    "intent.completed",
                    "intent_completed",
                    "Interpretazione non applicabile in sicurezza",
                    count=0,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    replayed=False,
                )
                return request, retrieved
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

    @staticmethod
    def _structural_terminal_grounding(
        *,
        request: TurnRequest,
        retrieved: RetrievalResult,
        candidate: ModelCandidate,
        lossless_proof: Mapping[str, Any] | None,
        semantic_delta: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Reconcile raw prose retrieval with compiler-consumed structural intent.

        Retrieval deliberately keeps unrecognized structural prose unresolved.
        Only a validated structural lossless proof plus its host-only semantic
        delta certificate may replace that raw diagnostic in the terminal.  A
        finite literal is copied only from one exact reviewed selection and
        resolution in the same semantic snapshot.
        """

        if semantic_delta is None:
            return None
        proof_fields = {
            "contract",
            "proof_mode",
            "receipt_sha256",
            "sha_before",
            "sha_after",
            "touched_count",
        }
        delta_fields = {
            "contract",
            "all_operator_semantics_consumed",
            "compiler_binding_identities",
            "reviewed_selection_identities",
            "semantic_source_revision",
            "context_revision",
            "exact_authority",
        }
        source_sha256 = bytes_sha256(candidate.source.encode("utf-8"))
        if (
            not isinstance(lossless_proof, Mapping)
            or set(lossless_proof) != proof_fields
            or lossless_proof.get("contract") != STRUCTURAL_LOSSLESS_PROOF_CONTRACT
            or lossless_proof.get("proof_mode") != "validate"
            or not isinstance(lossless_proof.get("receipt_sha256"), str)
            or _SHA256_RE.fullmatch(lossless_proof["receipt_sha256"]) is None
            or lossless_proof.get("sha_before") != request.target.get("base_sha256")
            or lossless_proof.get("sha_after") != source_sha256
            or type(lossless_proof.get("touched_count")) is not int
            or not 1 <= lossless_proof["touched_count"] <= 32
            or not isinstance(semantic_delta, Mapping)
            or set(semantic_delta) != delta_fields
            or semantic_delta.get("contract") != STRUCTURAL_SEMANTIC_DELTA_CONTRACT
            or semantic_delta.get("all_operator_semantics_consumed") is not True
            or semantic_delta.get("semantic_source_revision")
            != request.expected_semantic_source_revision
            or semantic_delta.get("semantic_source_revision") != retrieved.semantic_source_revision
            or semantic_delta.get("context_revision") != request.expected_context_revision
        ):
            raise BrainError(
                "STRUCTURAL_GROUNDING_INVALID",
                503,
                "compiler-owned structural grounding certificate is invalid",
            )
        compiler_identities = semantic_delta.get("compiler_binding_identities")
        identities = semantic_delta.get("reviewed_selection_identities")
        if (
            not isinstance(compiler_identities, tuple)
            or len(compiler_identities) > 32
            or any(
                not isinstance(identity, tuple)
                or len(identity) != 3
                or any(not isinstance(item, str) or not item for item in identity)
                for identity in compiler_identities
            )
            or len(compiler_identities) != len(set(compiler_identities))
            or not isinstance(identities, tuple)
            or len(identities) > 32
            or any(
                not isinstance(identity, tuple)
                or len(identity) != 3
                or any(not isinstance(item, str) or not item for item in identity)
                for identity in identities
            )
            or len(identities) != len(set(identities))
            or any(identity not in compiler_identities for identity in identities)
        ):
            raise BrainError(
                "STRUCTURAL_GROUNDING_INVALID",
                503,
                "compiler-owned semantic delta roster is invalid",
            )
        exact_authority = semantic_delta.get("exact_authority")
        if compiler_identities:
            authority_fields = {
                "contract",
                "context_revision",
                "semantic_source_revision",
                "toolchain_binding",
                "index_revision",
                "outcomes",
                "selections",
                "resolutions",
            }
            context_toolchain = retrieved.context.get("toolchain_binding")
            if (
                not isinstance(exact_authority, Mapping)
                or set(exact_authority) != authority_fields
                or exact_authority.get("contract") != EXACT_REVIEWED_VALUE_AUTHORITY_CONTRACT
                or exact_authority.get("context_revision") != request.expected_context_revision
                or exact_authority.get("semantic_source_revision")
                != retrieved.semantic_source_revision
                or not isinstance(context_toolchain, str)
                or exact_authority.get("toolchain_binding") != context_toolchain
                or not isinstance(exact_authority.get("index_revision"), str)
                or _SHA256_RE.fullmatch(exact_authority["index_revision"]) is None
                or not isinstance(exact_authority.get("outcomes"), tuple)
                or not isinstance(exact_authority.get("selections"), tuple)
                or not isinstance(exact_authority.get("resolutions"), tuple)
            ):
                raise BrainError(
                    "STRUCTURAL_GROUNDING_INVALID",
                    503,
                    "exact reviewed value authority is invalid",
                )
            authority_selections = exact_authority["selections"]
            authority_resolutions = exact_authority["resolutions"]
            authority_outcomes = exact_authority["outcomes"]
            outcome_identities: dict[tuple[str, str, str], str] = {}
            for outcome in authority_outcomes:
                if not isinstance(outcome, Mapping):
                    raise BrainError(
                        "STRUCTURAL_GROUNDING_INVALID",
                        503,
                        "exact reviewed value outcome is invalid",
                    )
                identity = (
                    outcome.get("catalog"),
                    outcome.get("field"),
                    outcome.get("literal"),
                )
                status = outcome.get("status")
                if (
                    any(not isinstance(item, str) or not item for item in identity)
                    or identity in outcome_identities
                    or status not in {"reviewed_exact", "witness_eligible_absent"}
                ):
                    raise BrainError(
                        "STRUCTURAL_GROUNDING_INVALID",
                        503,
                        "exact reviewed value outcome roster is invalid",
                    )
                outcome_identities[identity] = status
            if {
                identity
                for identity, status in outcome_identities.items()
                if status == "reviewed_exact"
            } != set(identities):
                raise BrainError(
                    "STRUCTURAL_GROUNDING_INVALID",
                    503,
                    "reviewed semantic delta differs from exact authority outcomes",
                )
            if set(outcome_identities) != set(compiler_identities):
                raise BrainError(
                    "STRUCTURAL_GROUNDING_INVALID",
                    503,
                    "compiler binding delta differs from exact authority outcomes",
                )
        else:
            if exact_authority is not None:
                raise BrainError(
                    "STRUCTURAL_GROUNDING_INVALID",
                    503,
                    "empty semantic delta unexpectedly carries value authority",
                )
            authority_selections = ()
            authority_resolutions = ()
        selections: list[dict[str, Any]] = []
        resolutions: list[dict[str, Any]] = []
        for catalog, field, literal in identities:
            selected = [
                item
                for item in authority_selections
                if isinstance(item, Mapping)
                and item.get("catalog") == catalog
                and item.get("field") == field
                and item.get("literal") == literal
            ]
            reviewed = [
                item
                for item in authority_resolutions
                if isinstance(item, Mapping)
                and item.get("review_state") == "reviewed"
                and item.get("catalog") == catalog
                and item.get("field") == field
                and item.get("literal") == literal
            ]
            if len(selected) != 1 or len(reviewed) != 1:
                raise BrainError(
                    "STRUCTURAL_GROUNDING_INVALID",
                    503,
                    "semantic delta is not backed by one exact reviewed grounding",
                )
            public_selection = {
                "catalog": catalog,
                "field": field,
                "literal": literal,
            }
            for key in ("domain", "matched_by", "type", "modifiers"):
                if key in selected[0]:
                    public_selection[key] = deepcopy(selected[0][key])
            selections.append(public_selection)
            resolutions.append(
                {
                    "concept": literal,
                    "catalog": catalog,
                    "field": field,
                    "literal": literal,
                    "review_state": "reviewed",
                }
            )
        catalogs = retrieved.grounding.get("catalogs", [])
        if not isinstance(catalogs, list) or any(
            not isinstance(item, str) or not item for item in catalogs
        ):
            raise BrainError(
                "STRUCTURAL_GROUNDING_INVALID",
                503,
                "structural grounding catalog roster is invalid",
            )
        if any(catalog not in catalogs for catalog, _field, _literal in compiler_identities):
            raise BrainError(
                "STRUCTURAL_GROUNDING_INVALID",
                503,
                "semantic delta catalog is outside the retrieved authority",
            )
        value = dict(retrieved.grounding)
        value.update(
            {
                "status": "resolved",
                "reason": "compiler-owned structural delta is fully accounted for",
                "selected": selections[0] if len(selections) == 1 else None,
                "selections": selections,
                "candidates": [],
                "catalog_candidates": [],
                "lookup": None,
                "lookups": [],
                "unresolved": [],
                "resolutions": resolutions,
                "semantic_source_revision": retrieved.semantic_source_revision,
            }
        )
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
        if len(retrieved.catalog_candidates) > 5 and request.schema_version != 2:
            raise BrainError(
                "CLARIFICATION_SCHEMA_UNSUPPORTED",
                409,
                "client schema cannot answer the catalog roster clarification",
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
            question=(
                "Quale catalogo vuoi usare? Scrivi uno dei riferimenti esatti disponibili."
                if len(options) > 5
                else "Quale catalogo vuoi usare?"
            ),
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
        basis_manifest: Mapping[str, Any] | None = None,
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
        shape_decision = _current_server_decision(request, "response_shape")
        decision = _current_server_decision(request, "result_count")
        basis_output = (
            request.server_basis_grounding.get("output_contract")
            if isinstance(request.server_basis_grounding, Mapping)
            else None
        )
        preserve_compiled_output = (
            request.target["mode"] == "existing"
            and basis_manifest is not None
            and (
                self._manifest_requires_preservation(basis_manifest)
                or (isinstance(basis_output, Mapping) and basis_output.get("mode") == "preserve")
            )
        )
        if preserve_compiled_output:
            if (
                shape_decision is not None
                or decision is not None
                or output_request.contracts
                or output_request.generic_pagination
                or output_request.ambiguous_count
            ):
                raise BrainError(
                    "OUTPUT_CONTRACT_UNAVAILABLE",
                    422,
                    "occurrence-specific output change has no reviewed authority",
                )
            retrieved.grounding["output_contract"] = {"mode": "preserve"}
            retrieved.grounding["assumptions"] = [
                "Cardinalità, ordine e fallback di ogni occorrenza compilata restano invariati."
            ]
            retrieved.context["output_contract"] = {"mode": "preserve"}
            return None
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
        semantic_delta: Mapping[str, Any] | None = None,
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
        grounding = self._structural_terminal_grounding(
            request=request,
            retrieved=retrieved,
            candidate=candidate,
            lossless_proof=lossless_proof,
            semantic_delta=semantic_delta,
        ) or self._grounding(retrieved)
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
