"""Client-neutral, bounded choices for descriptor-native structural operations.

Labels assist the operator; only server-bound decisions select a construction.
No free-text family classifier, endpoint roster or domain name supplies authority.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from metis_model1.brain_create_structural_authority_v2 import (
    ReviewedSemanticIndex,
    normalize_operator_text,
    reviewed_descriptor_filter_index,
)
from metis_model1.brain_create_surface import create_authority_history_revision
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    BoundDecision,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_output_contract import parse_create_quantity_surface
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_technical_authority import validate_technical_authority


def _unsupported(message: str) -> None:
    raise BrainError("CREATE_TYPED_AUTHORITY_UNSUPPORTED", 422, message)


def _procedural_text(message: str, decisions: tuple[BoundDecision, ...]) -> bool:
    # Share the resolver's existing lexical guards. Decisions, not phrases,
    # remain the authority; every clause must be completely accounted for.
    from metis_model1.brain_dialogue_planner import (
        _CHOICE_PREFIX,
        _normalize,
        _safe_assertion_statement,
        _safe_label,
    )

    labels = {
        _normalize(choice.label).removeprefix("@")
        for decision in decisions
        for choice in decision.choices
        if _safe_label(choice.label)
    }
    clauses = [part.strip() for part in re.split(r"[;,\n]", message) if part.strip()]
    if not clauses:
        return False
    for clause in clauses:
        if any(_integer_answer_text(clause, decision) for decision in decisions):
            continue
        if not _safe_assertion_statement(clause):
            return False
        value = _CHOICE_PREFIX.sub("", clause.strip().rstrip(".!"))
        normalized = _normalize(value).removeprefix("@")
        chunks = (
            [value] if normalized in labels else re.split(r"\s+(?:e|ed|and)\s+", value, flags=re.I)
        )
        if not chunks or any(_normalize(chunk).removeprefix("@") not in labels for chunk in chunks):
            return False
    return True


def _fresh_confirmation(decision: BoundDecision, dialogue: PrivateDialogueState) -> bool:
    if decision.binding.history_revision == dialogue.binding.history_revision:
        return True
    return (
        len(dialogue.messages) > 1
        and decision.binding.history_revision
        == create_authority_history_revision(dialogue.messages[:-1])
        and _procedural_text(dialogue.messages[-1].text, (decision,))
    )


def _integer_answer_text(message: str, decision: BoundDecision) -> bool:
    if decision.integer is None:
        return False
    normalized = normalize_operator_text(message)
    if normalized == str(decision.integer):
        return True
    if re.fullmatch(r"[a-z]+", normalized):
        message = normalized + " risultati"
    surface = parse_create_quantity_surface(message)
    return (
        surface.status == "resolved"
        and not surface.semantic_instruction.strip()
        and len(surface.mentions) == 1
        and surface.mentions[0].value == decision.integer
        and (
            surface.mentions[0].mode == decision.value_contract
            or re.fullmatch(r"[a-z]+", normalized) is not None
        )
    )


def _operation_request_revision(
    dialogue: PrivateDialogueState, *, through_revision: str | None = None
) -> str:
    """A new substantive utterance starts a new round, even before a Draft.

    Only an exact, already admitted answer immediately after its bound question
    is procedural. A message carrying an answer *and* new requirements is not.
    """
    latest = 1
    for index, message in enumerate(dialogue.messages):
        prefix = create_authority_history_revision(dialogue.messages[:index]) if index else None
        procedural = _procedural_text(
            message.text,
            tuple(
                decision
                for decision in dialogue.decisions
                if decision.binding.history_revision == prefix
            ),
        )
        if not procedural:
            latest = index + 1
        if through_revision == create_authority_history_revision(dialogue.messages[: index + 1]):
            return create_authority_history_revision(dialogue.messages[:latest])
    if through_revision is not None:
        raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "operation history is absent")
    return create_authority_history_revision(dialogue.messages[:latest])


class _Choices:
    def __init__(self, dialogue: PrivateDialogueState, scope: str) -> None:
        self.dialogue = dialogue
        self.scope = scope
        self.pending: list[QuestionSlot] = []
        self.used: list[str] = []

    def _prior(self, identity: tuple[str, str]) -> BoundDecision | None:
        found = [item for item in self.dialogue.decisions if item.identity == identity]
        return found[-1] if found else None

    def choice(
        self,
        key: str,
        question: str,
        options: list[tuple[str, str, str]],
        *,
        fresh: bool = False,
    ) -> str | None:
        if not options or len(options) > 64:
            _unsupported(
                "La scelta strutturale supera il limite leggibile: restringi la richiesta."
            )
        revision = canonical_sha256({"scope": self.scope, "key": key, "options": options})
        identity = (f"choice.general.{key}", f"general.{key}")
        choices = tuple(
            BoundChoice(
                label=label,
                authority_keys=(f"operation:{index}",),
                candidate_revision=revision,
                required_roles=("scalar",),
                description=description,
            )
            for index, (_, label, description) in enumerate(options)
        )
        prior = self._prior(identity)
        if prior is not None and (
            prior.kind == "structural_choice"
            and prior.answer_kind == "option_ref"
            and prior.value_contract == "authority"
            and len(prior.choices) == 1
            and (not fresh or _fresh_confirmation(prior, self.dialogue))
        ):
            selected = prior.choices[0]
            for index, expected in enumerate(choices):
                if (
                    selected.authority_keys == expected.authority_keys
                    and selected.candidate_revision == expected.candidate_revision
                    and selected.required_roles == expected.required_roles
                    and selected.label == expected.label
                    and selected.description == expected.description
                ):
                    self.used.append(prior.decision_sha256)
                    return options[index][0]
        self.pending.append(
            QuestionSlot(
                decision_key=identity[0],
                target_key=identity[1],
                kind="structural_choice",
                question=question,
                answer_kind="option_ref",
                choices=choices,
                supersedes=None if prior is None else prior.decision_sha256,
            )
        )
        return None

    def integer(self, key: str, question: str, *, contract: str, dependencies: Any) -> int | None:
        # Integer decisions have no candidate revision. Put the complete scope
        # and dependencies in their identity, preventing cross-generation reuse.
        scoped = canonical_sha256({"scope": self.scope, "key": key, "deps": dependencies})[7:31]
        quantity_scope = "page" if contract == "page_default" else "total"
        identity = (
            f"qty.result_count.{quantity_scope}.{contract}.any",
            f"general.{key}.{scoped}",
        )
        prior = self._prior(identity)
        if prior is not None and (
            prior.kind == "structural_choice"
            and prior.answer_kind == "integer"
            and prior.value_contract == contract
            and type(prior.integer) is int
            and 1 <= prior.integer <= 1000
        ):
            self.used.append(prior.decision_sha256)
            return prior.integer
        self.pending.append(
            QuestionSlot(
                decision_key=identity[0],
                target_key=identity[1],
                kind="structural_choice",
                question=question,
                answer_kind="integer",
                value_contract=contract,
                minimum=1,
                maximum=1000,
                supersedes=None if prior is None else prior.decision_sha256,
            )
        )
        return None

    def paged_choice(
        self, key: str, question: str, options: list[tuple[str, str, str]]
    ) -> str | None:
        """Browse the entire declared roster; never truncate it to a prefix."""
        if len(options) <= 64:
            return self.choice(key, question, options)
        if len(options) > 4096:
            _unsupported("Il numero di scelte supera il limite del contratto del catalogo.")
        pages = [options[start : start + 64] for start in range(0, len(options), 64)]
        page = self.choice(
            key + ".page",
            "Quale intervallo di scelte vuoi aprire?",
            [
                (
                    str(index),
                    f"Scelte {index * 64 + 1}-{index * 64 + len(items)}",
                    f"Da {items[0][1]} a {items[-1][1]}; nessuna scelta viene esclusa.",
                )
                for index, items in enumerate(pages)
            ],
        )
        if page is None:
            return None
        return self.choice(key, question, pages[int(page)])


@dataclass(frozen=True)
class DescriptorDialogueResult:
    slots: tuple[QuestionSlot, ...]
    authority: Any = None
    intent: Any = None


def prepare_descriptor_operation(
    *,
    base_spec: Mapping[str, Any],
    initial: bool,
    dialogue: PrivateDialogueState,
    retrieved: RetrievalResult,
    context_revision: str,
    semantic_revision: str,
    toolchain_binding: str,
    tenant_id: str,
    inventory_revision: str,
    policy_revision: str,
) -> DescriptorDialogueResult:
    from metis_model1.brain_create_descriptor_operations import (
        DescriptorOperationAuthority,
        build_descriptor_operation,
    )

    scope = canonical_sha256(
        {
            "contract": "metis-brain-descriptor-operation-dialogue/v1",
            "base": base_spec,
            "context": context_revision,
            "semantic": semantic_revision,
            "toolchain": toolchain_binding,
            "inventory": inventory_revision,
            "operation_request": _operation_request_revision(dialogue),
        }
    )
    q = _Choices(dialogue, scope)
    endpoint = base_spec.get("endpoint")
    if not isinstance(endpoint, Mapping) or not isinstance(endpoint.get("blocks"), list):
        _unsupported("La bozza non espone blocchi modificabili con questo contratto.")
    blocks = endpoint["blocks"]
    action_options = [
        (
            "add_filtered_block",
            "Aggiungi un blocco filtrato",
            "Nuovo blocco con i filtri revisionati del catalogo; preserva i blocchi esistenti.",
        ),
    ]
    if not endpoint.get("variants") and endpoint["params"]["paginate"] in {None, "offset"}:
        action_options.append(
            (
                "add_filtered_page",
                "Crea una pagina filtrata",
                "Take paginato nella risposta principale, non dentro un blocco riutilizzabile.",
            )
        )
    if blocks:
        action_options.extend(
            [
                (
                    "set_cardinality",
                    "Quantità totale",
                    "Modifica il numero totale di un solo take nel blocco.",
                ),
                (
                    "order_by_field",
                    "Ordinamento per campo",
                    "Aggiunge un criterio su un campo revisionato, dopo quelli esistenti.",
                ),
                (
                    "return_projection",
                    "Formato della risposta",
                    "Sceglie sul take un profilo di risposta dichiarato dal catalogo.",
                ),
                (
                    "similarity_from_input",
                    "Similarità a un contenuto in input",
                    "Input obbligatorio per l'identificativo, un solo record seed "
                    "e un profilo dichiarato dal catalogo.",
                ),
            ]
        )
        if len(blocks) > 1:
            action_options.append(
                (
                    "same_draft_fallback",
                    "Fallback verso un altro blocco",
                    "Destinazione nella stessa bozza; condizione e modalità scelte esplicitamente.",
                )
            )
    action = q.choice(
        "action",
        "Quale operazione vuoi applicare adesso? Le altre restano per un refinement.",
        action_options,
    )
    if action is None:
        return DescriptorDialogueResult(tuple(q.pending))
    operation: dict[str, Any] = {"kind": action}
    semantic: ReviewedSemanticIndex | None = None
    selected_labels: list[str] = []
    technical = None
    raw_technical = retrieved.context.get("technical_authority")
    if raw_technical is not None:
        technical = validate_technical_authority(
            raw_technical,
            context_revision=context_revision,
            semantic_source_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
            tenant_id=tenant_id,
        )

    if action in {"add_filtered_block", "add_filtered_page"}:
        semantic = reviewed_descriptor_filter_index(
            retrieved=retrieved,
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
        )
        selected_labels.append(
            f"Catalogo {semantic.catalog}; filtri in AND: "
            + "; ".join(
                f"{field} = "
                + " oppure ".join(json.dumps(value, ensure_ascii=False) for value in values)
                for field, values in semantic.selected_values
            )
        )
    else:
        need_fetch = action in {
            "set_cardinality",
            "order_by_field",
            "similarity_from_input",
            "return_projection",
        }
        targets: list[tuple[str, str, str]] = []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                continue
            name = str(block.get("name", block_index))
            if need_fetch:
                for fetch_index, fetch in enumerate(block.get("fetches", [])):
                    source = fetch.get("from", {})
                    if source.get("kind") == "catalog":
                        targets.append(
                            (
                                f"{block_index}:{fetch_index}",
                                f"{name} take {fetch_index + 1}",
                                f"Catalogo @{source.get('catalog')}. Gli altri take non cambiano.",
                            )
                        )
            else:
                targets.append(
                    (str(block_index), name, "Modifica soltanto l'output di questo blocco.")
                )
        target = q.paged_choice("target", "Su quale parte della bozza vuoi intervenire?", targets)
        if target is None:
            return DescriptorDialogueResult(tuple(q.pending))
        indices = target.split(":")
        operation["block_index"] = int(indices[0])
        if need_fetch:
            operation["fetch_index"] = int(indices[1])
        selected_labels.append(next(label for value, label, _ in targets if value == target))

    if action in {"add_filtered_block", "add_filtered_page", "set_cardinality"}:
        mode = "page_default" if action == "add_filtered_page" else "total"
        count = q.integer(
            "count",
            "Quanti risultati totali?"
            if mode == "total"
            else "Quale dimensione predefinita della pagina?",
            contract=mode,
            dependencies={**operation, "mode": mode},
        )
        if count is not None:
            operation.update(count=count)
            if action != "add_filtered_page":
                operation["mode"] = mode
            selected_labels.append(
                f"{count} risultati totali"
                if mode == "total"
                else f"Paginazione con dimensione predefinita {count}"
            )
    elif action in {"order_by_field", "similarity_from_input", "return_projection"}:
        if technical is None:
            _unsupported(
                "Manca la proiezione tecnica verificata; nessun ruolo viene dedotto dal nome."
            )
        fetch = blocks[operation["block_index"]]["fetches"][operation["fetch_index"]]
        short_name = fetch["from"]["catalog"]
        catalogs = [
            entry
            for entry in technical["catalogs"]
            if entry["name"].rsplit(".", 1)[-1] == short_name
        ]
        if len(catalogs) != 1:
            _unsupported("L'identità del catalogo della bozza è ambigua.")
        catalog = catalogs[0]
        context_catalog = retrieved.context.get("catalog", {})
        if (
            context_catalog.get("name") != catalog["name"]
            or context_catalog.get("semantic", {}).get("state") != "reviewed"
        ):
            _unsupported("Seleziona il catalogo revisionato del take da modificare.")
        if action == "order_by_field":
            fields = {
                field["name"]: field
                for field in retrieved.context.get("fields", [])
                if field.get("semantic", {}).get("state") == "reviewed"
            }
            options = []
            for field in catalog["fields"]:
                name = field["name"]
                if (
                    name in fields
                    and "." not in name
                    and not field["modifiers"]
                    and field["type"] in {"keyword", "number", "date", "boolean"}
                ):
                    description = fields[name].get("semantic", {}).get("means")
                    if isinstance(description, Mapping):
                        description = description.get("text")
                    if not isinstance(description, str) or not description.strip():
                        description = (
                            f"Campo revisionato {name} ({field['type']}). "
                            "Sceglierlo non gli attribuisce altri ruoli."
                        )
                    options.append((name, name, description[:500]))
            field = q.paged_choice(
                "order_field", "Quale campo deve guidare l'ordinamento?", options
            )
            direction = q.choice(
                "order_direction",
                "In quale direzione?",
                [
                    ("ascending", "Crescente", "Valori minori prima."),
                    ("descending", "Decrescente", "Valori maggiori prima."),
                ],
            )
            if field is not None and direction is not None:
                operation.update(field=field, direction=direction)
                selected_labels.append(
                    f"Aggiungi ordinamento {field} {direction} dopo i criteri esistenti"
                )
        elif action == "return_projection":
            projection = q.paged_choice(
                "projection",
                "Quale profilo dichiarato deve restituire questo take?",
                [
                    (item["name"], item["name"], "Campi restituiti: " + ", ".join(item["fields"]))
                    for item in catalog["projections"]
                ],
            )
            if projection is not None:
                operation["projection"] = projection
                selected_labels.append(f"Profilo di risposta dichiarato {projection}")
        else:
            profile = q.paged_choice(
                "profile",
                "Quale profilo dichiarato vuoi usare? Confermi anche l'input obbligatorio "
                "per l'identificativo del contenuto seed?",
                [
                    (
                        profile["name"],
                        profile["name"],
                        "Campi dichiarati: "
                        + ", ".join(profile["fields"])
                        + ". L'identificativo sarà fornito dal chiamante, non inventato da Brain.",
                    )
                    for profile in catalog["similarity_profiles"]
                ],
            )
            if profile is not None:
                operation["profile"] = profile
                selected_labels.append(
                    f"Similarità con profilo {profile}; "
                    "nuovo input obbligatorio, seed singolo dal catalogo"
                )
    elif action == "same_draft_fallback":
        target = q.choice(
            "fallback_target",
            "Quale blocco della bozza deve fornire il fallback?",
            [
                (
                    str(index),
                    str(block["name"]),
                    "Destinazione locale alla bozza; non viene eseguito un endpoint esterno.",
                )
                for index, block in enumerate(blocks)
                if index != operation["block_index"]
            ],
        )
        trigger = q.choice(
            "fallback_trigger",
            "Quando deve intervenire?",
            [
                (
                    "empty",
                    "Risultati assenti",
                    "Interviene se il blocco restituisce zero risultati.",
                ),
                (
                    "below",
                    "Sotto una soglia",
                    "Interviene quando il numero di risultati è inferiore alla soglia specificata.",
                ),
            ],
        )
        mode = q.choice(
            "fallback_mode",
            "Come deve essere usato il risultato di riserva?",
            [
                ("substitute", "Sostituisci", "Sostituisce il risultato del blocco."),
                ("append", "Aggiungi in coda", "Accoda i risultati del blocco di riserva."),
            ],
        )
        if target is not None and trigger is not None and mode is not None:
            operation.update(target_index=int(target), trigger=trigger, mode=mode)
            if trigger == "below":
                threshold = q.integer(
                    "threshold",
                    "Sotto quanti risultati deve intervenire?",
                    contract="total",
                    dependencies=operation,
                )
                if threshold is not None:
                    operation["threshold"] = threshold
            selected_labels.append(
                f"Fallback verso {blocks[int(target)]['name']}; {trigger}, {mode}"
                + (f", soglia {operation['threshold']}" if "threshold" in operation else "")
            )
    if q.pending:
        return DescriptorDialogueResult(tuple(q.pending))

    authority = DescriptorOperationAuthority(
        base_spec=base_spec,
        operation=operation,
        semantic=semantic,
        retrieved=retrieved,
        context_revision=context_revision,
        semantic_revision=semantic_revision,
        toolchain_binding=toolchain_binding,
        tenant_id=tenant_id,
        decision_revision=canonical_sha256(
            {"scope": scope, "operation": operation, "decisions": q.used}
        ),
    )
    intent = build_descriptor_operation(authority, policy_revision=policy_revision)
    summary = (
        ". ".join(selected_labels)
        + ". Applica SOLO questa operazione. Tutto il resto della bozza resta invariato; "
        "eventuali altri requisiti richiedono un refinement."
    )
    if len(summary.encode("utf-8")) > 1024:
        _unsupported("La conferma supera il limite leggibile: restringi l'operazione.")
    confirmed = q.choice(
        "confirm",
        "Confermi esattamente questa operazione prima della compilazione?",
        [
            ("yes", "Confermo questa operazione", summary),
            (
                "no",
                "Annulla operazione",
                "Non genera una proposta. Specifica una nuova richiesta o correggi le scelte.",
            ),
        ],
        fresh=True,
    )
    if confirmed is None:
        return DescriptorDialogueResult(tuple(q.pending))
    if confirmed != "yes":
        _unsupported("Operazione non confermata: nessuna proposta generata.")
    return DescriptorDialogueResult((), authority, intent)
