from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_intent_ir import FLASH_INTENT_SCHEMA_SHA256
from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_semantic_retrieval import (
    MAX_FIELDS,
    LoadedProjection,
    Schema2SnapshotRetriever,
)
from metis_model1.brain_turns import TurnRecord, TurnRequest
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _semantic(
    state: str,
    file: str,
    line: int,
    *,
    text: str | None = None,
    aka: list[str] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"state": state, "at": {"file": file, "line": line}}
    if text is not None:
        result["means"] = {"text": text, "at": {"file": file, "line": line + 1}}
    if aka is not None:
        result["aka"] = {"items": aka, "at": {"file": file, "line": line + 2}}
    if label is not None:
        result["label"] = {"text": label, "at": {"file": file, "line": line + 3}}
    return result


def _field(
    name: str,
    file: str,
    line: int,
    *,
    state: str = "reviewed",
    text: str | None = None,
    domain: dict[str, Any] | None = None,
    modifiers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": "keyword",
        "modifiers": list(modifiers or []),
        "semantic": _semantic(state, file, line, text=text or name),
        "domain": domain or {"kind": "none"},
    }


def _projection(*, second_owner: bool = False, mirror_only: bool = False) -> dict[str, Any]:
    video_file = "catalogs/video.metis"
    mirror_file = "catalogs/video_pg.metis"
    video_fields = [
        _field(
            "genre",
            video_file,
            10,
            text="genere editoriale",
            domain={
                "kind": "enum",
                "size": 2,
                "nature": "editorial",
                "values": [
                    {
                        "literal": "Film",
                        "semantic": _semantic(
                            "reviewed", video_file, 20, text="opera cinematografica"
                        ),
                    },
                    {
                        "literal": "Sport",
                        "semantic": _semantic("draft", video_file, 21, text="contenuto sportivo"),
                    },
                ],
            },
        ),
        _field("title", video_file, 30, text="titolo indicizzato"),
        _field("mood", video_file, 31, text="tono narrativo", domain={"kind": "open"}),
        _field("protagonistaSesso", video_file, 32, text="sesso del protagonista"),
    ]
    catalogs: list[dict[str, Any]] = []
    if not mirror_only:
        catalogs.append(
            {
                "name": "video",
                "driver": "opensearch",
                "file": video_file,
                "semantic": _semantic(
                    "reviewed", video_file, 2, text="contenuti video", label="Video"
                ),
                "fields": video_fields,
            }
        )
    catalogs.append(
        {
            "name": "video_pg",
            "driver": "opensearch",
            "file": mirror_file,
            "semanticSource": {
                "catalog": "video",
                "at": {"file": video_file, "line": 1},
            },
            "semantic": _semantic(
                "reviewed", mirror_file, 2, text="mirror operativo", label="Video PG"
            ),
            "fields": [copy.deepcopy(video_fields[0])],
        }
    )
    if second_owner:
        users_file = "catalogs/users.metis"
        catalogs.append(
            {
                "name": "users",
                "driver": "opensearch",
                "file": users_file,
                "semantic": _semantic("reviewed", users_file, 2, text="utenti", label="Utenti"),
                "fields": [_field("country", users_file, 10, text="paese utente")],
            }
        )
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "tenant-one",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": catalogs,
    }


def _refinement_projection() -> dict[str, Any]:
    projection = _projection()
    fields = projection["catalogs"][0]["fields"]
    fields[0]["domain"]["size"] = 3
    fields[0]["domain"]["values"].append(
        {
            "literal": "Documentario",
            "semantic": _semantic(
                "reviewed",
                "catalogs/video.metis",
                22,
                text="opera documentaria",
            ),
        }
    )
    fields.extend(
        [
            _field(
                "country",
                "catalogs/video.metis",
                40,
                text="paese di produzione",
                domain={
                    "kind": "inline",
                    "size": 2,
                    "values": [
                        {
                            "literal": "Francia",
                            "semantic": _semantic(
                                "reviewed",
                                "catalogs/video.metis",
                                41,
                                text="opera prodotta in Francia",
                            ),
                        },
                        {
                            "literal": "Germania",
                            "semantic": _semantic(
                                "draft",
                                "catalogs/video.metis",
                                42,
                                text="opera prodotta in Germania",
                            ),
                        },
                    ],
                },
            ),
            _field(
                "award",
                "catalogs/video.metis",
                50,
                text="riconoscimento editoriale",
                domain={
                    "kind": "inline",
                    "size": 1,
                    "values": [
                        {
                            "literal": "Premiato",
                            "semantic": _semantic(
                                "reviewed",
                                "catalogs/video.metis",
                                51,
                                text="opera che ha ricevuto un premio",
                            ),
                        }
                    ],
                },
            ),
        ]
    )
    return projection


