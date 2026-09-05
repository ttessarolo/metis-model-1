from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis_model1.brain_output_contract import (
    CreateQuantityContract,
    parse_create_quantity_surface,
    parse_output_request,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_CORPUS = PROJECT_ROOT / "examples/metis-brain-hard-prompts.play-prod-v2.json"


def _contract(
    kind: str,
    scope: str,
    mode: str,
    value: int | None = None,
    *,
    qualifier: str | None = None,
    factor: int | None = None,
) -> CreateQuantityContract:
    return (kind, scope, mode, qualifier, value, factor)  # type: ignore[return-value]


T = lambda value: _contract("result_count", "total", "total", value)  # noqa: E731
P = lambda value: _contract("result_count", "page", "page_default", value)  # noqa: E731
R = lambda value: _contract("result_count", "row", "total", value)  # noqa: E731
F = lambda value: _contract("fetch_occurrences", "fetch", "exact", value)  # noqa: E731
RC = lambda value: _contract("row_count", "page", "exact", value)  # noqa: E731
B = lambda value: _contract("block_count", "block", "exact", value)  # noqa: E731
INST = lambda value: _contract("instance_count", "instance", "exact", value)  # noqa: E731
POOL = lambda value: _contract("pool_count", "pool", "exact", value)  # noqa: E731
ROLE = lambda value: _contract("role_count", "role", "exact", value)  # noqa: E731

EXPECTED_30_STAGE_CENSUS: dict[
    tuple[str, int],
    tuple[str, tuple[CreateQuantityContract, ...]],
] = {
    ("play.similar_cinema", 2): ("resolved", (T(24),)),
    (
        "play.similar_cinema",
        3,
    ): (
        "resolved",
        (RC(1), _contract("branch_count", "branch", "exact", 4), F(10)),
    ),
    (
        "play.similar_cinema",
        4,
    ): (
        "resolved",
        (_contract("result_count", "final_output", "total", 24, qualifier="final"),),
    ),
    ("play.similar_serie_tv_fiction", 2): ("resolved", (T(24),)),
    (
        "play.similar_serie_tv_fiction",
        3,
    ): (
        "resolved",
        (
            _contract("branch_count", "path", "exact", 3),
            _contract("branch_count", "variant", "exact", 1),
            RC(1),
            F(9),
        ),
    ),
    (
        "play.similar_serie_tv_fiction",
        4,
    ): (
        "resolved",
        (
            _contract("over_fetch", "fetch", "multiplier", 24, factor=2),
            R(5),
        ),
    ),
    ("search.filtered_search", 2): ("resolved", (P(50),)),
    (
        "search.filtered_search",
        3,
    ): ("resolved", (_contract("branch_count", "path", "exact", 7), F(14))),
    ("search.filtered_search", 4): ("absent", ()),
    ("search.detail", 2): ("absent", ()),
    ("search.detail", 3): ("resolved", (B(3),)),
    (
        "search.detail",
        4,
    ): (
        "resolved",
        (
            _contract("branch_count", "variant", "exact", 9),
            _contract("branch_count", "path", "exact", 3),
        ),
    ),
    (
        "play.multiple_block_compleanno",
        2,
    ): (
        "resolved",
        (
            _contract("result_count", "page", "page"),
            _contract("result_count", "total", "deferred"),
        ),
    ),
    ("play.multiple_block_compleanno", 3): ("resolved", (ROLE(11), F(26))),
    ("play.multiple_block_compleanno", 4): ("ambiguous", ()),
    ("play.multiple_block_dem_titoli_momento", 2): ("resolved", (T(30),)),
    ("play.multiple_block_dem_titoli_momento", 3): ("ambiguous", ()),
    (
        "play.multiple_block_dem_titoli_momento",
        4,
    ): (
        "resolved",
        (
            _contract("branch_count", "branch", "exact", 1),
            RC(1),
            _contract("over_fetch", "row", "multiplier", 20, factor=2),
        ),
    ),
    ("play.tvod_multiple_block", 2): ("resolved", (T(30),)),
    ("play.tvod_multiple_block", 3): ("resolved", (INST(11), F(5), RC(1))),
    (
        "play.tvod_multiple_block",
        4,
    ): ("resolved", (_contract("result_count", "page", "page"),)),
    (
        "play.multiple_block4_k",
        2,
    ): (
        "resolved",
        (
            _contract("result_count", "page", "page"),
            _contract("result_count", "row", "total", 20, qualifier="each"),
        ),
    ),
    (
        "play.multiple_block4_k",
        3,
    ): (
        "resolved",
        (
            F(6),
            _contract("result_count", "row", "total", 20, qualifier="each"),
            _contract("result_count", "fetch", "total", 50, qualifier="second"),
        ),
    ),
    ("play.multiple_block4_k", 4): ("absent", ()),
    (
        "play.inf_multiple_block_film_serie",
        2,
    ): (
        "resolved",
        (_contract("result_count", "page", "page"), RC(6)),
    ),
    ("play.inf_multiple_block_film_serie", 3): ("resolved", (B(4), INST(12))),
    ("play.inf_multiple_block_film_serie", 4): ("absent", ()),
    (
        "play.similar_intrat_abtest",
        2,
    ): ("resolved", (RC(1), R(24))),
    (
        "play.similar_intrat_abtest",
        3,
    ): (
        "resolved",
        (
            POOL(4),
            _contract("result_count", "pool", "total", 50, qualifier="each"),
        ),
    ),
    (
        "play.similar_intrat_abtest",
        4,
    ): (
        "resolved",
        (
            _contract("result_count", "fetch", "total", 4, qualifier="first"),
            _contract("result_count", "fetch", "total", 24, qualifier="final"),
            _contract("result_count", "final_output", "total", 24, qualifier="final"),
        ),
    ),
}


def test_frozen_zero_generation_corpus_has_no_quantity_classification_gap() -> None:
    corpus = json.loads(FROZEN_CORPUS.read_text(encoding="utf-8"))
    scenarios = corpus["zero_generation_scenarios"]
    assert len(scenarios) == 10

    observed: dict[
        tuple[str, int],
        tuple[str, tuple[CreateQuantityContract, ...]],
    ] = {}
    for scenario in scenarios:
        endpoint = scenario["endpoint_qualified"]
        for turn in scenario["turns"]:
            if turn["turn"] == 1:
                continue
            surface = parse_create_quantity_surface(turn["user_message"])
            observed[(endpoint, turn["turn"])] = (surface.status, surface.contracts)

    assert len(observed) == 30
    assert len(EXPECTED_30_STAGE_CENSUS) == 30
    assert set(observed) == set(EXPECTED_30_STAGE_CENSUS)
    assert observed == EXPECTED_30_STAGE_CENSUS


def test_t1_clarification_does_not_gain_a_result_count_from_row_wording() -> None:
    t1 = parse_create_quantity_surface("Voglio una riga di film simili per la sezione cinema.")
    assert all(mention.kind != "result_count" for mention in t1.mentions)

    t2 = parse_create_quantity_surface("Usa il catalogo video e dammi 24 risultati totali.")
    assert t2.status == "resolved"
    assert t2.contracts == (T(24),)


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Dammi 24 risultati totali.", T(24)),
        ("Dammi ventiquattro film.", T(24)),
        ("Usa 50 risultati per pagina.", P(50)),
        ("Usa take page default 20.", P(20)),
        (
            "Usa la paginazione snapshot.",
            _contract("result_count", "page", "page"),
        ),
        (
            "Dammi 20 risultati totali per ogni riga.",
            _contract("result_count", "row", "total", 20, qualifier="each"),
        ),
        (
            "Crea una riga clip da 5.",
            R(5),
        ),
        (
            "Costruisci pool candidati da cinquanta elementi ciascuno.",
            _contract("result_count", "pool", "total", 50, qualifier="each"),
        ),
        ("Distribuisci quattordici take complessivi.", F(14)),
        (
            "Usa un secondo take di ampliamento a 50.",
            _contract("result_count", "fetch", "total", 50, qualifier="second"),
        ),
        (
            "Aggiungi una sequenza 24 per 2.",
            _contract("over_fetch", "fetch", "multiplier", 24, factor=2),
        ),
        (
            "Usa una riga 20 * 2.",
            _contract("over_fetch", "row", "multiplier", 20, factor=2),
        ),
        (
            "Limita il risultato finale a 24.",
            _contract("result_count", "final_output", "total", 24, qualifier="final"),
        ),
        (
            "Non applicare ancora un limite globale.",
            _contract("result_count", "total", "deferred"),
        ),
        ("Crea sei righe per la pagina.", RC(6)),
        ("Separa tre blocchi riusabili.", B(3)),
        ("Crea undici istanze del blocco.", INST(11)),
        (
            "Aggiungi quattro rami separati.",
            _contract("branch_count", "branch", "exact", 4),
        ),
        (
            "Instrada nove varianti.",
            _contract("branch_count", "variant", "exact", 9),
        ),
        (
            "Prevedi sette percorsi distinti.",
            _contract("branch_count", "path", "exact", 7),
        ),
        ("Costruisci quattro pool candidati.", POOL(4)),
        ("Aggiungi undici ruoli separati.", ROLE(11)),
    ],
)
def test_each_scoped_create_quantity_is_typed(
    instruction: str,
    expected: CreateQuantityContract,
) -> None:
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "resolved"
    assert expected in surface.contracts
    assert surface.issues == ()


