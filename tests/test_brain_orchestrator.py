from __future__ import annotations

import threading
import unicodedata
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_output_contract import parse_output_request
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_turns import TurnRecord, TurnRequest

_SESSION_ID = "s" * 32
_TURN_ID = "t" * 24


def _request(
    context: str,
    semantic: str,
    clarification=None,
    *,
    instruction: str = "crea un endpoint",
    schema_version: int = 1,
    target: dict | None = None,
) -> TurnRequest:
    return TurnRequest(
        schema_version,
        "123e4567-e89b-12d3-a456-426614174000",
        context,
        semantic,
        "create",
        instruction,
        target
        or {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        None,
        clarification,
    )


def test_catalog_selection_requires_explicit_revision_bound_option() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    candidates = (
        {"catalog": "video", "label": "Video", "option_ref": "option-video"},
        {"catalog": "trending", "label": "Tendenze", "option_ref": "option-trending"},
    )
    retrieved = RetrievalResult({}, {}, semantic, candidates)
    request = _request(context, semantic, schema_version=2)
    assert BrainOrchestrator._selected_catalog(request, retrieved) is None
    response = {"kind": "catalog", "resolved_value": "video"}
    assert (
        BrainOrchestrator._selected_catalog(
            _request(context, semantic).with_server_clarification(response), retrieved
        )
        == candidates[0]
    )


def test_catalog_clarification_preserves_legacy_public_catalog_field() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(context, semantic, schema_version=1)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = RetrievalResult(
        {"semantic_schema": 2},
        {},
        semantic,
        (
            {"catalog": "video", "label": "Video", "description": "Contenuti video"},
            {"catalog": "users", "label": "Utenti", "description": "Profili utente"},
        ),
    )

    terminal = BrainOrchestrator(
        retriever=SimpleNamespace(),
        model=SimpleNamespace(),
        compiler=SimpleNamespace(),
    )._catalog_clarification(
        session_id=_SESSION_ID,
        record=record,
        request=request,
        retrieved=retrieved,
    )

    assert terminal["schema_version"] == 1
    assert [
        {key: item[key] for key in ("catalog", "label", "description")}
        for item in terminal["clarification"]["options"]
    ] == [
        {"catalog": "video", "label": "Video", "description": "Contenuti video"},
        {"catalog": "users", "label": "Utenti", "description": "Profili utente"},
    ]
    assert all(
        "value" not in item and "resolved_value" not in item
        for item in terminal["clarification"]["options"]
    )


def test_stale_semantic_revision_fails_closed() -> None:
    context = "sha256:" + "a" * 64
    request = _request(context, "sha256:" + "b" * 64)
    retrieved = RetrievalResult({}, {}, "sha256:" + "c" * 64)
    with pytest.raises(BrainError) as raised:
        BrainOrchestrator._check_semantic_revision(request, retrieved)
    assert raised.value.code == "SEMANTIC_SOURCE_STALE"


def test_omitted_count_asks_for_total_cardinality_once() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(context, semantic, schema_version=2)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = _grounded_retrieval(context, semantic)
    retrieved.context["semantic_schema"] = 2
    orchestrator = BrainOrchestrator(
        retriever=SimpleNamespace(),
        model=SimpleNamespace(),
        compiler=SimpleNamespace(),
    )

    result = orchestrator._prepare_output_contract(
        session_id=_SESSION_ID,
        record=record,
        request=request,
        retrieved=retrieved,
    )
    assert result is not None
    assert result["outcome"] == "needs_clarification"
    assert result["schema_version"] == 2
    assert result["clarification"]["kind"] == "result_count"
    assert result["clarification"]["question"] == "Quanti risultati complessivi vuoi?"
    assert result["session_memory"]["assumptions"] == []


def test_quantifier_bound_to_results_asks_for_exact_total() -> None:
    terminal = _output_contract_for("crea pochi risultati")
    assert terminal["outcome"] == "needs_clarification"
    assert terminal["clarification"]["kind"] == "result_count"


def test_schema_one_never_receives_unrepresentable_numeric_clarification() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(context, semantic, schema_version=1)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = _grounded_retrieval(context, semantic)
    retrieved.context["semantic_schema"] = 2

    result = BrainOrchestrator(
        retriever=SimpleNamespace(),
        model=SimpleNamespace(),
        compiler=SimpleNamespace(),
    )._prepare_output_contract(
        session_id=_SESSION_ID,
        record=record,
        request=request,
        retrieved=retrieved,
    )
    assert result is None
    assert "output_contract" not in retrieved.grounding


def _output_contract_for(
    instruction: str,
    *,
    decision: dict | None = None,
    target: dict | None = None,
    previous_source: str | None = None,
    basis_grounding: dict | None = None,
) -> dict | None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(
        context,
        semantic,
        instruction=instruction,
        schema_version=2,
        target=target,
    )
    if decision is not None:
        request = request.with_server_clarification(decision)
    if basis_grounding is not None:
        request = request.with_server_basis_grounding(basis_grounding)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = _grounded_retrieval(context, semantic)
    retrieved.context["semantic_schema"] = 2
    result = BrainOrchestrator(
        retriever=SimpleNamespace(),
        model=SimpleNamespace(),
        compiler=SimpleNamespace(),
    )._prepare_output_contract(
        session_id=_SESSION_ID,
        record=record,
        request=request,
        retrieved=retrieved,
        previous_source=previous_source,
    )
    return result if result is not None else retrieved.grounding["output_contract"]


def test_exact_total_emits_take_n_contract_without_pagination() -> None:
    contract = _output_contract_for("crea un endpoint con 24 risultati")
    assert set(contract) == {"take", "fallback"}
    assert contract["take"] == {
        "mode": "count",
        "value": 24,
        "source": "operator_confirmed",
    }
    assert contract["fallback"] == {"mode": "none"}


@pytest.mark.parametrize(
    "instruction",
    ["crea 24 film per pagina", "crea 24 contenuti per pagina", "crea 24 video per pagina"],
)
def test_explicit_page_size_is_pagination_only(instruction: str) -> None:
    contract = _output_contract_for(instruction)
    assert contract["take"] == {
        "mode": "page",
        "page_size": {
            "mode": "local_default",
            "value": 24,
            "source": "operator_confirmed",
        },
    }


def test_mixed_total_and_pagination_requires_shape_confirmation() -> None:
    terminal = _output_contract_for("crea 24 risultati paginati")
    assert terminal["outcome"] == "needs_clarification"
    clarification = terminal["clarification"]
    assert clarification["kind"] == "response_shape"
    assert clarification["question"] == "Il numero 24 indica il totale o i risultati per pagina?"
    assert [option["label"] for option in clarification["options"]] == [
        "24 risultati complessivi",
        "24 risultati per pagina",
    ]


@pytest.mark.parametrize(
    "decision, expected",
    [
        (
            {"kind": "response_shape", "resolved_value": "count:24"},
            {"mode": "count", "value": 24, "source": "operator_confirmed"},
        ),
        (
            {"kind": "response_shape", "resolved_value": "page:24"},
            {
                "mode": "page",
                "page_size": {
                    "mode": "local_default",
                    "value": 24,
                    "source": "operator_confirmed",
                },
            },
        ),
    ],
)
def test_confirmed_shape_preserves_exact_count_semantics(decision: dict, expected: dict) -> None:
    contract = _output_contract_for("crea 24 risultati paginati", decision=decision)
    assert contract["take"] == expected


@pytest.mark.parametrize(
    ("instruction", "labels"),
    [
        (
            "crea 24 risultati e 30 contenuti",
            ["24 risultati complessivi", "30 risultati complessivi"],
        ),
        (
            "crea 24 film, 10 per pagina",
            ["24 risultati complessivi", "10 risultati per pagina"],
        ),
        (
            "crea 24 risultati per pagina e 30 risultati per pagina",
            ["24 risultati per pagina", "30 risultati per pagina"],
        ),
    ],
)
def test_multiple_explicit_cardinalities_require_one_real_choice(
    instruction: str, labels: list[str]
) -> None:
    terminal = _output_contract_for(instruction)
    assert terminal["outcome"] == "needs_clarification"
    assert terminal["clarification"]["kind"] == "response_shape"
    assert terminal["clarification"]["question"] == (
        "Hai indicato più cardinalità: quale vuoi applicare?"
    )
    assert [item["label"] for item in terminal["clarification"]["options"]] == labels
    assert terminal["session_memory"]["assumptions"] == []


def test_multiple_cardinality_choice_replays_exact_selected_contract() -> None:
    contract = _output_contract_for(
        "crea 24 film, 10 per pagina",
        decision={"kind": "response_shape", "resolved_value": "page:10"},
    )
    assert contract["take"] == {
        "mode": "page",
        "page_size": {
            "mode": "local_default",
            "value": 10,
            "source": "operator_confirmed",
        },
    }


def test_multiple_totals_with_unbound_pagination_fail_closed() -> None:
    with pytest.raises(BrainError) as raised:
        _output_contract_for("crea 24 risultati e 30 contenuti paginati")
    assert raised.value.code == "OUTPUT_CONTRACT_AMBIGUOUS"


def test_structural_count_command_is_an_exact_total_contract() -> None:
    contract = _output_contract_for("porta il numero di risultati a 30")
    assert contract["take"] == {
        "mode": "count",
        "value": 30,
        "source": "operator_confirmed",
    }


@pytest.mark.parametrize(
    "historical_decision",
    [
        {
            "kind": "result_count",
            "answer": {"integer": 24},
            "resolved_value": None,
        },
        {
            "kind": "response_shape",
            "resolved_value": "page:24",
        },
    ],
)
def test_explicit_refinement_count_overrides_historical_output_decision(
    historical_decision: dict,
) -> None:
    contract = _output_contract_for(
        "porta il numero di risultati a 30",
        decision={"decisions": [historical_decision]},
        basis_grounding={
            "output_contract": {
                "take": {
                    "mode": "count",
                    "value": 24,
                    "source": "operator_confirmed",
                }
            }
        },
    )
    assert contract["take"] == {
        "mode": "count",
        "value": 30,
        "source": "operator_confirmed",
    }


def test_current_output_decision_remains_authoritative_inside_conversation_context() -> None:
    current = {
        "kind": "response_shape",
        "resolved_value": "page:24",
    }
    contract = _output_contract_for(
        "crea 24 risultati paginati",
        decision={"decisions": [current], "current_decision": current},
    )
    assert contract["take"] == {
        "mode": "page",
        "page_size": {
            "mode": "local_default",
            "value": 24,
            "source": "operator_confirmed",
        },
    }


@pytest.mark.parametrize(
    ("instruction", "mode"),
    [
        ("crea Film tra 20 e 30 risultati", "count"),
        ("crea Film fra 20 e 30 risultati", "count"),
        ("crea Film da 20 a 30 risultati", "count"),
        ("crea Film 20 oppure 30 risultati", "count"),
        ("crea Film 20 o 30 risultati", "count"),
        ("crea Film 20/30 risultati", "count"),
        ("crea Film 20-30 risultati", "count"),
        ("crea Film tra 20 e 30 risultati per pagina", "page"),
        ("crea Film 20 oppure 30 risultati per pagina", "page"),
        ("crea Film tra 20 e 30 per pagina", "page"),
        ("crea Film fra 20 e 30 per pagina", "page"),
        ("crea Film da 20 a 30 per pagina", "page"),
        ("crea Film 20 o 30 per pagina", "page"),
        ("crea Film 20 oppure 30 per pagina", "page"),
        ("crea Film 20/30 per pagina", "page"),
    ],
)
def test_range_or_alternative_cardinality_requires_explicit_choice(
    instruction: str,
    mode: str,
) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ((mode, 20), (mode, 30))
    terminal = _output_contract_for(instruction)
    assert terminal["outcome"] == "needs_clarification"
    assert terminal["clarification"]["kind"] == "response_shape"
    assert len(terminal["clarification"]["options"]) == 2


@pytest.mark.parametrize(
    "instruction",
    [
        "crea Film da circa 20 a 30 risultati",
        "crea Film tra almeno 20 e 30 risultati",
        "crea Film fra 20 e massimo 30 per pagina",
    ],
)
def test_qualified_range_never_becomes_an_exact_upper_bound(instruction: str) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.invalid_numeric_output is True
    with pytest.raises(BrainError) as raised:
        _output_contract_for(instruction)
    assert raised.value.code == "OUTPUT_CONTRACT_INVALID"


def _existing_target(endpoint: str = "demo.target") -> dict[str, object]:
    return {
        "mode": "existing",
        "relative_path": "endpoints/existing.metis",
        "endpoint": endpoint,
        "base_sha256": "sha256:" + "c" * 64,
    }


@pytest.mark.parametrize(
    ("take_source", "expected"),
    [
        (
            "take 24 from @play-demo.video",
            {"mode": "count", "value": 24, "source": "existing_source"},
        ),
        (
            "take page default 20 from @play-demo.video",
            {
                "mode": "page",
                "page_size": {
                    "mode": "local_default",
                    "value": 20,
                    "source": "existing_source",
                },
            },
        ),
        (
            "take page from @play-demo.video",
            {"mode": "page", "page_size": {"mode": "tenant"}},
        ),
    ],
)
def test_existing_endpoint_preserves_pinned_take_without_asking(
    take_source: str, expected: dict
) -> None:
    source = f"""metis 0.43
endpoint demo.other {{ take 9 from @play-demo.video }}
endpoint demo.target as "Target" {{
  {take_source}
  return response.expanded
}}
"""
    contract = _output_contract_for(
        "modifica il filtro del mio endpoint",
        target=_existing_target(),
        previous_source=source,
    )
    assert contract["take"] == expected


def test_existing_endpoint_explicit_count_overrides_pinned_take() -> None:
    source = """endpoint demo.target {
  take page default 20 from @play-demo.video
}
"""
    contract = _output_contract_for(
        "modifica il filtro e restituisci 30 risultati",
        target=_existing_target(),
        previous_source=source,
    )
    assert contract["take"] == {
        "mode": "count",
        "value": 30,
        "source": "operator_confirmed",
    }


def test_existing_endpoint_fallback_is_never_silently_removed() -> None:
    source = """endpoint demo.target {
  take 20 from @play-demo.video
  return response fallback to block.empty when empty
}
"""
    with pytest.raises(BrainError) as raised:
        _output_contract_for(
            "rendi più chiara l'etichetta dell'endpoint",
            target=_existing_target(),
            previous_source=source,
        )
    assert raised.value.code == "OUTPUT_CONTRACT_UNAVAILABLE"


def test_proposal_basis_fallback_is_never_relabelled_as_none() -> None:
    with pytest.raises(BrainError) as raised:
        _output_contract_for(
            "rendi più chiara l'etichetta dell'endpoint",
            basis_grounding={
                "output_contract": {
                    "take": {
                        "mode": "count",
                        "value": 20,
                        "source": "operator_confirmed",
                    },
                    "fallback": {"mode": "preserve"},
                }
            },
        )
    assert raised.value.code == "OUTPUT_CONTRACT_UNAVAILABLE"


@pytest.mark.parametrize(
    "take",
    [
        {"mode": "count", "value": 24, "source": "existing_source"},
        {
            "mode": "page",
            "page_size": {
                "mode": "local_default",
                "value": 20,
                "source": "existing_source",
            },
        },
    ],
)
def test_refinement_preserves_existing_source_authority_without_relabelling(
    take: dict,
) -> None:
    contract = _output_contract_for(
        "rendi più chiara l'etichetta dell'endpoint",
        basis_grounding={"output_contract": {"take": take}},
    )
    assert contract["take"] == take


@pytest.mark.parametrize(
    "instruction",
    [
        'rinomina l\'endpoint in "24 film"',
        "rinomina l'endpoint in “24 video”",
        "rinomina l'endpoint in «24 risultati per pagina»",
    ],
)
def test_quoted_endpoint_label_never_becomes_an_output_contract(instruction: str) -> None:
    prior = {"mode": "count", "value": 30, "source": "operator_confirmed"}
    contract = _output_contract_for(
        instruction,
        basis_grounding={"output_contract": {"take": prior}},
    )
    assert contract["take"] == prior


@pytest.mark.parametrize(
    "instruction",
    [
        "rinomina l'endpoint in '24 risultati'",
        "rinomina l’endpoint in ‘24 risultati’",
        "scrivi ‹24 risultati› nell'etichetta",
        "usa la stringa `24 risultati`",
        "usa il blocco ```24 risultati```",
    ],
)
def test_single_quotes_and_code_spans_never_authorize_cardinality(
    instruction: str,
) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.generic_pagination is False
    assert parsed.semantic_instruction == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        "crea Film senza paginazione",
        "crea Film non paginato",
        "crea Film, non 24 risultati",
        "crea Film senza 24 risultati",
        "crea Film, non voglio 24 risultati",
        "crea Film, non avere 24 risultati",
        "crea Film, non restituire 24 risultati",
        "crea Film, al massimo 24 risultati",
        "crea Film, fino a 24 risultati",
        "crea Film, non oltre 24 risultati",
        "crea Film, oltre 24 risultati",
        "crea Film, massimo 24 risultati",
        "crea Film, minimo 24 risultati",
        "crea Film, entro 24 risultati",
        "crea Film, non superiore a 24 risultati",
        "crea Film, non inferiore a 24 risultati",
        "crea Film, più o meno 24 risultati",
        "crea Film, approssimativamente 24 risultati",
        "crea Film, indicativamente 24 risultati",
        "crea Film, intorno a 24 risultati",
        "crea Film, sopra 24 risultati",
        "crea Film, sotto 24 risultati",
        "crea Film, non più di 24 risultati",
        "crea Film, non esattamente 24 risultati",
        "imposta il limite di 24 risultati",
        "fissa il limite di 24 risultati",
        "porta il limite a 24 risultati",
        "imposta il limite massimo a 24 risultati",
        "crea Film, 24 risultati al massimo",
        "crea Film, 24 risultati o meno",
        "crea Film, oltre 24 risultati per pagina",
        "crea Film, 24 risultati al massimo per pagina",
    ],
)
def test_negated_output_language_is_never_positive_authority(instruction: str) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.generic_pagination is False
    assert parsed.semantic_instruction == instruction