def _snapshot(*, revision: str = HASH_A, binding: str = HASH_C) -> ContextSnapshot:
    files = (
        SnapshotFile("metis.toml", b"tenant", HASH_A),
        SnapshotFile("catalogs/video.metis", b"video", HASH_B),
        SnapshotFile("catalogs/video_pg.metis", b"video pg", HASH_C),
        SnapshotFile("catalogs/users.metis", b"users", HASH_A),
        SnapshotFile(
            "properties/demo.metis",
            b"metis 0.43\nendpoint demo.feed { variant main { take 1 from @video } }\n",
            "sha256:" + "d" * 64,
        ),
    )
    return ContextSnapshot(
        tenant_alias="demo",
        tenant_id="tenant-one",
        root_device=1,
        root_inode=2,
        revision=revision,
        toolchain_binding=binding,
        files=files,
        total_bytes=sum(len(item.content) for item in files),
    )


def _request(instruction: str, *, catalog_hint: str | None = None) -> Any:
    value = SimpleNamespace(instruction=instruction)
    if catalog_hint is not None:
        value.catalog_hint = catalog_hint
    return value


def _lease(snapshot: ContextSnapshot) -> Any:
    return SimpleNamespace(snapshot=snapshot)


def _bound_loader(factory):
    def load(snapshot: ContextSnapshot) -> LoadedProjection:
        projection = factory() if callable(factory) else factory
        return LoadedProjection(
            projection,
            snapshot.revision,
            snapshot.semantic_source_revision(),
        )

    return load


def test_loader_receives_exact_snapshot_and_index_is_bound_to_it() -> None:
    snapshot = _snapshot()
    seen: list[ContextSnapshot] = []

    def loader(value: ContextSnapshot) -> LoadedProjection:
        seen.append(value)
        return LoadedProjection(_projection(), value.revision, value.semantic_source_revision())

    result = Schema2SnapshotRetriever(loader).retrieve(
        lease=_lease(snapshot), request=_request("crea un endpoint per Film")
    )
    assert seen == [snapshot]
    assert result.semantic_source_revision == snapshot.semantic_source_revision()
    assert result.context["context_revision"] == snapshot.revision
    assert result.context["toolchain_binding"] == snapshot.toolchain_binding
    assert result.grounding["status"] == "resolved"
    assert result.grounding["selections"][0]["literal"] == "Film"
    assert result.grounding["selections"][0]["type"] == "keyword"
    assert result.grounding["selections"][0]["modifiers"] == []
    assert result.context["language_version"] == "0.43"
    assert result.context["fields"][0]["type"] == "keyword"
    assert result.context["fields"][0]["modifiers"] == []
    assert result.context["endpoint_templates"] == [
        {
            "path": "properties/demo.metis",
            "source": "metis 0.43\nendpoint demo.feed { variant main { take 1 from @video } }\n",
        }
    ]


def test_retrieval_preserves_multi_cardinality_in_context_and_grounding() -> None:
    snapshot = _snapshot()
    projection = _projection()
    projection["catalogs"][0]["fields"][0]["modifiers"] = ["multi"]
    result = Schema2SnapshotRetriever(_bound_loader(lambda: projection)).retrieve(
        lease=_lease(snapshot), request=_request("Film")
    )
    assert result.context["fields"][0]["modifiers"] == ["multi"]
    assert result.grounding["selections"][0]["modifiers"] == ["multi"]


def test_stale_envelope_and_source_location_fail_closed() -> None:
    snapshot = _snapshot()
    stale = LoadedProjection(_projection(), HASH_B, snapshot.semantic_source_revision())
    with pytest.raises(BrainError) as raised:
        Schema2SnapshotRetriever(lambda _snapshot: stale).retrieve(
            lease=_lease(snapshot), request=_request("Film")
        )
    assert raised.value.code == "STALE_CONTEXT"

    outside = _projection()
    outside["catalogs"][0]["fields"][0]["semantic"]["at"]["file"] = "secret.metis"
    with pytest.raises(BrainError) as raised:
        Schema2SnapshotRetriever(_bound_loader(outside)).retrieve(
            lease=_lease(snapshot), request=_request("Film")
        )
    assert raised.value.code == "STALE_CONTEXT"


def test_video_is_owner_and_video_pg_is_not_implicit_ambiguity() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_projection))
    implicit = retriever.retrieve(lease=_lease(snapshot), request=_request("Film"))
    assert implicit.grounding["catalogs"] == ["video"]
    assert implicit.grounding["status"] == "resolved"

    explicit = retriever.retrieve(lease=_lease(snapshot), request=_request("@video_pg Film"))
    assert explicit.grounding["catalogs"] == ["video_pg"]
    assert explicit.context["catalog"]["name"] == "video_pg"
    assert explicit.grounding["selections"][0]["literal"] == "Film"
    assert explicit.context["fields"][0]["semantic"]["means"]["text"] == "genere editoriale"