def test_distinct_local_row_and_fetch_quantities_can_coexist() -> None:
    surface = parse_create_quantity_surface(
        "Usa una sequenza 24 per 2 e fai shuffle solo sulla riga clip da 5."
    )
    assert surface.status == "resolved"
    assert surface.contracts == (
        _contract("over_fetch", "fetch", "multiplier", 24, factor=2),
        R(5),
    )


def test_first_and_final_fetch_counts_are_separate_local_facts() -> None:
    surface = parse_create_quantity_surface("Usa un primo take da 4 e uno finale da 24.")
    assert surface.status == "resolved"
    assert surface.contracts == (
        _contract("result_count", "fetch", "total", 4, qualifier="first"),
        _contract("result_count", "fetch", "total", 24, qualifier="final"),
    )


@pytest.mark.parametrize(
    "instruction",
    [
        "Crea un endpoint di film italiani ordinati per data.",
        "Usa una finestra di 18 mesi, 14 giorni e il formato 4K.",
        "I conteggi saranno definiti in seguito.",
    ],
)
def test_absence_never_forces_a_count_or_normalizes_prose(instruction: str) -> None:
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "absent"
    assert surface.mentions == ()
    assert surface.contracts == ()
    assert surface.semantic_instruction == instruction
    assert not surface.requires_clarification