@pytest.mark.parametrize(
    "instruction",
    ["crea 24 pagine", "crea la prima pagina", "rinomina in pagina principale"],
)
def test_document_page_wording_does_not_enable_result_pagination(instruction: str) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.generic_pagination is False


def test_all_unicode_signlike_prefixes_fail_closed() -> None:
    signs = tuple(
        chr(codepoint)
        for codepoint in range(0x110000)
        if unicodedata.category(chr(codepoint)) == "Pd"
        or any(
            marker in unicodedata.name(chr(codepoint), "") for marker in ("PLUS", "MINUS", "HYPHEN")
        )
    )
    assert len(signs) >= 80
    failures: list[str] = []
    for sign in signs:
        for template in (
            "crea Film {sign}5 risultati",
            "crea Film {sign}5 per pagina",
            "crea Film pagina da {sign}5",
        ):
            parsed = parse_output_request(template.format(sign=sign))
            if parsed.contracts or not parsed.invalid_numeric_output:
                failures.append(f"U+{ord(sign):04X}:{template}")
    assert failures == []


@pytest.mark.parametrize(
    "instruction",
    ["crea Film pagina da 024", "crea Film pagina da 10000", "crea Film pagina 24"],
)
def test_malformed_numeric_pagination_never_degrades_to_tenant_page(
    instruction: str,
) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.invalid_numeric_pagination is True
    with pytest.raises(BrainError) as raised:
        _output_contract_for(instruction)
    assert raised.value.code == "OUTPUT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    "instruction",
    [
        "crea Film -5 risultati",
        "crea Film +5 risultati",
        "crea Film −5 risultati",
        "crea Film –5 risultati",
        "crea Film —5 risultati",
        "crea Film ‐5 risultati",
        "crea Film ‑5 risultati",
        "crea Film ‒5 risultati",
        "crea Film ―5 risultati",
        "crea Film ⁻5 risultati",
        "crea Film ₋5 risultati",
        "crea Film ﹣5 risultati",
        "crea Film －5 risultati",
        "crea Film ＋5 risultati",
        "crea Film .5 risultati",
        "crea Film 0,5 risultati",
        "crea Film -5 risultati per pagina",
        "crea Film +5 per pagina",
        "crea Film −5 per pagina",
        "crea Film –5 per pagina",
        "crea Film —5 per pagina",
        "crea Film ‐5 per pagina",
        "crea Film ‑5 per pagina",
        "crea Film ‒5 per pagina",
        "crea Film ―5 per pagina",
        "crea Film ⁻5 per pagina",
        "crea Film ₋5 per pagina",
        "crea Film ﹣5 per pagina",
        "crea Film －5 per pagina",
        "crea Film ＋5 per pagina",
        "crea Film .5 risultati per pagina",
        "crea Film pagina da -5",
        "crea Film pagina da −5",
        "crea Film pagina da –5",
        "crea Film pagina da —5",
        "crea Film pagina da ‐5",
        "crea Film pagina da ‑5",
        "crea Film pagina da ‒5",
        "crea Film pagina da ―5",
        "crea Film pagina da ⁻5",
        "crea Film pagina da ₋5",
        "crea Film pagina da ﹣5",
        "crea Film pagina da －5",
        "crea Film pagina da ＋5",
    ],
)
def test_signed_or_fractional_counts_are_never_unsigned_authority(
    instruction: str,
) -> None:
    parsed = parse_output_request(instruction)
    assert parsed.contracts == ()
    assert parsed.invalid_numeric_output is True
    with pytest.raises(BrainError) as raised:
        _output_contract_for(instruction)
    assert raised.value.code == "OUTPUT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    "source",
    [
        "endpoint demo.other { take 20 from @play-demo.video }",
        "endpoint demo.target { return response.expanded }",
        """endpoint demo.target { take 20 from @play-demo.video }
endpoint demo.target { take 20 from @play-demo.video }
""",
    ],
)
def test_existing_endpoint_without_unique_take_fails_instead_of_asking(source: str) -> None:
    with pytest.raises(BrainError) as raised:
        _output_contract_for(
            "modifica il filtro del mio endpoint",
            target=_existing_target(),
            previous_source=source,
        )
    assert raised.value.code == "OUTPUT_CONTRACT_UNAVAILABLE"