def test_fully_qualified_catalog_reference_is_not_an_unresolved_semantic_clause() -> None:
    projection = _projection()
    projection["catalogs"][0]["name"] = "play-demo.video"
    projection["catalogs"][1]["name"] = "play-demo.video_pg"
    projection["catalogs"][1]["semanticSource"]["catalog"] = "play-demo.video"

    result = Schema2SnapshotRetriever(_bound_loader(lambda: projection)).retrieve(
        lease=_lease(_snapshot()),
        request=_request("Crea un endpoint su @play-demo.video per Film"),
    )

    assert result.grounding["status"] == "resolved"
    assert result.grounding["catalogs"] == ["play-demo.video"]
    assert result.grounding["unresolved"] == []
    assert result.grounding["selections"][0]["literal"] == "Film"


def test_catalog_cardinality_is_auto_unsupported_or_clarification() -> None:
    snapshot = _snapshot()
    one = Schema2SnapshotRetriever(_bound_loader(_projection))
    assert (
        one.retrieve(lease=_lease(snapshot), request=_request("Film")).grounding["status"]
        == "resolved"
    )

    orphan = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(mirror_only=True)))
    with pytest.raises(BrainError, match="canonical owner"):
        orphan.retrieve(lease=_lease(snapshot), request=_request("Film"))

    multiple = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(second_owner=True)))
    clarification = multiple.retrieve(lease=_lease(snapshot), request=_request("crea endpoint"))
    assert clarification.grounding["status"] == "clarify"
    assert clarification.grounding["catalog_candidates"] == ["users", "video"]

    inferred = multiple.retrieve(lease=_lease(snapshot), request=_request("crea endpoint Film"))
    assert inferred.grounding["catalogs"] == ["video"]
    assert inferred.grounding["status"] == "resolved"


def test_draft_catalog_semantics_are_not_exposed_in_clarification_options() -> None:
    snapshot = _snapshot()
    projection = _projection(second_owner=True)
    projection["catalogs"][0]["semantic"].update(
        {
            "state": "draft",
            "label": {
                "text": "Etichetta bozza non verificata",
                "at": {"file": "catalogs/video.metis", "line": 5},
            },
            "means": {
                "text": "Descrizione bozza non verificata",
                "at": {"file": "catalogs/video.metis", "line": 6},
            },
        }
    )

    result = Schema2SnapshotRetriever(_bound_loader(projection)).retrieve(
        lease=_lease(snapshot), request=_request("crea endpoint")
    )

    option = next(item for item in result.catalog_candidates if item["catalog"] == "video")
    assert option["label"] == "video"
    assert option["description"] == "Catalogo autorizzato"
    assert result.context["catalogs"] == [dict(item) for item in result.catalog_candidates]


def test_catalog_inference_keeps_unique_owner_and_prefers_reviewed_general_field() -> None:
    snapshot = _snapshot()
    projection = _projection(second_owner=True)
    projection["catalogs"][0]["fields"].append(
        _field(
            "secondary_type",
            "catalogs/video.metis",
            40,
            text="classificazione secondaria",
            domain={
                "kind": "inline",
                "size": 1,
                "values": [
                    {
                        "literal": "Film",
                        "semantic": _semantic(
                            "reviewed", "catalogs/video.metis", 41, text="literal secondario"
                        ),
                    }
                ],
            },
        )
    )
    result = Schema2SnapshotRetriever(_bound_loader(projection)).retrieve(
        lease=_lease(snapshot), request=_request("crea un endpoint per Film")
    )
    assert result.grounding["catalogs"] == ["video"]
    assert result.grounding["status"] == "resolved"
    assert result.grounding["selections"][0]["field"] == "genre"


def test_only_server_owned_clarification_rebinds_selected_catalog() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(second_owner=True)))
    first = retriever.retrieve(lease=_lease(snapshot), request=_request("crea endpoint"))
    users = next(item for item in first.catalog_candidates if item["catalog"] == "users")
    assert "." not in users["option_ref"]
    raw_request = SimpleNamespace(
        instruction="crea endpoint",
        clarification_response={
            "option_ref": users["option_ref"],
            "context_revision": snapshot.revision,
            "semantic_source_revision": snapshot.semantic_source_revision(),
        },
    )
    ignored = retriever.retrieve(lease=_lease(snapshot), request=raw_request)
    assert ignored.grounding["status"] == "clarify"

    request = SimpleNamespace(
        instruction="crea endpoint country",
        server_clarification={"kind": "catalog", "resolved_value": "users"},
    )
    selected = retriever.retrieve(lease=_lease(snapshot), request=request)
    assert selected.context["catalog"]["name"] == "users"
    assert selected.grounding["catalogs"] == ["users"]


