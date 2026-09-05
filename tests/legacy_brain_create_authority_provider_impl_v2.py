"""Historical test-only CREATE authority fixture; never product authority.

Frozen from Model 1 61a6c47 for legacy regression assertions only. This module
is outside the src/metis_model1 wheel package and must never be imported by
production code. Its accepted closed recipes do not register product powers.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from legacy_brain_create_authority_issuer_v2 import CreateV2HostRefIssuer
from legacy_brain_create_structural_authority_v2 import (
    ReviewedSemanticIndex,
    StructuralNeed,
    closed_structural_semantic_requirements,
    filtered_collection_intent,
    initial_family_need,
    initial_ready_intent,
    presemantic_structural_need,
    refinement_ready_intent,
    reviewed_descriptor_filter_index,
    reviewed_semantic_index,
)

from metis_model1.brain_create_assembler import (
    CreateAuthorityAssemblyError,
    prune_reviewed_retrieval,
)
from metis_model1.brain_create_authority_provider_v2 import (
    AskCreateV2Authority,
    CreateV2AuthorityDecision,
    PrivateCreateV2Basis,
    ReadyCreateV2Authority,
    validate_dialogue_binding,
)
from metis_model1.brain_create_capability_inventory_v2 import (
    AMBIGUOUS_CURRENT_TIME_COMMANDS,
    DISABLE_CURRENT_TIME_COMMANDS,
    ENABLE_CURRENT_TIME_COMMANDS,
    PinnedCreateV2CapabilityInventory,
    build_pinned_create_v2_capability_inventory,
    validate_pinned_create_v2_inventory,
)
from metis_model1.brain_create_plan_v2 import initial_create_endpoint_skeleton
from metis_model1.brain_create_surface import create_authority_history_revision
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    BoundDecision,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_dialogue_planner import ChoiceNeed, QuantityNeed, plan_create_dialogue
from metis_model1.brain_output_contract import parse_create_quantity_surface
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_turns import TurnRequest
from metis_model1.brain_typed_create_pipeline import TypedCreateV2RequestBinding

_DECISION_KEY = "choice.endpoint.needs_time"
_TARGET_KEY = "endpoint.needs_time"
_ENABLE_KEY = "capability:endpoint.needs_time.enable"
_DISABLE_KEY = "capability:endpoint.needs_time.disable"
_DESCRIPTOR_FILTER_DECISION_KEY = "choice.structure.descriptor_filtered_collection"
_DESCRIPTOR_FILTER_TARGET_KEY = "structure.descriptor_filtered_collection"
_DESCRIPTOR_FILTER_ENABLE_KEY = "capability:descriptor.filtered_collection"
_DESCRIPTOR_FILTER_DEFER_KEY = "clarification:descriptor.more_structure"
_DESCRIPTOR_FILTER_COUNT_TARGET = "endpoint.results.total"
CREATE_V2_AUTHORITY_PROVIDER_CONTRACT = (
    "metis-brain-create-authority-provider/production-structural-v2"
)
_CATALOG_DECLARATION_RE = re.compile(
    rb"(?m)^\s*catalog\s+([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)\b"
)
_QUALIFIED_CATALOG_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$"
)


class ExactReviewedValueResolver(Protocol):
    def resolve_exact_reviewed_values(
        self,
        *,
        lease: OperationLease,
        identities: tuple[tuple[str, str, str], ...],
    ) -> dict[str, Any]: ...


def _unsupported(message: str) -> None:
    raise BrainError("CREATE_TYPED_AUTHORITY_UNSUPPORTED", 422, message)


def _invalid(message: str) -> None:
    raise BrainError("CREATE_TYPED_AUTHORITY_INVALID", 500, message)


def _normalize_command(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("’", "'").casefold().strip()
    normalized = re.sub(r"[.!?]+$", "", normalized).strip()
    return " ".join(normalized.split())


def _semantic_requirement_map(grounding: Mapping[str, Any]) -> dict[tuple[str, ...], list[str]]:
    catalogs = grounding.get("catalogs")
    selections = grounding.get("selections")
    if not isinstance(catalogs, list) or not isinstance(selections, list):
        _unsupported("catalog semantic authority is incomplete")
    identities: list[tuple[str, ...]] = []
    for catalog in catalogs:
        if not isinstance(catalog, str) or not catalog:
            _unsupported("catalog semantic authority is invalid")
        identities.append(("catalog", catalog))
    for item in selections:
        if not isinstance(item, Mapping):
            _unsupported("catalog semantic selection is invalid")
        catalog, field, literal = item.get("catalog"), item.get("field"), item.get("literal")
        if not isinstance(catalog, str) or not isinstance(field, str):
            _unsupported("catalog semantic selection is invalid")
        identities.append(("field", catalog, field))
        if literal is not None:
            if not isinstance(literal, str):
                _unsupported("catalog semantic value is invalid")
            identities.append(("catalog_value", catalog, field, literal))
    distinct = tuple(dict.fromkeys(identities))
    return {identity: [f"semantic.requirement.{index}"] for index, identity in enumerate(distinct)}


def _reject_content_semantics(
    *,
    retrieved: RetrievalResult,
    lease: OperationLease,
) -> None:
    """Prove selected content evidence is reviewed, then refuse unsupported structure."""

    if not isinstance(retrieved, RetrievalResult):
        _invalid("retrieval authority is invalid")
    if retrieved.semantic_source_revision != lease.snapshot.semantic_source_revision():
        raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval authority is stale")
    if not isinstance(retrieved.context, Mapping) or not isinstance(retrieved.grounding, Mapping):
        _invalid("retrieval authority is invalid")
    context = retrieved.context
    for key, expected in (
        ("context_revision", lease.snapshot.revision),
        ("semantic_source_revision", retrieved.semantic_source_revision),
        ("toolchain_binding", lease.snapshot.toolchain_binding),
    ):
        if key in context and context.get(key) != expected:
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval binding differs")
    selections = retrieved.grounding.get("selections")
    if selections in (None, []):
        return
    if not isinstance(selections, list):
        _unsupported("catalog semantic selection is invalid")
    try:
        projection = prune_reviewed_retrieval(
            retrieved=retrieved,
            context_revision=lease.snapshot.revision,
            semantic_revision=retrieved.semantic_source_revision,
            toolchain_binding=lease.snapshot.toolchain_binding,
            authority_requirement_keys=_semantic_requirement_map(retrieved.grounding),
        )
    except CreateAuthorityAssemblyError as error:
        raise BrainError(
            "CREATE_TYPED_AUTHORITY_UNSUPPORTED",
            422,
            "catalog semantics are not complete reviewed authority",
        ) from error
    if projection.status != "resolved" or any(
        item.state != "reviewed" or not item.resolved for item in projection.authorities
    ):
        _unsupported("catalog semantics are not complete reviewed authority")
    _unsupported("catalog content structure is not available in the partial production provider")


def _validate_retrieval_envelope(*, retrieved: RetrievalResult, lease: OperationLease) -> None:
    """Validate immutable retrieval bindings even when the outcome is an Ask."""

    if not isinstance(retrieved, RetrievalResult):
        _invalid("retrieval authority is invalid")
    expected_semantic = lease.snapshot.semantic_source_revision()
    if retrieved.semantic_source_revision != expected_semantic:
        raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval authority is stale")
    if not isinstance(retrieved.context, Mapping) or not isinstance(retrieved.grounding, Mapping):
        _invalid("retrieval authority is invalid")
    for key, expected in (
        ("context_revision", lease.snapshot.revision),
        ("semantic_source_revision", expected_semantic),
        ("toolchain_binding", lease.snapshot.toolchain_binding),
    ):
        if retrieved.context.get(key) != expected:
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval binding differs")


def _latest_decision(dialogue: PrivateDialogueState) -> BoundDecision | None:
    matches = tuple(
        item
        for item in dialogue.decisions
        if item.decision_key == _DECISION_KEY and item.target_key == _TARGET_KEY
    )
    return matches[-1] if matches else None


def _choice_need(
    inventory: PinnedCreateV2CapabilityInventory,
    *,
    supersedes: str | None,
) -> ChoiceNeed:
    choices = tuple(
        BoundChoice(
            label=inventory.capability(key).label,
            authority_keys=(key,),
            candidate_revision=inventory.inventory_revision,
            required_roles=("scalar",),
            description=(
                "Rende disponibile il tempo corrente all'endpoint"
                if key == _ENABLE_KEY
                else "Mantiene disabilitato il tempo corrente"
            ),
        )
        for key in (_ENABLE_KEY, _DISABLE_KEY)
    )
    return ChoiceNeed(
        decision_key=_DECISION_KEY,
        target_key=_TARGET_KEY,
        kind="structural_choice",
        question="Vuoi abilitare o disabilitare il tempo corrente per questo endpoint?",
        choices=choices,
        supersedes=supersedes,
    )


def _descriptor_filter_revision(
    inventory_revision: str, semantic: ReviewedSemanticIndex, count: int
) -> str:
    return canonical_sha256(
        {
            "contract": "metis-brain-descriptor-filter-confirmation/v1",
            "inventory_revision": inventory_revision,
            "semantic_proof_revision": semantic.proof_revision,
            "count": count,
            "logic": "include_all_fields_any_selected_value",
        }
    )


def _descriptor_filter_slot(
    inventory_revision: str,
    semantic: ReviewedSemanticIndex,
    count: int,
    *,
    supersedes: str | None = None,
) -> QuestionSlot:
    revision = _descriptor_filter_revision(inventory_revision, semantic, count)
    filters = "; ".join(
        f"{field} = " + " oppure ".join(json.dumps(value, ensure_ascii=False) for value in values)
        for field, values in semantic.selected_values
    )
    summary = (
        f"Catalogo {semantic.catalog}. {count} risultati totali. "
        f"Includi soltanto elementi che soddisfano TUTTI i filtri: {filters}. "
        "Un unico blocco, senza ordinamento aggiuntivo, paginazione o fallback."
    )
    if len(summary.encode("utf-8")) > 1024:
        _unsupported("descriptor filter confirmation exceeds the readable bound")
    choices = (
        BoundChoice(
            label="Un solo blocco filtrato",
            authority_keys=(_DESCRIPTOR_FILTER_ENABLE_KEY,),
            candidate_revision=revision,
            required_roles=("scalar",),
            description=summary,
        ),
        BoundChoice(
            label="Serve una struttura più articolata",
            authority_keys=(_DESCRIPTOR_FILTER_DEFER_KEY,),
            candidate_revision=revision,
            required_roles=("scalar",),
            description=(
                "Richiede dettagli per blocchi, similarità, paginazione, fallback o relazioni"
            ),
        ),
    )
    return QuestionSlot(
        decision_key=_DESCRIPTOR_FILTER_DECISION_KEY,
        target_key=_DESCRIPTOR_FILTER_TARGET_KEY,
        kind="structural_choice",
        question=(
            "Confermi esattamente il blocco e i filtri di inclusione descritti nella prima opzione?"
        ),
        answer_kind="option_ref",
        choices=choices,
        supersedes=supersedes,
    )


def _latest_descriptor_filter_decision(dialogue: PrivateDialogueState) -> BoundDecision | None:
    matches = tuple(
        item
        for item in dialogue.decisions
        if item.decision_key == _DESCRIPTOR_FILTER_DECISION_KEY
        and item.target_key == _DESCRIPTOR_FILTER_TARGET_KEY
    )
    return matches[-1] if matches else None


def _descriptor_filter_choice(
    dialogue: PrivateDialogueState,
    *,
    inventory_revision: str,
    semantic: ReviewedSemanticIndex,
    count: int,
) -> str | None:
    decision = _latest_descriptor_filter_decision(dialogue)
    if decision is None:
        return None
    if (
        decision.kind != "structural_choice"
        or decision.answer_kind != "option_ref"
        or decision.value_contract != "authority"
        or len(decision.choices) != 1
    ):
        _invalid("descriptor collection decision is invalid")
    if decision.binding.history_revision != dialogue.binding.history_revision:
        # A pure natural-language selection of the captured label may add one
        # utterance. Any new requirements must be confirmed afresh.
        preceding = (
            create_authority_history_revision(dialogue.messages[:-1])
            if len(dialogue.messages) > 1
            else None
        )
        if preceding != decision.binding.history_revision or _normalize_command(
            dialogue.messages[-1].text
        ) != _normalize_command(decision.choices[0].label):
            return None
    revision = _descriptor_filter_revision(inventory_revision, semantic, count)
    matching = tuple(
        choice
        for choice in decision.choices
        if len(choice.authority_keys) == 1
        and choice.authority_keys[0]
        in {_DESCRIPTOR_FILTER_ENABLE_KEY, _DESCRIPTOR_FILTER_DEFER_KEY}
        and choice.candidate_revision == revision
        and choice.required_roles == ("scalar",)
    )
    if len(matching) != 1:
        _invalid("descriptor collection decision is invalid")
    return matching[0].authority_keys[0]


def _descriptor_filter_count(dialogue: PrivateDialogueState) -> int | None:
    need = QuantityNeed(target_key=_DESCRIPTOR_FILTER_COUNT_TARGET, necessary=True)
    decisions = tuple(item for item in dialogue.decisions if item.identity == need.identity)
    latest = decisions[-1] if decisions else None
    start = 0
    if latest is not None:
        if (
            latest.kind != "result_count"
            or latest.answer_kind != "integer"
            or latest.value_contract != "total"
            or type(latest.integer) is not int
        ):
            _invalid("descriptor collection count decision is invalid")
        start = next(
            index
            for index in range(1, len(dialogue.messages) + 1)
            if create_authority_history_revision(dialogue.messages[:index])
            == latest.binding.history_revision
        )
    operator_values: set[int] = set()
    for message in dialogue.messages[start:]:
        surface = parse_create_quantity_surface(message.text)
        if surface.status != "resolved":
            continue
        operator_values.update(
            item.value
            for item in surface.mentions
            if item.kind == "result_count"
            and item.scope == "total"
            and item.mode == "total"
            and item.qualifier is None
            and type(item.value) is int
        )
    decided_values = {latest.integer} if latest is not None else set()
    values = operator_values | decided_values
    if len(values) > 1:
        _unsupported("descriptor collection result count is ambiguous")
    return next(iter(values)) if values else None


def _has_descriptor_filter_selection(retrieved: RetrievalResult) -> bool:
    grounding = retrieved.grounding
    if not isinstance(grounding, Mapping) or grounding.get("status") != "resolved":
        return False
    selections = grounding.get("selections")
    return (
        isinstance(selections, list)
        and bool(selections)
        and all(
            isinstance(item, Mapping)
            and (isinstance(item.get("literal"), str) or isinstance(item.get("literals"), list))
            for item in selections
        )
    )


def _catalog_slot(
    retrieved: RetrievalResult,
    *,
    lease: OperationLease,
    semantic_revision: str,
) -> QuestionSlot:
    declared = {
        match.group(1).decode("ascii")
        for file in lease.snapshot.files
        for match in _CATALOG_DECLARATION_RE.finditer(file.content)
    }
    candidates: list[tuple[str, str]] = []
    context = retrieved.context
    raw_catalogs = context.get("catalogs") if isinstance(context, Mapping) else None
    if retrieved.catalog_candidates:
        if not isinstance(raw_catalogs, list) or len(raw_catalogs) != len(
            retrieved.catalog_candidates
        ):
            _unsupported("catalog candidate authority is invalid")
        expected_grounding = retrieved.grounding.get("catalog_candidates")
        if not isinstance(expected_grounding, list):
            _unsupported("catalog candidate authority is invalid")
        for candidate, contextual in zip(retrieved.catalog_candidates, raw_catalogs, strict=True):
            if not isinstance(candidate, Mapping) or dict(candidate) != contextual:
                _unsupported("catalog candidate authority is invalid")
            catalog = candidate.get("catalog")
            label = candidate.get("label")
            option_ref = candidate.get("option_ref")
            description = candidate.get("description")
            if (
                not isinstance(catalog, str)
                or _QUALIFIED_CATALOG_RE.fullmatch(catalog) is None
                or catalog not in declared
                or option_ref != "catalog-" + canonical_sha256({"catalog": catalog})[7:31]
                or not isinstance(label, str)
                or not label.strip()
                or not isinstance(description, str)
                or not description.strip()
            ):
                _unsupported("catalog candidate authority is invalid")
            candidates.append((catalog, label))
        if expected_grounding != [catalog for catalog, _label in candidates]:
            _unsupported("catalog candidate authority is invalid")
    else:
        raw_catalog = context.get("catalog") if isinstance(context, Mapping) else None
        if (
            not isinstance(raw_catalog, Mapping)
            or set(raw_catalog) - {"name", "file", "semantic"}
            or not isinstance(raw_catalog.get("name"), str)
            or _QUALIFIED_CATALOG_RE.fullmatch(raw_catalog["name"]) is None
            or raw_catalog["name"] not in declared
            or not isinstance(raw_catalog.get("semantic"), Mapping)
            or raw_catalog["semantic"].get("state") != "reviewed"
        ):
            _unsupported("reviewed catalog authority is unavailable")
        candidates.append((raw_catalog["name"], raw_catalog["name"].rsplit(".", 1)[-1]))
    if not candidates:
        _unsupported("catalog candidate authority is unavailable")
    if len({catalog for catalog, _label in candidates}) != len(candidates):
        _unsupported("catalog candidate authority is duplicated")
    choices = tuple(
        BoundChoice(
            label=label,
            authority_keys=(f"catalog:{catalog}",),
            candidate_revision=semantic_revision,
            required_roles=("catalog",),
            description=f"Usa il catalogo {label}",
        )
        for catalog, label in candidates
    )
    return QuestionSlot(
        decision_key="choice.catalog.initial",
        target_key="catalog.selection",
        kind="catalog",
        question="Quali cataloghi devo usare?",
        answer_kind="option_refs" if len(choices) > 1 else "option_ref",
        choices=choices,
        minimum=1,
        maximum=len(choices),
    )


def _initial_slot(
    dialogue: PrivateDialogueState,
    retrieved: RetrievalResult,
    lease: OperationLease,
) -> QuestionSlot:
    need = initial_family_need(dialogue.messages[0].text)
    if need is None:
        _unsupported("request structure is outside the pinned production authority")
    kind, target_key, _question = need
    if kind == "catalog":
        return _catalog_slot(
            retrieved,
            lease=lease,
            semantic_revision=retrieved.semantic_source_revision,
        )
    if kind == "page":
        return QuantityNeed(
            target_key=target_key,
            scope="page",
            mode="page_default",
            necessary=True,
            label="pagina",
        ).slot()
    if kind == "row":
        return QuantityNeed(
            target_key=target_key,
            scope="row",
            mode="total",
            necessary=True,
            label="riga",
        ).slot()
    if kind == "rows":
        return QuantityNeed(
            target_key=target_key,
            kind="row_count",
            scope="page",
            mode="exact",
            necessary=True,
            label="pagina",
        ).slot()
    return QuantityNeed(
        target_key=target_key,
        scope="total",
        mode="total",
        necessary=True,
        label="endpoint",
    ).slot()


def _structural_slot(need: StructuralNeed, *, inventory_revision: str) -> QuestionSlot:
    digest = canonical_sha256(
        {"contract_id": CREATE_V2_AUTHORITY_PROVIDER_CONTRACT, "target": need.target_key}
    )[7:23]
    return QuestionSlot(
        decision_key=f"choice.structure.{digest}",
        target_key=need.target_key,
        kind="structural_choice",
        question=need.question,
        answer_kind="option_ref",
        choices=(
            BoundChoice(
                label="Specificare il contratto mancante",
                authority_keys=(f"clarification:structure:{digest}:specify",),
                candidate_revision=inventory_revision,
                required_roles=("scalar",),
                description="Fornisci nel prossimo messaggio i dettagli verificabili richiesti",
            ),
            BoundChoice(
                label="Ridurre la richiesta",
                authority_keys=(f"clarification:structure:{digest}:reduce",),
                candidate_revision=inventory_revision,
                required_roles=("scalar",),
                description="Riformula la richiesta senza la struttura non definita",
            ),
        ),
    )


class PinnedCreateV2AuthorityProvider:
    """Production-safe structural provider; unknown structure is never guessed."""

    __slots__ = (
        "_closed",
        "_exact_value_resolver",
        "_inventory",
        "_issuer",
        "_legacy_closed_recipes",
    )

    def __init__(
        self,
        *,
        hmac_key: bytes,
        toolchain_binding: str,
        exact_value_resolver: ExactReviewedValueResolver | None = None,
        inventory: PinnedCreateV2CapabilityInventory | None = None,
        legacy_closed_recipes: bool = False,
    ) -> None:
        expected = (
            build_pinned_create_v2_capability_inventory(toolchain_binding=toolchain_binding)
            if inventory is None
            else validate_pinned_create_v2_inventory(inventory)
        )
        if expected.toolchain_binding != toolchain_binding:
            raise BrainError("CREATE_V2_CAPABILITY_INVALID", 500, "inventory toolchain differs")
        self._inventory = expected
        self._issuer = CreateV2HostRefIssuer(hmac_key=hmac_key)
        if exact_value_resolver is not None and not callable(
            getattr(exact_value_resolver, "resolve_exact_reviewed_values", None)
        ):
            raise BrainError("CREATE_V2_CAPABILITY_INVALID", 500, "exact value resolver is invalid")
        self._exact_value_resolver = exact_value_resolver
        if type(legacy_closed_recipes) is not bool:
            raise BrainError("CREATE_V2_CAPABILITY_INVALID", 500, "legacy recipe mode is invalid")
        self._legacy_closed_recipes = legacy_closed_recipes
        self._closed = False

    @property
    def inventory_revision(self) -> str:
        return self._inventory.inventory_revision

    @property
    def policy_revision(self) -> str:
        return self._inventory.policy_revision

    @property
    def contract_id(self) -> str:
        return CREATE_V2_AUTHORITY_PROVIDER_CONTRACT

    def close(self) -> None:
        if self._closed:
            return
        self._issuer.close()
        self._closed = True

    def prepare(
        self,
        *,
        session_id: str,
        lease: OperationLease,
        request: TurnRequest,
        dialogue: PrivateDialogueState,
        retrieved: RetrievalResult,
        basis: PrivateCreateV2Basis | None,
    ) -> CreateV2AuthorityDecision:
        if self._closed:
            raise BrainError(
                "CREATE_V2_AUTHORITY_RETIRED", 500, "CREATE v2 authority provider is closed"
            )
        if not isinstance(lease, OperationLease) or lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        if session_id != lease.session_id:
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "session authority differs")
        if lease.snapshot.toolchain_binding != self._inventory.toolchain_binding:
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "toolchain authority is stale")
        if not isinstance(request, TurnRequest) or not isinstance(dialogue, PrivateDialogueState):
            _invalid("typed CREATE request authority is invalid")
        if (
            request.schema_version != 2
            or request.intent != "create"
            or request.target.get("mode") != "create"
        ):
            _invalid("typed CREATE request mode is invalid")
        if not isinstance(retrieved, RetrievalResult):
            _invalid("retrieval authority is invalid")
        validate_dialogue_binding(
            lease=lease,
            request=request,
            dialogue=dialogue,
            semantic_revision=retrieved.semantic_source_revision,
        )
        _validate_retrieval_envelope(retrieved=retrieved, lease=lease)
        endpoint = request.target.get("endpoint")
        filename = request.target.get("relative_path")
        if not isinstance(endpoint, str) or not isinstance(filename, str):
            _invalid("typed CREATE target is invalid")
        binding = TypedCreateV2RequestBinding(
            history=dialogue.messages,
            history_revision=dialogue.binding.history_revision,
            context_revision=lease.snapshot.revision,
            semantic_revision=retrieved.semantic_source_revision,
            candidate_filename=filename,
            endpoint=endpoint,
        )
        if basis is not None:
            if not isinstance(basis, PrivateCreateV2Basis):
                _invalid("typed CREATE basis is invalid")
            parent_endpoint = basis.spec.get("endpoint")
            if not isinstance(parent_endpoint, Mapping) or parent_endpoint.get("name") != endpoint:
                raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "basis target differs")
            if (
                len(basis.history) > len(dialogue.messages)
                or tuple(dialogue.messages[: len(basis.history)]) != basis.history
            ):
                raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "basis history differs")
        generation = 0 if basis is None else basis.generation + 1

        latest = _normalize_command(dialogue.messages[-1].text)
        desired: bool | None = None
        origin: Literal["operator", "clarification"] = "operator"
        evidence_identity: dict[str, Any] = {
            "message_ordinal": dialogue.messages[-1].ordinal,
            "message_sha256": dialogue.messages[-1].message_sha256,
            "recognition": "normalized_full_utterance",
        }
        if latest in ENABLE_CURRENT_TIME_COMMANDS:
            desired = True
        elif latest in DISABLE_CURRENT_TIME_COMMANDS:
            desired = False
        elif latest in AMBIGUOUS_CURRENT_TIME_COMMANDS:
            prior = _latest_decision(dialogue)
            need = _choice_need(
                self._inventory,
                supersedes=(
                    prior.decision_sha256 if basis is not None and prior is not None else None
                ),
            )
            plan = plan_create_dialogue(
                dialogue=dialogue,
                quantity_surface=parse_create_quantity_surface(dialogue.messages[-1].text),
                choices=(need,),
            )
            if plan.slots:
                return AskCreateV2Authority(plan.slots)
            resolved = tuple(
                choice
                for item in plan.resolved_choices
                if item.decision_key == _DECISION_KEY and item.target_key == _TARGET_KEY
                for choice in item.choices
            )
            if len(resolved) != 1 or len(resolved[0].authority_keys) != 1:
                _invalid("time capability decision is invalid")
            key = resolved[0].authority_keys[0]
            if key not in {_ENABLE_KEY, _DISABLE_KEY}:
                _invalid("time capability decision is invalid")
            desired = key == _ENABLE_KEY
            origin = "clarification"
            decision = _latest_decision(dialogue)
            if decision is None:
                _invalid("time capability decision is absent")
            evidence_identity = {
                "decision_sha256": decision.decision_sha256,
                "question_ref": decision.question_ref,
                "recognition": "server_bound_choice",
            }
        elif basis is None:
            # The only valid resume without repeating the ambiguous command is
            # its first server-bound answer turn.
            decision = _latest_decision(dialogue)
            seed = any(
                _normalize_command(item.text) in AMBIGUOUS_CURRENT_TIME_COMMANDS
                for item in dialogue.messages[:-1]
            )
            if decision is not None and seed:
                matching = tuple(
                    choice
                    for choice in decision.choices
                    if len(choice.authority_keys) == 1
                    and choice.authority_keys[0] in {_ENABLE_KEY, _DISABLE_KEY}
                    and choice.candidate_revision == self._inventory.inventory_revision
                    and choice.required_roles == ("scalar",)
                )
                if len(matching) != 1:
                    _invalid("time capability decision is invalid")
                desired = matching[0].authority_keys[0] == _ENABLE_KEY
                origin = "clarification"
                evidence_identity = {
                    "decision_sha256": decision.decision_sha256,
                    "question_ref": decision.question_ref,
                    "recognition": "server_bound_choice",
                }
        base_spec = initial_create_endpoint_skeleton(endpoint) if basis is None else basis.spec
        if desired is not None:
            _reject_content_semantics(retrieved=retrieved, lease=lease)
            parent = base_spec.get("endpoint")
            if not isinstance(parent, Mapping) or type(parent.get("needs_time")) is not bool:
                _invalid("base typed CREATE spec is invalid")
            if parent["needs_time"] is desired:
                _unsupported("request does not produce an authorized structural change")
            issued = self._issuer.issue_needs_time_authority(
                inventory=self._inventory,
                session_id=lease.session_id,
                conversation_id=dialogue.conversation_id,
                request_fingerprint=dialogue.binding.parent_fingerprint,
                history_revision=dialogue.binding.history_revision,
                context_revision=lease.snapshot.revision,
                semantic_revision=retrieved.semantic_source_revision,
                toolchain_binding=lease.snapshot.toolchain_binding,
                generation=generation,
                endpoint=endpoint,
                candidate_filename=filename,
                enabled=desired,
                origin=origin,
                evidence_identity=evidence_identity,
                parent_spec_sha256=None if basis is None else basis.spec_sha256,
                parent_ir_sha256=None if basis is None else basis.ir_sha256,
                parent_proposal_ref=None if basis is None else basis.proposal_ref,
            )
        else:
            if any(token in latest for token in ("tempo corrente", "ora corrente", "current time")):
                _unsupported("mixed current-time structure is not authorized")
            descriptor_mode = (
                basis is None
                and not self._legacy_closed_recipes
                and _has_descriptor_filter_selection(retrieved)
            )
            if descriptor_mode:
                semantic = reviewed_descriptor_filter_index(
                    retrieved=retrieved,
                    context_revision=lease.snapshot.revision,
                    semantic_revision=retrieved.semantic_source_revision,
                    toolchain_binding=lease.snapshot.toolchain_binding,
                )
                count = _descriptor_filter_count(dialogue)
                if count is None:
                    return AskCreateV2Authority(
                        (
                            QuantityNeed(
                                target_key=_DESCRIPTOR_FILTER_COUNT_TARGET,
                                necessary=True,
                                label="endpoint",
                            ).slot(),
                        )
                    )
                descriptor_choice = _descriptor_filter_choice(
                    dialogue,
                    inventory_revision=self.inventory_revision,
                    semantic=semantic,
                    count=count,
                )
                if descriptor_choice is None:
                    prior = _latest_descriptor_filter_decision(dialogue)
                    return AskCreateV2Authority(
                        (
                            _descriptor_filter_slot(
                                self.inventory_revision,
                                semantic,
                                count,
                                supersedes=None if prior is None else prior.decision_sha256,
                            ),
                        )
                    )
                if descriptor_choice == _DESCRIPTOR_FILTER_DEFER_KEY:
                    _unsupported(
                        "la struttura richiesta non ha ancora un contratto generale disponibile"
                    )
                structural = filtered_collection_intent(
                    count=count,
                    messages=dialogue.messages,
                    semantic=semantic,
                    policy_revision=self._inventory.policy_revision,
                )
            else:
                if not self._legacy_closed_recipes:
                    if basis is None and retrieved.catalog_candidates:
                        return AskCreateV2Authority(
                            (
                                _catalog_slot(
                                    retrieved,
                                    lease=lease,
                                    semantic_revision=retrieved.semantic_source_revision,
                                ),
                            )
                        )
                    _unsupported("request needs a descriptor-native structural contract")
                if basis is None and len(dialogue.messages) == 1:
                    return AskCreateV2Authority((_initial_slot(dialogue, retrieved, lease),))
                structural_need = presemantic_structural_need(
                    dialogue.messages, generation=generation
                )
                if structural_need is not None:
                    return AskCreateV2Authority(
                        (
                            _structural_slot(
                                structural_need,
                                inventory_revision=self.inventory_revision,
                            ),
                        )
                    )
                raw_catalog = retrieved.context.get("catalog")
                if not isinstance(raw_catalog, Mapping) or not isinstance(
                    raw_catalog.get("name"), str
                ):
                    _unsupported("one reviewed catalog context is required")
                requirements = closed_structural_semantic_requirements(
                    dialogue.messages,
                    generation=generation,
                    catalog=raw_catalog["name"],
                )
                exact_value_authority: Mapping[str, Any] | None = None
                if requirements.resolver_identities:
                    if self._exact_value_resolver is None:
                        _unsupported("exact reviewed value resolver is unavailable")
                    try:
                        exact_value_authority = (
                            self._exact_value_resolver.resolve_exact_reviewed_values(
                                lease=lease,
                                identities=requirements.resolver_identities,
                            )
                        )
                    except BrainError as error:
                        if error.code == "EXACT_REVIEWED_VALUE_UNAVAILABLE":
                            _unsupported("an exact reviewed value is unavailable")
                        raise
                semantic = reviewed_semantic_index(
                    retrieved=retrieved,
                    context_revision=lease.snapshot.revision,
                    semantic_revision=retrieved.semantic_source_revision,
                    toolchain_binding=lease.snapshot.toolchain_binding,
                    dialogue_message_count=len(dialogue.messages),
                    expected_value_identities=requirements.resolver_identities,
                    expected_cumulative_identities=requirements.cumulative_identities,
                    exact_value_authority=exact_value_authority,
                )
                if basis is None:
                    structural = initial_ready_intent(
                        messages=dialogue.messages,
                        semantic=semantic,
                        policy_revision=self._inventory.policy_revision,
                    )
                else:
                    structural = refinement_ready_intent(
                        messages=dialogue.messages,
                        base_spec=base_spec,
                        generation=generation,
                        semantic=semantic,
                        policy_revision=self._inventory.policy_revision,
                    )
                if isinstance(structural, StructuralNeed):
                    return AskCreateV2Authority(
                        (_structural_slot(structural, inventory_revision=self.inventory_revision),)
                    )
            issued = self._issuer.issue_structural_authority(
                inventory=self._inventory,
                intent=structural,
                semantic_authority=semantic if descriptor_mode else None,
                result_count=count if descriptor_mode else None,
                session_id=lease.session_id,
                conversation_id=dialogue.conversation_id,
                request_fingerprint=dialogue.binding.parent_fingerprint,
                history_revision=dialogue.binding.history_revision,
                context_revision=lease.snapshot.revision,
                semantic_revision=retrieved.semantic_source_revision,
                toolchain_binding=lease.snapshot.toolchain_binding,
                generation=generation,
                endpoint=endpoint,
                candidate_filename=filename,
                parent_spec_sha256=None if basis is None else basis.spec_sha256,
                parent_ir_sha256=None if basis is None else basis.ir_sha256,
                parent_proposal_ref=None if basis is None else basis.proposal_ref,
            )
        return ReadyCreateV2Authority(
            binding=binding,
            projection=issued.projection,
            active_requirement_handles=issued.active_requirement_handles,
            base_spec=base_spec,
            target_ref=issued.target_ref,
            basis_ref=issued.basis_ref,
            generation=generation,
            parent_spec_sha256=None if basis is None else basis.spec_sha256,
            parent_ir=None if basis is None else basis.ir,
            parent_ir_sha256=None if basis is None else basis.ir_sha256,
        )


__all__ = [
    "CREATE_V2_AUTHORITY_PROVIDER_CONTRACT",
    "ExactReviewedValueResolver",
    "PinnedCreateV2AuthorityProvider",
]