@pytest.mark.parametrize(
    "take_source",
    [
        "take 1001 from @play-demo.video",
        "take 10000 from @play-demo.video",
        "take page default 1001 from @play-demo.video",
    ],
)
def test_existing_endpoint_take_cannot_bypass_global_safe_bound(take_source: str) -> None:
    source = f"""endpoint demo.target {{
  {take_source}
}}
"""
    with pytest.raises(BrainError) as raised:
        _output_contract_for(
            "modifica il filtro del mio endpoint",
            target=_existing_target(),
            previous_source=source,
        )
    assert raised.value.code == "RESULT_COUNT_OUT_OF_RANGE"


def test_proposal_basis_take_cannot_bypass_global_safe_bound() -> None:
    with pytest.raises(BrainError) as raised:
        _output_contract_for(
            "rendi più chiara l'etichetta dell'endpoint",
            basis_grounding={
                "output_contract": {
                    "take": {
                        "mode": "count",
                        "value": 1001,
                        "source": "existing_source",
                    }
                }
            },
        )
    assert raised.value.code == "RESULT_COUNT_OUT_OF_RANGE"


@pytest.mark.parametrize(
    "instruction, decision",
    [
        ("crea 1001 risultati paginati", None),
        (
            "crea risultati paginati",
            {"kind": "response_shape", "resolved_value": "count:1001"},
        ),
        (
            "crea risultati paginati",
            {"kind": "response_shape", "resolved_value": "page:1001"},
        ),
    ],
)
def test_output_count_bound_cannot_be_bypassed_by_shape_decision(
    instruction: str, decision: dict | None
) -> None:
    with pytest.raises(BrainError) as raised:
        _output_contract_for(instruction, decision=decision)
    assert raised.value.code == "RESULT_COUNT_OUT_OF_RANGE"