def test_server_owned_semantic_choice_resolves_means_tie_without_losing_surface() -> None:
    snapshot = _snapshot()
    projection = _projection()
    projection["catalogs"][0]["fields"].append(
        _field("genre_alt", "catalogs/video.metis", 45, text="genere editoriale")
    )
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: projection))

    first = retriever.retrieve(lease=_lease(snapshot), request=_request("@video genere editoriale"))
    assert first.grounding["status"] == "clarify"
    assert len(first.grounding["candidates"]) == 2
    chosen = next(item for item in first.grounding["candidates"] if item["field"] == "genre")
    assert chosen["matched_surfaces"] == ["genere editoriale"]

    request = SimpleNamespace(
        instruction="@video genere editoriale",
        server_clarification={
            "kind": "semantic_choice",
            "resolved_value": chosen["option_ref"],
        },
    )
    selected = retriever.retrieve(lease=_lease(snapshot), request=request)
    assert selected.grounding["status"] == "resolved"
    assert selected.grounding["unresolved"] == []
    assert selected.grounding["candidates"] == []
    assert selected.grounding["selections"][0]["field"] == "genre"


def test_all_server_owned_semantic_decisions_replay_in_order() -> None:
    snapshot = _snapshot()
    projection = _projection()
    projection["catalogs"][0]["fields"].extend(
        [
            _field("genre_alt", "catalogs/video.metis", 45, text="genere editoriale"),
            _field("mood_alt", "catalogs/video.metis", 46, text="tono narrativo"),
        ]
    )
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: projection))
    instruction = "@video genere editoriale, tono narrativo"

    first = retriever.retrieve(lease=_lease(snapshot), request=_request(instruction))
    assert first.grounding["status"] == "clarify"
    assert len(first.grounding["candidates"]) == 4
    genre = next(item for item in first.grounding["candidates"] if item["field"] == "genre")
    mood = next(item for item in first.grounding["candidates"] if item["field"] == "mood")
    assert genre["clause_ref"] != mood["clause_ref"]

    selected = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_clarification={
                "decisions": [
                    {"kind": "semantic_choice", "resolved_value": genre["option_ref"]},
                    {"kind": "semantic_choice", "resolved_value": mood["option_ref"]},
                ]
            },
        ),
    )
    assert selected.grounding["status"] == "resolved"
    assert selected.grounding["candidates"] == []
    assert {item["field"] for item in selected.grounding["selections"]} == {
        "genre",
        "mood",
    }


def test_refinement_does_not_replay_semantic_choice_already_absorbed_by_basis() -> None:
    snapshot = _snapshot()
    projection = _refinement_projection()
    projection["catalogs"][0]["fields"].append(
        _field("genre_alt", "catalogs/video.metis", 60, text="genere editoriale")
    )
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: projection))
    instruction = "@video genere editoriale"

    ambiguous = retriever.retrieve(lease=_lease(snapshot), request=_request(instruction))
    chosen = next(item for item in ambiguous.grounding["candidates"] if item["field"] == "genre")
    decision = {"kind": "semantic_choice", "resolved_value": chosen["option_ref"]}
    selected = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_clarification={
                "decisions": [decision],
                "current_decision": decision,
            },
        ),
    )
    assert selected.grounding["status"] == "resolved"
    assert selected.grounding["selections"][0]["field"] == "genre"

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="rendi più chiara l'etichetta dell'endpoint",
            server_basis_grounding=selected.grounding,
            server_clarification={"decisions": [decision]},
        ),
    )
    assert refined.grounding["status"] == "resolved"
    assert refined.grounding["selections"][0]["field"] == "genre"
    assert refined.grounding["nonsemantic_refinement"] == {
        "kind": "endpoint_label",
        "source": "server_basis",
    }


def test_explicit_refinement_catalog_overrides_historical_catalog_choice() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(second_owner=True)))
    basis = retriever.retrieve(
        lease=_lease(snapshot),
        request=_request("@video Film"),
    ).grounding
    historical = {
        "kind": "catalog",
        "resolved_value": "video",
    }

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="ora usa @users country",
            server_basis_grounding=basis,
            server_clarification={"decisions": [historical]},
        ),
    )
    assert refined.context["catalog"]["name"] == "users"
    assert refined.grounding["catalogs"] == ["users"]
    assert refined.grounding["selections"][0]["field"] == "country"


def test_semantic_clause_digest_covers_full_clause_beyond_public_preview() -> None:
    snapshot = _snapshot()
    projection = _projection()
    projection["catalogs"][0]["fields"].append(
        _field("genre_alt", "catalogs/video.metis", 45, text="genere editoriale")
    )
    long_token = "z" * 520
    full_clause = f"{long_token} genere editoriale"
    result = Schema2SnapshotRetriever(_bound_loader(lambda: projection)).retrieve(
        lease=_lease(snapshot), request=_request(f"@video {full_clause}")
    )
    candidate = result.grounding["candidates"][0]
    assert len(candidate["clause"]) == 256
    assert candidate["clause_ref"] == canonical_sha256({"clause": full_clause})
    assert candidate["clause_ref"] != canonical_sha256({"clause": candidate["clause"]})


