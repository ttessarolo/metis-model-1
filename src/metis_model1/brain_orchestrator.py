"""Brain's bounded retrieval -> generation -> compile -> repair pipeline."""

from __future__ import annotations

import secrets
from typing import Any

from metis_model1.brain_model_runtime import BrainModelRuntime, ModelCandidate, ModelRequest
from metis_model1.brain_protocol import BrainError, bytes_sha256
from metis_model1.brain_retrieval import BrainRetriever, RetrievalResult
from metis_model1.brain_sessions import SessionManager
from metis_model1.brain_turns import TurnRecord, TurnRequest


class BrainOrchestrator:
    def __init__(
        self,
        *,
        retriever: BrainRetriever,
        model: BrainModelRuntime,
        compiler: Any,
        max_repairs: int = 2,
    ) -> None:
        if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
            raise BrainError("INVALID_CONFIG", 500, "repair budget is invalid")
        self._retriever = retriever
        self._model = model
        self._compiler = compiler
        self._max_repairs = max_repairs

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
            record.emit("retrieval.started", "retrieval_started", "Recupero contesto")
            retrieved = self._retriever.retrieve(lease=lease, request=request)
            self._check_semantic_revision(request, retrieved)
            record.emit(
                "retrieval.completed",
                "retrieval_completed",
                "Contesto recuperato",
                count=len(retrieved.context),
            )
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
                    return self._clarification(record, request, retrieved)
                record.emit("catalog.auto_selected", "catalog_selected", "Catalogo confermato")
            elif len(candidates) == 1:
                record.emit("catalog.auto_selected", "catalog_selected", "Catalogo selezionato")
            elif not retrieved.grounding.get("catalogs"):
                return self._unsupported(record, request, retrieved)
            if retrieved.grounding.get("status") not in {None, "resolved"}:
                return self._unsupported(record, request, retrieved)

            previous = lease.snapshot.source_map().get(request.target["relative_path"])
            model_request = ModelRequest(
                instruction=request.instruction,
                intent=request.intent,
                target_path=request.target["relative_path"],
                endpoint=request.target["endpoint"],
                context=retrieved.context,
                grounding=retrieved.grounding,
                previous_source=previous,
                cancellation=record.cancellation,
            )
            record.emit("inference.started", "inference_started", "Model 1 in generazione")
            candidate = self._generate(model_request)
            record.emit(
                "inference.completed",
                "inference_completed",
                "Candidato ricevuto",
                bytes=len(candidate.source.encode()),
            )

            diagnostics: list[dict[str, Any]] = []
            compile_receipt: dict[str, Any] | None = None
            attempts = 0
            while True:
                if record.cancellation.is_set() or lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "turn was revoked")
                attempts += 1
                record.emit(
                    "compile.started",
                    "compile_started",
                    "Compilazione del candidato",
                    attempt=attempts,
                )
                try:
                    compile_receipt = self._compiler.compile(
                        lease=lease,
                        source=candidate.source,
                        filename=request.target["relative_path"],
                        execution_mode="endpoint" if request.target["endpoint"] else "source",
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
                    )
                    break
                diagnostics = self._diagnostics(compile_receipt)
                record.emit(
                    "compile.completed",
                    "compile_completed",
                    "Compilazione con diagnostica",
                    attempt=attempts,
                )
                if attempts > self._max_repairs:
                    break
                record.emit(
                    "repair.started", "repair_started", "Correzione delimitata", attempt=attempts
                )
                repair_request = ModelRequest(
                    instruction=request.instruction,
                    intent=request.intent,
                    target_path=request.target["relative_path"],
                    endpoint=request.target["endpoint"],
                    context=retrieved.context,
                    grounding=retrieved.grounding,
                    previous_source=candidate.source,
                    diagnostics=tuple(diagnostics[:32]),
                    cancellation=record.cancellation,
                )
                candidate = self._generate(repair_request)
                record.emit(
                    "repair.completed", "repair_completed", "Correzione ricevuta", attempt=attempts
                )

            if compile_receipt is None:
                raise BrainError("COMPILER_FAILED", 503, "compiler returned no receipt")
            return self._proposal(
                record=record,
                request=request,
                retrieved=retrieved,
                candidate=candidate,
                receipt=compile_receipt,
                attempts=attempts,
                previous=previous,
                diagnostics=diagnostics,
            )

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
        clarification = request.clarification_response
        if clarification is None:
            return None
        if (
            clarification["context_revision"] != request.expected_context_revision
            or clarification["semantic_source_revision"]
            != request.expected_semantic_source_revision
        ):
            raise BrainError("SEMANTIC_SOURCE_STALE", 409, "clarification revision is stale")
        option_ref = clarification["option_ref"]
        for item in retrieved.catalog_candidates:
            if item.get("option_ref") == option_ref or item.get("catalog") == option_ref:
                return item
        raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "catalog option is unavailable")

    @staticmethod
    def _grounding(retrieved: RetrievalResult) -> dict[str, Any]:
        value = dict(retrieved.grounding)
        value["semantic_source_revision"] = retrieved.semantic_source_revision
        value.setdefault("resolutions", [])
        value.setdefault("unresolved", [])
        return value

    def _clarification(
        self, record: TurnRecord, request: TurnRequest, retrieved: RetrievalResult
    ) -> dict[str, Any]:
        options = []
        for item in retrieved.catalog_candidates[:5]:
            catalog = item.get("catalog", "")
            options.append(
                {
                    "option_ref": item.get("option_ref", catalog),
                    "catalog": catalog,
                    "label": item.get("label", catalog),
                    "description": item.get("description", "Catalogo autorizzato"),
                }
            )
        return {
            "schema_version": 1,
            "turn_id": record.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "outcome": "needs_clarification",
            "route": "local",
            "clarification": {
                "clarification_id": "clarification-" + secrets.token_urlsafe(18),
                "kind": "catalog",
                "question": "Quale catalogo vuoi usare?",
                "options": options,
            },
            "identity": self._identity(record, retrieved),
            "grounding": self._grounding(retrieved),
            "claims": {
                "compile_clean": None,
                "semantic_grounded": False,
                "semantic_correctness": False,
                "tenant_modified": False,
            },
        }

    def _unsupported(
        self, record: TurnRecord, request: TurnRequest, retrieved: RetrievalResult
    ) -> dict[str, Any]:
        grounding = self._grounding(retrieved)
        if not grounding.get("unresolved"):
            grounding["unresolved"] = [request.instruction[:256]]
        return {
            "schema_version": 1,
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
        return {
            "model_revision": getattr(self._model, "model_revision", "unavailable"),
            "adapter_sha256": getattr(self._model, "adapter_sha256", "unavailable"),
            "context_revision": record.request.expected_context_revision,
            "semantic_source_revision": retrieved.semantic_source_revision,
            "toolchain_binding": "unknown",
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
    ) -> dict[str, Any]:
        clean = receipt.get("compiler", receipt).get("status") == "ok"
        source_hash = bytes_sha256(candidate.source.encode("utf-8"))
        proposal = {
            "proposal_ref": "proposal-" + secrets.token_urlsafe(24),
            "operation": "create" if request.target["mode"] == "create" else "replace",
            "relative_path": request.target["relative_path"],
            "base_sha256": request.target["base_sha256"],
            "source": candidate.source,
            "source_sha256": source_hash,
            "proposal_basis": {
                "context_revision": request.expected_context_revision,
                "semantic_source_revision": retrieved.semantic_source_revision,
            },
        }
        identity = self._identity(record, retrieved)
        toolchain = receipt.get("toolchain_binding")
        if isinstance(toolchain, str):
            identity["toolchain_binding"] = toolchain
        validation = {
            "status": "ok" if clean else "invalid",
            "diagnostics": diagnostics,
            "attempts": attempts,
            "compiler_receipt_sha256": receipt.get("receipt_sha256", "unavailable"),
        }
        grounding = self._grounding(retrieved)
        semantically_grounded = (
            grounding.get("status") in {None, "resolved"}
            and not grounding.get("candidates")
            and not grounding.get("unresolved")
        )
        return {
            "schema_version": 1,
            "turn_id": record.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "outcome": "no_change" if previous == candidate.source else "proposed",
            "route": "local",
            "proposal": None if previous == candidate.source else proposal,
            "validation": validation,
            "grounding": grounding,
            "identity": identity,
            "claims": {
                "compile_clean": clean,
                "semantic_grounded": semantically_grounded,
                "semantic_correctness": False,
                "tenant_modified": False,
            },
        }