class _FakeManager:
    def __init__(self, lease: object) -> None:
        self.lease = lease

    @contextmanager
    def operation(self, **_kwargs: object):
        yield self.lease


class _SequenceModel:
    model_revision = "model-test"
    adapter_sha256 = "adapter-test"

    def __init__(
        self,
        sources: list[str],
        *,
        metrics: dict[str, int | float | str] | None = None,
    ) -> None:
        self.sources = iter(sources)
        self.requests = []
        self.metrics = metrics or {}

    def generate(self, request: object) -> ModelCandidate:
        self.requests.append(request)
        return ModelCandidate(
            next(self.sources),
            self.model_revision,
            self.adapter_sha256,
            metrics=self.metrics,
        )


class _CountingCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self, status: str = "ok") -> None:
        self.calls = 0
        self.status = status

    def compile(self, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        return {"status": self.status, "toolchain_binding": self.toolchain_binding}


def _grounded_retrieval(context: str, semantic: str) -> RetrievalResult:
    return RetrievalResult(
        context={},
        grounding={
            "status": "resolved",
            "catalogs": ["play-demo.video"],
            "selections": [
                {
                    "catalog": "play-demo.video",
                    "field": "paesiorigine",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                    "literal": None,
                    "literals": ["ITALIA", "italia"],
                    "value_mode": "any_of",
                }
            ],
            "candidates": [],
            "unresolved": [],
        },
        semantic_source_revision=semantic,
        catalog_candidates=({"catalog": "play-demo.video"},),
    )


def _run_with_model(
    model: _SequenceModel, compiler: _CountingCompiler, *, max_repairs: int
) -> dict:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(context, semantic)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    lease = SimpleNamespace(
        snapshot=SimpleNamespace(source_map=lambda: {}),
        cancellation=threading.Event(),
    )
    return BrainOrchestrator(
        retriever=SimpleNamespace(
            retrieve=lambda **_kwargs: _grounded_retrieval(context, semantic)
        ),
        model=model,
        compiler=compiler,
        max_repairs=max_repairs,
    ).run(
        manager=_FakeManager(lease),
        session_id=_SESSION_ID,
        token="token-test",
        request=request,
        record=record,
    )


def test_reviewed_finite_create_skips_model_but_still_compiles() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(
        context,
        semantic,
        instruction="crea un endpoint con 24 risultati",
        schema_version=2,
        target={
            "mode": "create",
            "relative_path": "brain-drafts/film_italiani.metis",
            "endpoint": "demo.film_italiani",
            "base_sha256": None,
        },
    )
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = _grounded_retrieval(context, semantic)
    retrieved.context.update(
        {
            "semantic_schema": 2,
            "language_version": "0.43",
            "context_revision": context,
            "semantic_source_revision": semantic,
            "toolchain_binding": "sha256:" + "a" * 64,
            "catalog": {
                "name": "play-demo.video",
                "semantic": {"state": "reviewed"},
            },
            "fields": [
                {
                    "name": "paesiorigine",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                    "semantic": {"state": "reviewed"},
                    "values": [
                        {"literal": "ITALIA", "semantic": {"state": "reviewed"}},
                        {"literal": "italia", "semantic": {"state": "reviewed"}},
                    ],
                }
            ],
        }
    )
    model = _SequenceModel([])
    compiler = _CountingCompiler()
    lease = SimpleNamespace(
        snapshot=SimpleNamespace(source_map=lambda: {}),
        cancellation=threading.Event(),
    )

    result = BrainOrchestrator(
        retriever=SimpleNamespace(retrieve=lambda **_kwargs: retrieved),
        model=model,
        compiler=compiler,
    ).run(
        manager=_FakeManager(lease),
        session_id=_SESSION_ID,
        token="token-test",
        request=request,
        record=record,
    )

    assert result["outcome"] == "proposed"
    assert result["identity"]["generation_strategy"] == "grounded_renderer"
    assert "take 24 from @play-demo.video" in result["proposal"]["source"]
    assert model.requests == []
    assert compiler.calls == 1
    completed = {
        event["event"]: event["data"]
        for event in record.events
        if event["event"].endswith(".completed")
    }
    for event_name in ("retrieval.completed", "inference.completed", "compile.completed"):
        assert type(completed[event_name]["duration_ms"]) is int
        assert completed[event_name]["duration_ms"] >= 0


def test_model_generation_metrics_are_preserved_in_proposal_identity() -> None:
    metrics: dict[str, int | float | str] = {
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 0,
        "prompt_tps": 100.0,
        "generation_tps": 2.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }
    model = _SequenceModel(
        ['@paesiorigine in ["ITALIA", "italia"]'],
        metrics=metrics,
    )
    result = _run_with_model(model, _CountingCompiler(), max_repairs=0)

    assert result["identity"]["generation_strategy"] == "model"
    assert result["identity"]["generation_metrics"] == metrics


def test_grounding_repair_converges_before_compile() -> None:
    model = _SequenceModel(
        [
            '@paesiorigine is "italia"',
            '@paesiorigine in ["ITALIA", "italia"]',
        ]
    )
    compiler = _CountingCompiler()
    result = _run_with_model(model, compiler, max_repairs=1)
    assert result["outcome"] == "proposed"
    assert result["schema_version"] == 1
    assert result["claims"]["compile_clean"] is True
    assert compiler.calls == 1
    assert len(model.requests) == 2
    assert model.requests[1].diagnostics[0]["code"] == "CANDIDATE_GROUNDING_MISMATCH"


def test_terminal_grounding_mismatch_fails_closed_without_compile() -> None:
    model = _SequenceModel(['@paesiorigine is "italia"', '@paesiorigine is "italia"'])
    compiler = _CountingCompiler()
    with pytest.raises(BrainError) as raised:
        _run_with_model(model, compiler, max_repairs=1)
    assert raised.value.code == "CANDIDATE_GROUNDING_MISMATCH"
    assert compiler.calls == 0


@pytest.mark.parametrize("max_repairs", [0, 1])
def test_invalid_compiler_receipt_never_produces_proposal(max_repairs: int) -> None:
    model = _SequenceModel(['@paesiorigine in ["ITALIA", "italia"]'] * (max_repairs + 1))
    compiler = _CountingCompiler(status="invalid")
    with pytest.raises(BrainError) as raised:
        _run_with_model(model, compiler, max_repairs=max_repairs)
    assert raised.value.code == "COMPILER_REJECTED"
    assert compiler.calls == max_repairs + 1