def test_refinement_reuses_reviewed_proposal_basis_inside_same_snapshot() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_projection))
    first = retriever.retrieve(lease=_lease(snapshot), request=_request("@video Film"))
    assert first.grounding["status"] == "resolved"

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="porta il numero di risultati a 30",
            server_basis_grounding=first.grounding,
        ),
    )
    assert refined.grounding["status"] == "resolved"
    assert refined.grounding["selections"][0]["literal"] == "Film"
    assert refined.context["catalog"]["name"] == "video"


@pytest.mark.parametrize(
    ("instruction", "contracts", "generic_pagination"),
    [
        ("@video Film 24 risultati", (("count", 24),), False),
        ("@video 24 film", (("count", 24),), False),
        ("@video Film paginati", (), True),
        ("@video Film 24 risultati per pagina", (("page", 24),), True),
        ("@video Film 24 per pagina", (("page", 24),), True),
    ],
)
def test_output_surface_is_removed_before_production_semantic_grounding(
    instruction: str,
    contracts: tuple[tuple[str, int], ...],
    generic_pagination: bool,
) -> None:
    retrieved = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(_snapshot()),
        request=_request(instruction),
    )

    assert retrieved.grounding["status"] == "resolved"
    assert [item["literal"] for item in retrieved.grounding["selections"]] == ["Film"]
    assert retrieved.output_request is not None
    assert retrieved.output_request.contracts == contracts
    assert retrieved.output_request.generic_pagination is generic_pagination
    assert "24" not in retrieved.output_request.semantic_instruction
    assert "pagin" not in retrieved.output_request.semantic_instruction.casefold()


def test_server_flash_intent_uses_exact_sources_not_advisory_queries() -> None:
    """Flash may segment prose; retrieval alone resolves catalog/field/value authority."""
    instruction = "@video Film 24 risultati"
    request = SimpleNamespace(
        instruction=instruction,
        intent="create",
        target={"mode": "create"},
        server_flash_intent={
            "schema_version": 1,
            "intent_ir": {
                "schema_version": 1,
                "operation": "create",
                "target_scope": "new",
                "concept_logic": "all",
                "concepts": [
                    # The query is deliberately wrong: it is advisory only.
                    {"source": "Film", "query": "Sport", "polarity": "include"}
                ],
                "response_format": "unspecified",
                "fallback": "unspecified",
                "ambiguities": [],
            },
            "model_revision": "flash-test",
            "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
            "decoder": "llguidance-1.8.0",
        },
    )

    retrieved = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(_snapshot()), request=request
    )

    assert retrieved.grounding["status"] == "resolved"
    assert retrieved.grounding["catalogs"] == ["video"]
    selection = retrieved.grounding["selections"]
    assert len(selection) == 1
    assert selection[0]["catalog"] == "video"
    assert selection[0]["field"] == "genre"
    assert selection[0]["literal"] == "Film"
    assert selection[0]["type"] == "keyword"
    assert selection[0]["modifiers"] == []
    assert all("Sport" not in item["literal"] for item in retrieved.grounding["selections"])
    assert retrieved.output_request is not None
    assert retrieved.output_request.contracts == (("count", 24),)
    assert "24" not in retrieved.output_request.semantic_instruction


@pytest.mark.parametrize(
    "instruction",
    [
        "@video Film senza paginazione",
        "@video Film non paginato",
        "@video Film, non 24 risultati",
        "@video Film senza 24 risultati",
        "@video Film non voglio 24 risultati",
        "@video Film al massimo 24 risultati",
        "@video Film fino a 24 risultati",
        "@video Film non oltre 24 risultati",
    ],
)
def test_negated_output_language_remains_semantic_residue_and_fails_closed(
    instruction: str,
) -> None:
    retrieved = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(_snapshot()),
        request=_request(instruction),
    )
    assert retrieved.output_request is not None
    assert retrieved.output_request.contracts == ()
    assert retrieved.output_request.generic_pagination is False
    assert retrieved.grounding["status"] == "unsupported"
    assert retrieved.grounding["unresolved"]


@pytest.mark.parametrize(
    "instruction",
    [
        "@video Film -5 risultati",
        "@video Film +5 risultati",
        "@video Film .5 risultati per pagina",
        "@video Film pagina da -5",
    ],
)
def test_signed_or_fractional_output_numbers_are_marked_invalid(
    instruction: str,
) -> None:
    retrieved = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(_snapshot()),
        request=_request(instruction),
    )
    assert retrieved.output_request is not None
    assert retrieved.output_request.contracts == ()
    assert retrieved.output_request.invalid_numeric_output is True


