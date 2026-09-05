"""Prompt-only L1068 blueprint contract, with no runtime corpus/tenant reads.

The prompt text below is the complete allowed projection for these five ids.
It deliberately contains no endpoint source, hidden oracle, generated IR or
stage-authority fixture. Rendering tests exercise the pure typed builder only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_SCHEMA,
    render_create_endpoint,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "examples" / "metis-brain-create-blueprints-v3-multiblock.json"

PROMPTS = {
    "play.multiple_block_compleanno": {
        1: "Voglio una homepage personalizzata con contenuti per il compleanno dell'utente.",
        2: (
            "Usa insieme i cataloghi video e users, la paginazione snapshot e il seed "
            "dell'utente; non applicare ancora un limite globale, perché i conteggi "
            "saranno definiti nei singoli blocchi."
        ),
        3: (
            "Aggiungi undici ruoli separati e ventisei take complessivi: film recenti, "
            "fallback cinema, film simili al cluster, intrattenimento recente, programmi "
            "TV, documentari, fiction/serie scelte, soap simili al cluster, kids, "
            "informazione recente e informazione/sport simili; riusa i blocchi con Vedi "
            "tutto, combina le alternative dove esiste un profilo simile e ordina ogni "
            "riga secondo il suo criterio."
        ),
        4: (
            "Quando una riga clusterizzata è vuota usa la riga più recente della stessa "
            "area; aggiungi i rami ciak e statico, con un limite finale distinto per "
            "ciascuno."
        ),
    },
    "play.multiple_block_dem_titoli_momento": {
        1: "Crea una pagina con i titoli del momento.",
        2: "Catalogo video, 30 risultati totali per la pagina, con film e serie recenti.",
        3: (
            "Dividi la pagina in almeno dieci blocchi e ventisette take complessivi: "
            "fallback cinema, film recenti, serie/fiction recenti, fiction e serie per "
            "te, originali, documentari più visti, programmi TV, soap e tre righe rese "
            "movibili; ciascuno deve avere Vedi tutto."
        ),
        4: (
            "Aggiungi un ramo clusterizzato e uno default; passa prima dalla "
            "personalizzazione e poi dal clustering. Nel ramo clusterizzato usa una "
            "riga 20 per 2 e un fallback sulla riga più recente, mentre il risultato "
            "finale riordina per affinità al profilo."
        ),
    },
    "play.tvod_multiple_block": {
        1: "Voglio una pagina TVOD con film consigliati.",
        2: "Catalogo video, 30 risultati totali e sezioni per genere.",
        3: (
            "Crea undici istanze del blocco, una per famiglia/animazione, azione, "
            "commedia, drammatico, horror, thriller, fantascienza, avventura, biografico, "
            "crime e sportivo; conserva cinque take nel blocco condiviso, aggiungi una "
            "riga Perché hai visto con risposta expanded e usa alternative per "
            "selezionare i titoli migliori."
        ),
        4: (
            "Riordina le sezioni per affinità alla storia dell'utente e, in caso di "
            "errore, usa la pagina TVOD di errore; conserva i take interni, Vedi tutto "
            "e la paginazione snapshot."
        ),
    },
    "play.multiple_block4_k": {
        1: "Crea una pagina con film e serie disponibili in 4K.",
        2: (
            "Usa insieme i cataloghi video e users, la paginazione snapshot e 20 "
            "risultati totali per riga; distingui HDR e SDR in base alla capacità del "
            "dispositivo."
        ),
        3: (
            "Distribuisci sei take complessivi nei rami: ciascuna riga principale da "
            "20 deve avere un secondo take di ampliamento a 50; usa Vedi tutto, "
            "ordina i film per anno di produzione e riusa un blocco parametrico per "
            "genere con righe per azione/thriller, commedie, drammatico e classici."
        ),
        4: (
            "Se non c'è una capacità 4K lascia la variante vuota; conserva anche la "
            "riga di serie/documentari e riordina il risultato finale per affinità "
            "alla storia."
        ),
    },
    "play.inf_multiple_block_film_serie": {
        1: "Crea una homepage con film e serie divisi per genere.",
        2: (
            "Usa insieme i cataloghi video e users, la paginazione snapshot e sei "
            "righe per la pagina; ricava dal catalogo users il contesto utente e "
            "l'attributo has_fingerprint: se l'utente ha storia usa la personalizzazione, "
            "altrimenti una pagina anonima."
        ),
        3: (
            "Dichiara quattro blocchi parametrici riusabili, film e serie per il "
            "percorso personalizzato e film e serie per quello anonimo, tutti con "
            "genere obbligatorio; crea dodici istanze complessive usando commedia, "
            "drammatico, azione, drama, comedy e crime in ciascun percorso."
        ),
        4: (
            "Ogni riga deve avere Vedi tutto; nella pagina personalizzata ordina le "
            "righe per affinità al fingerprint e lascia quella anonima in ordine fisso."
        ),
    },
}


def _load_bundle() -> dict[str, Any]:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def _stages() -> list[tuple[str, dict[str, Any]]]:
    return [
        (scenario["scenario_id"], stage)
        for scenario in _load_bundle()["scenarios"]
        for stage in scenario["stages"]
    ]


def test_exact_five_scenario_fifteen_stage_roster() -> None:
    bundle = _load_bundle()
    assert set(bundle) == {"schema_version", "contract_id", "scenarios"}
    assert bundle["schema_version"] == 3
    assert bundle["contract_id"] == "metis-brain-create-stage-blueprints/v3"
    scenarios = bundle["scenarios"]
    assert [item["scenario_id"] for item in scenarios] == list(PROMPTS)
    assert len({(scenario_id, item["stage_id"]) for scenario_id, item in _stages()}) == 15
    for scenario in scenarios:
        assert set(scenario) == {"scenario_id", "stages"}
        assert [item["stage_id"] for item in scenario["stages"]] == ["T2", "T3", "T4"]


def test_unresolved_stages_cannot_supply_partial_authority() -> None:
    ready = []
    for scenario_id, stage in _stages():
        assert set(stage) == {"stage_id", "status", "spec", "spec_sha256", "missing"}
        assert stage["status"] in {"ready", "needs_clarification"}
        if stage["status"] == "ready":
            ready.append((scenario_id, stage["stage_id"]))
            assert isinstance(stage["spec"], dict)
            assert stage["missing"] == []
        else:
            assert stage["spec"] is None
            assert stage["spec_sha256"] is None
            assert stage["missing"]
    assert ready == [("play.multiple_block_dem_titoli_momento", "T2")]


def test_missing_slots_have_exact_non_future_prompt_evidence() -> None:
    for scenario_id, stage in _stages():
        slots = []
        for missing in stage["missing"]:
            assert set(missing) == {"slot", "reason", "evidence"}
            assert missing["slot"].startswith("endpoint.")
            assert len(missing["reason"].strip()) >= 40
            slots.append(missing["slot"])
            assert missing["evidence"]
            for item in missing["evidence"]:
                assert set(item) == {"turn", "quote"}
                assert type(item["turn"]) is int
                assert 1 <= item["turn"] <= int(stage["stage_id"][1:])
                assert isinstance(item["quote"], str) and item["quote"]
                assert item["quote"] in PROMPTS[scenario_id][item["turn"]]
        assert len(slots) == len(set(slots))


def test_later_stages_preserve_every_still_unresolved_slot() -> None:
    for scenario in _load_bundle()["scenarios"]:
        previous_slots: set[str] = set()
        for stage in scenario["stages"]:
            slots = {item["slot"] for item in stage["missing"]}
            assert previous_slots <= slots
            previous_slots = slots
            if stage["status"] == "needs_clarification":
                assert any(
                    evidence["turn"] == int(stage["stage_id"][1:])
                    for item in stage["missing"]
                    for evidence in item["evidence"]
                )


def test_ready_spec_validates_renders_and_has_independently_recomputed_hash() -> None:
    validator = Draft202012Validator(CREATE_ENDPOINT_SPEC_SCHEMA)
    for scenario_id, stage in _stages():
        if stage["status"] != "ready":
            continue
        spec = stage["spec"]
        validator.validate(spec)
        canonical = json.dumps(
            spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        assert "sha256:" + hashlib.sha256(canonical).hexdigest() == stage["spec_sha256"]
        assert spec["endpoint"]["name"] == scenario_id
        rendered = render_create_endpoint(spec)
        assert rendered.spec_sha256 == stage["spec_sha256"]
        assert rendered.stats.fetches == 1
        assert rendered.stats.clauses == 1
        assert rendered.stats.predicates == 1
        assert rendered.stats.output_steps == 1
        assert rendered.stats.fallbacks == 0
        assert rendered.stats.expanded_uses == 0


def test_recent_titles_t2_has_only_requested_selection_order_and_page_limit() -> None:
    stage = next(
        stage
        for scenario_id, stage in _stages()
        if scenario_id == "play.multiple_block_dem_titoli_momento" and stage["stage_id"] == "T2"
    )
    endpoint = stage["spec"]["endpoint"]
    assert endpoint["reference"] is None
    assert endpoint["params"] == {"timeout": None, "expires": None, "paginate": None}
    assert endpoint["needs_time"] is False
    for key in ("inputs", "attributes", "input_pipeline", "output_pipeline", "context", "blocks"):
        assert endpoint[key] == []
    assert endpoint["inheritance"] == {"without_input": [], "without_output": []}
    assert len(endpoint["variants"]) == 1
    variant = endpoint["variants"][0]
    assert variant["activation"] is None
    assert variant["blocks"] == variant["uses"] == []
    assert variant["output"] is None
    assert len(variant["fetches"]) == 1
    fetch = variant["fetches"][0]
    assert fetch["from"] == {"kind": "catalog", "catalog": "video"}
    assert fetch["cardinality"] == {"mode": "total", "value": 30}
    assert fetch["clauses"] == [
        {
            "intent": "include",
            "where": [
                {
                    "op": "in",
                    "field": "tipologia",
                    "value": {"kind": "vals", "items": ["Film", "Serie TV"]},
                }
            ],
        }
    ]
    assert fetch["order"] == [
        {"by": "field", "direction": "descending", "field": "publication_date"}
    ]
    for key in ("over_fetch", "alias", "title", "activation", "group_by", "output"):
        assert fetch[key] is None
    empty_presentation = {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}
    assert fetch["presentation"] == variant["presentation"] == empty_presentation
    assert endpoint["output"] == {
        "projection": "default",
        "steps": [{"kind": "max", "count": 30}],
        "fallbacks": [],
    }


@pytest.mark.parametrize(
    ("scenario_id", "slot", "required_numbers"),
    [
        ("play.multiple_block_compleanno", "endpoint.blocks[*].fetches.take_plan", (11, 26)),
        (
            "play.multiple_block_dem_titoli_momento",
            "endpoint.blocks[*].fetches.take_plan",
            (10, 27),
        ),
        ("play.tvod_multiple_block", "endpoint.blocks[genre].fetches.take_plan", (11, 5)),
        ("play.multiple_block4_k", "endpoint.blocks_and_variants.fetches.take_plan", (6, 20, 50)),
        (
            "play.inf_multiple_block_film_serie",
            "endpoint.variants[personalizzata,anonima].uses[*].block",
            (4, 12, 6),
        ),
    ],
)
def test_aggregate_counts_do_not_authorize_invented_allocation(
    scenario_id: str, slot: str, required_numbers: tuple[int, ...]
) -> None:
    for owner_id, stage in _stages():
        if owner_id != scenario_id or stage["stage_id"] == "T2":
            continue
        missing = next(item for item in stage["missing"] if item["slot"] == slot)
        assert all(str(number) in missing["reason"] for number in required_numbers)
        assert stage["spec"] is None


def test_named_missing_destinations_and_branch_limits_remain_explicit() -> None:
    stages = {(scenario_id, stage["stage_id"]): stage for scenario_id, stage in _stages()}
    birthday = stages[("play.multiple_block_compleanno", "T4")]
    assert "endpoint.variants[ciak,statico].output.steps[max].count" in {
        item["slot"] for item in birthday["missing"]
    }
    tvod = stages[("play.tvod_multiple_block", "T4")]
    assert "endpoint.output.fallbacks[error].target" in {item["slot"] for item in tvod["missing"]}
    for scenario_id in PROMPTS:
        stage = stages[(scenario_id, "T4")]
        assert "endpoint.blocks[*].presentation.view_all" in {
            item["slot"] for item in stage["missing"]
        }