@pytest.mark.parametrize(
    "instruction",
    [
        "Dammi alcuni risultati.",
        "Dammi circa 24 risultati.",
        "Dammi 20 o 24 risultati.",
        "Dammi tra 20 e 24 risultati.",
        "Usa una riga da almeno 20.",
        "Dividi la pagina in almeno dieci blocchi.",
        "Aggiungi un limite finale distinto per ciascuno.",
    ],
)
def test_ambiguous_quantity_fails_closed(instruction: str) -> None:
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "ambiguous"
    assert surface.mentions == ()
    assert surface.contracts == ()
    assert surface.semantic_instruction == instruction
    assert surface.requires_clarification


@pytest.mark.parametrize(
    "instruction",
    [
        "Dammi 0 risultati.",
        "Dammi 10001 risultati.",
        "Dammi -2 risultati.",
        "Dammi 1,5 risultati.",
        "Usa una riga da 0.",
        "Crea 0 blocchi.",
        "Usa un take da 10001.",
        "Usa una sequenza 24 per 1.",
        "Usa una sequenza 24 per 17.",
    ],
)
def test_invalid_quantity_fails_closed(instruction: str) -> None:
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "invalid"
    assert surface.mentions == ()
    assert surface.contracts == ()
    assert surface.semantic_instruction == instruction
    assert surface.requires_clarification


@pytest.mark.parametrize(
    "instruction",
    [
        "Dammi 24 risultati e 30 risultati.",
        "Usa 20 risultati per pagina e 50 risultati per pagina.",
        "Non applicare un limite globale ma dammi 24 risultati totali.",
        "Distribuisci sei take complessivi e nove take complessivi.",
        "Crea tre righe e sei righe.",
        "Crea tre blocchi e sei blocchi.",
        "Ogni riga ha 20 risultati per riga e 50 risultati per riga.",
        "Usa un primo take da 4 e un primo take da 8.",
    ],
)
def test_conflicting_quantity_fails_closed(instruction: str) -> None:
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "conflict"
    assert surface.mentions == ()
    assert surface.contracts == ()
    assert surface.semantic_instruction == instruction
    assert surface.requires_clarification


def test_quoted_or_backticked_quantity_examples_are_not_authority() -> None:
    instruction = 'Non copiare "24 risultati" né `take 50 from @video`.'
    surface = parse_create_quantity_surface(instruction)
    assert surface.status == "absent"
    assert surface.semantic_instruction == instruction


def test_resolved_masking_retains_semantic_film_and_video_nouns() -> None:
    surface = parse_create_quantity_surface("Dammi 24 film in bianco e nero.")
    assert surface.status == "resolved"
    assert surface.semantic_instruction == "Dammi film in bianco e nero."


def test_duplicate_identical_contract_is_not_a_conflict() -> None:
    surface = parse_create_quantity_surface("Dammi 24 risultati, esattamente 24 risultati.")
    assert surface.status == "resolved"
    assert surface.contracts == (T(24),)
    assert len(surface.mentions) == 2


def test_create_parser_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="instruction must be a string"):
        parse_create_quantity_surface(None)  # type: ignore[arg-type]


def test_legacy_output_parser_contract_remains_unchanged() -> None:
    total = parse_output_request("Dammi 24 film italiani.")
    assert total.contracts == (("count", 24),)
    assert total.semantic_instruction == "Dammi film italiani."
    assert not total.generic_pagination
    assert not total.ambiguous_count
    assert not total.invalid_numeric_output

    page = parse_output_request("Dammi 50 risultati per pagina.")
    assert page.contracts == (("page", 50),)
    assert page.generic_pagination
    assert not page.invalid_numeric_pagination

    ambiguous = parse_output_request("Dammi alcuni risultati.")
    assert ambiguous.mentions == ()
    assert ambiguous.ambiguous_count

    invalid = parse_output_request("Dammi -2 risultati.")
    assert invalid.mentions == ()
    assert invalid.invalid_numeric_output