def test_reviewed_value_with_quantifier_word_does_not_trigger_output_question() -> None:
    projection = _refinement_projection()
    projection["catalogs"][0]["fields"].append(
        _field(
            "dialogue_density",
            "catalogs/video.metis",
            60,
            text="densità dei dialoghi",
            domain={
                "kind": "inline",
                "size": 1,
                "values": [
                    {
                        "literal": "Pochi dialoghi",
                        "semantic": _semantic(
                            "reviewed",
                            "catalogs/video.metis",
                            61,
                            text="opera con pochi scambi verbali",
                        ),
                    }
                ],
            },
        )
    )
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: projection))
    basis = retriever.retrieve(
        lease=_lease(snapshot),
        request=_request("@video Film"),
    ).grounding

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="aggiungi Pochi dialoghi",
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "resolved"
    assert [item["literal"] for item in refined.grounding["selections"]] == [
        "Film",
        "Pochi dialoghi",
    ]
    assert refined.output_request is not None
    assert refined.output_request.ambiguous_count is False


def test_quantifier_bound_to_output_noun_requests_exact_total() -> None:
    retrieved = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(_snapshot()),
        request=_request("@video Film pochi risultati"),
    )
    assert retrieved.grounding["status"] == "resolved"
    assert [item["literal"] for item in retrieved.grounding["selections"]] == ["Film"]
    assert retrieved.output_request is not None
    assert retrieved.output_request.ambiguous_count is True


@pytest.mark.parametrize(
    ("instruction", "take_source", "expected_take"),
    [
        (
            "@video Film 24 risultati",
            "take 24 from @video",
            {"mode": "count", "value": 24, "source": "operator_confirmed"},
        ),
        (
            "@video Film paginati",
            "take page from @video",
            {"mode": "page", "page_size": {"mode": "tenant"}},
        ),
        (
            "@video Film 24 per pagina",
            "take page default 24 from @video",
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
def test_production_retriever_and_orchestrator_share_one_output_parse(
    instruction: str,
    take_source: str,
    expected_take: dict[str, Any],
) -> None:
    snapshot = _snapshot()
    lease = SimpleNamespace(snapshot=snapshot, cancellation=threading.Event())

    class Manager:
        @contextmanager
        def operation(self, **_kwargs: object):
            yield lease

    class Model:
        model_revision = "model-test"
        adapter_sha256 = "adapter-test"

        def __init__(self) -> None:
            self.requests: list[Any] = []

        def generate(self, request: Any) -> ModelCandidate:
            self.requests.append(request)
            return ModelCandidate(
                f"""metis 0.43
endpoint demo.test as "Test" {{
  {take_source}
  include where @genre is "Film"
  return response.expanded
}}
""",
                self.model_revision,
                self.adapter_sha256,
            )

    class Compiler:
        toolchain_binding = HASH_C

        def compile(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "ok", "toolchain_binding": self.toolchain_binding}

    request = TurnRequest(
        2,
        "123e4567-e89b-12d3-a456-426614174000",
        snapshot.revision,
        snapshot.semantic_source_revision(),
        "create",
        instruction,
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        None,
        None,
    )
    record = TurnRecord("t" * 24, "s" * 32, request, request.payload_hash)
    model = Model()
    result = BrainOrchestrator(
        retriever=Schema2SnapshotRetriever(_bound_loader(_projection)),
        model=model,
        compiler=Compiler(),
    ).run(
        manager=Manager(),
        session_id="s" * 32,
        token="token-test",
        request=request,
        record=record,
    )

    assert result["outcome"] == "proposed"
    assert model.requests[0].grounding["output_contract"]["take"] == expected_take


def _reviewed_refinement_basis(
    retriever: Schema2SnapshotRetriever, snapshot: ContextSnapshot
) -> dict[str, Any]:
    result = retriever.retrieve(
        lease=_lease(snapshot),
        request=_request("@video Film, Premiato"),
    )
    assert result.grounding["status"] == "resolved"
    assert {item["literal"] for item in result.grounding["selections"]} == {
        "Film",
        "Premiato",
    }
    return result.grounding


def test_explicit_endpoint_label_refinement_preserves_reviewed_filters() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="rendi più chiara l'etichetta dell'endpoint",
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "resolved"
    assert [item["literal"] for item in refined.grounding["selections"]] == [
        "Film",
        "Premiato",
    ]
    assert refined.grounding["nonsemantic_refinement"] == {
        "kind": "endpoint_label",
        "source": "server_basis",
    }


def test_ambiguous_title_refinement_asks_scope_then_applies_only_label_choice() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)
    instruction = "rendi il titolo più chiaro"

    ambiguous = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
        ),
    )
    assert ambiguous.grounding["status"] == "clarify"
    assert [item["literal"] for item in ambiguous.grounding["selections"]] == [
        "Film",
        "Premiato",
    ]
    assert [item["label"] for item in ambiguous.grounding["candidates"]] == [
        "Etichetta dell'endpoint",
        "Metadato @title",
    ]
    label_option = ambiguous.grounding["candidates"][0]["option_ref"]
    field_option = ambiguous.grounding["candidates"][1]["option_ref"]

    label_refine = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
            server_clarification={
                "decisions": [{"kind": "semantic_choice", "resolved_value": label_option}],
                "current_decision": {
                    "kind": "semantic_choice",
                    "resolved_value": label_option,
                },
            },
        ),
    )
    assert label_refine.grounding["status"] == "resolved"
    assert [item["literal"] for item in label_refine.grounding["selections"]] == [
        "Film",
        "Premiato",
    ]
    assert label_refine.grounding["nonsemantic_refinement"]["kind"] == "endpoint_label"

    field_refine = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
            server_clarification={
                "decisions": [{"kind": "semantic_choice", "resolved_value": field_option}],
                "current_decision": {
                    "kind": "semantic_choice",
                    "resolved_value": field_option,
                },
            },
        ),
    )
    assert field_refine.grounding["status"] == "unsupported"
    assert field_refine.grounding["selections"] == []
    assert field_refine.grounding["unresolved"] == ["rendi titolo più chiaro"]


