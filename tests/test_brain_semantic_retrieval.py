from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_semantic_retrieval import (
    MAX_FIELDS,
    LoadedProjection,
    Schema2SnapshotRetriever,
)
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


def test_clarification_option_is_path_inert_and_rebinds_selected_catalog() -> None:
    snapshot = _snapshot()
    retriever = Schema2SnapshotRetriever(_bound_loader(lambda: _projection(second_owner=True)))
    first = retriever.retrieve(lease=_lease(snapshot), request=_request("crea endpoint"))
    users = next(item for item in first.catalog_candidates if item["catalog"] == "users")
    assert "." not in users["option_ref"]
    request = SimpleNamespace(
        instruction="crea endpoint country",
        clarification_response={
            "option_ref": users["option_ref"],
            "context_revision": snapshot.revision,
            "semantic_source_revision": snapshot.semantic_source_revision(),
        },
    )
    selected = retriever.retrieve(lease=_lease(snapshot), request=request)
    assert selected.context["catalog"]["name"] == "users"
    assert selected.grounding["catalogs"] == ["users"]

    request.clarification_response["context_revision"] = HASH_B
    with pytest.raises(BrainError) as raised:
        retriever.retrieve(lease=_lease(snapshot), request=request)
    assert raised.value.code == "SEMANTIC_SOURCE_STALE"


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