def test_title_refinement_does_not_ask_false_catalog_option_without_title_field() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(second_owner=True)))
    basis = retriever.retrieve(
        lease=_lease(snapshot),
        request=_request("@users country"),
    ).grounding
    assert basis["status"] == "resolved"
    assert basis["catalogs"] == ["users"]

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="rendi il titolo più chiaro",
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "resolved"
    assert refined.grounding["candidates"] == []
    assert refined.grounding["nonsemantic_refinement"] == {
        "kind": "endpoint_label",
        "source": "server_basis",
    }
    assert [item["field"] for item in refined.grounding["selections"]] == ["country"]


@pytest.mark.parametrize(
    "instruction",
    [
        "modifica il formato della risposta",
        "modifica il formato della risposta e rimuovi Film",
        "rendi l'etichetta dell'endpoint più chiara e aggiungi Francia",
        "rinomina l'endpoint usando Sport",
        "cambia il titolo in Francia",
    ],
)
def test_unbounded_structural_refinements_remain_unsupported(instruction: str) -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "unsupported"
    assert refined.grounding["selections"] == []
    assert refined.grounding["unresolved"]


@pytest.mark.parametrize(
    "instruction",
    [
        "sostituisci Film con Francia",
        "cambia Film in Francia",
        "usa Francia invece di Film",
        "rimuovi Film e usa Francia",
    ],
)
def test_explicit_replace_refinement_preserves_every_other_prior_selection(
    instruction: str,
) -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "resolved"
    assert [item["literal"] for item in refined.grounding["selections"]] == [
        "Premiato",
        "Francia",
    ]
    assert all(item["literal"] != "Film" for item in refined.grounding["selections"])


def test_explicit_add_and_remove_apply_one_reviewed_delta_only() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    added = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="aggiungi Francia",
            server_basis_grounding=basis,
        ),
    )
    assert added.grounding["status"] == "resolved"
    assert [item["literal"] for item in added.grounding["selections"]] == [
        "Film",
        "Premiato",
        "Francia",
    ]

    removed = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="rimuovi Film",
            server_basis_grounding=basis,
        ),
    )
    assert removed.grounding["status"] == "resolved"
    assert [item["literal"] for item in removed.grounding["selections"]] == ["Premiato"]


def test_same_field_replace_requires_one_unambiguous_prior_member() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="cambia genre in Documentario",
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "resolved"
    assert [item["literal"] for item in refined.grounding["selections"]] == [
        "Premiato",
        "Documentario",
    ]

    ambiguous_basis = retriever.retrieve(
        lease=_lease(snapshot),
        request=_request("@video Film, Documentario, Premiato"),
    ).grounding
    assert [item["literal"] for item in ambiguous_basis["selections"]] == [
        "Film",
        "Documentario",
        "Premiato",
    ]
    ambiguous = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="cambia genre in Film",
            server_basis_grounding=ambiguous_basis,
        ),
    )
    assert ambiguous.grounding["status"] == "unsupported"
    assert ambiguous.grounding["selections"] == []

    explicit = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="rimuovi Film",
            server_basis_grounding=ambiguous_basis,
        ),
    )
    assert [item["literal"] for item in explicit.grounding["selections"]] == [
        "Documentario",
        "Premiato",
    ]


@pytest.mark.parametrize(
    "instruction",
    [
        "sostituisci Film con Sport",
        "aggiungi mood",
        "sostituisci Francia con Film",
        "sostituisci Film con Francia domani",
        "trasforma Film in Francia",
    ],
)
def test_refinement_draft_open_residue_and_ambiguous_verbs_fail_closed(
    instruction: str,
) -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_refinement_projection))
    basis = _reviewed_refinement_basis(retriever, snapshot)

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction=instruction,
            server_basis_grounding=basis,
        ),
    )

    assert refined.grounding["status"] == "unsupported"
    assert refined.grounding["selections"] == []
    assert all(
        item.get("literal") not in {"Sport", "Francia"} for item in refined.grounding["selections"]
    )


def test_refinement_rejects_draft_value_in_server_basis() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_projection))
    reviewed = retriever.retrieve(lease=_lease(snapshot), request=_request("@video Film"))
    poisoned = copy.deepcopy(reviewed.grounding)
    poisoned["selections"][0]["literal"] = "Sport"
    poisoned["selections"][0]["literals"] = ["Sport"]

    refined = retriever.retrieve(
        lease=_lease(snapshot),
        request=SimpleNamespace(
            instruction="porta il numero di risultati a 30",
            server_basis_grounding=poisoned,
        ),
    )
    assert refined.grounding["status"] == "unsupported"
    assert refined.grounding["selections"] == []
    assert all(item.get("literal") != "Sport" for item in refined.grounding["selections"])


def test_unbound_projection_is_rejected() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(lambda _snapshot: _projection())  # type: ignore[arg-type]
    with pytest.raises(BrainError) as raised:
        retriever.retrieve(lease=_lease(snapshot), request=_request("Film"))
    assert raised.value.code == "STALE_CONTEXT"


def test_draft_values_are_quarantined_and_open_never_materializes() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(_projection))
    draft = retriever.retrieve(lease=_lease(snapshot), request=_request("Sport"))
    assert draft.grounding["status"] == "unsupported"
    assert all(item["literal"] != "Sport" for item in draft.context["fields"][0].get("values", []))

    open_result = retriever.retrieve(lease=_lease(snapshot), request=_request("mood"))
    mood = next(item for item in open_result.context["fields"] if item["name"] == "mood")
    assert mood["domain"] == {"kind": "open"}
    assert "values" not in mood
    assert open_result.grounding["status"] == "unsupported"
    assert open_result.grounding["lookups"][0]["values"] is None


def test_none_domain_is_not_a_value_source() -> None:
    snapshot = _snapshot()
    result = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(snapshot), request=_request("protagonistaSesso Mario")
    )
    assert result.grounding["status"] == "unsupported"
    assert result.grounding["selections"][0]["literal"] is None
    assert result.grounding["unresolved"] == ["Mario"]
    assert all("values" not in field for field in result.context["fields"])


def test_cache_key_includes_snapshot_and_toolchain_identity() -> None:
    calls: list[ContextSnapshot] = []

    def loader(snapshot: ContextSnapshot) -> LoadedProjection:
        calls.append(snapshot)
        return LoadedProjection(
            _projection(), snapshot.revision, snapshot.semantic_source_revision()
        )

    retriever = Schema2SnapshotRetriever(loader, cache_size=2)
    first = _snapshot()
    retriever.retrieve(lease=_lease(first), request=_request("Film"))
    retriever.retrieve(lease=_lease(first), request=_request("title"))
    assert len(calls) == 1
    second = replace(first, revision=HASH_B)
    retriever.retrieve(lease=_lease(second), request=_request("Film"))
    third = replace(first, toolchain_binding=HASH_A)
    retriever.retrieve(lease=_lease(third), request=_request("Film"))
    assert len(calls) == 3
    assert calls[0] is first and calls[1] is second and calls[2] is third


def test_context_is_bounded_and_has_no_draft_or_unannotated_values() -> None:
    snapshot = _snapshot()
    projection = _projection()
    fields = projection["catalogs"][0]["fields"]
    for index in range(MAX_FIELDS):
        fields.append(_field(f"extra{index}", "catalogs/video.metis", 100 + index))
    with pytest.raises(BrainError, match="field context exceeds"):
        Schema2SnapshotRetriever(_bound_loader(projection)).retrieve(
            lease=_lease(snapshot), request=_request("Film")
        )


def test_invalid_catalog_hint_does_not_fall_back_to_owner() -> None:
    snapshot = _snapshot()
    result = Schema2SnapshotRetriever(_bound_loader(_projection)).retrieve(
        lease=_lease(snapshot), request=_request("Film", catalog_hint="missing")
    )
    assert result.grounding["status"] == "unsupported"
    assert result.catalog_candidates == ()


def test_mirror_must_point_directly_to_one_present_owner() -> None:
    snapshot = _snapshot()
    projection = _projection()
    projection["catalogs"][-1]["semanticSource"]["catalog"] = "missing"
    with pytest.raises(BrainError, match="canonical owner"):
        Schema2SnapshotRetriever(_bound_loader(projection)).retrieve(
            lease=_lease(snapshot), request=_request("Film")
        )
