"""Catalog technical roles remain private, exact and snapshot-bound."""

from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_semantic_retrieval import LoadedProjection, Schema2SnapshotRetriever
from metis_model1.brain_technical_authority import (
    TECHNICAL_AUTHORITY_CONTRACT,
    bind_technical_authority,
    validate_technical_authority,
)
from metis_model1.brain_tools import PinnedCatalogProjectionLoader
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT


def _hash(label: str) -> str:
    return bytes_sha256(label.encode())


def _fixture(suffix: str = "alpha", *, binding: str | None = None):
    tenant = f"tenant-{suffix}"
    catalog = f"{suffix}.archive_{suffix}"
    identity, fingerprint, attribute = f"key_{suffix}", f"vector_{suffix}", f"tag_{suffix}"
    profile = f"related_{suffix}"
    source = (
        f'catalog {catalog} {{\n means "Archivio editoriale"\n'
        f' index "synthetic_{suffix}"\n id {identity}\n similarity {fingerprint}\n'
        f" similarity {profile} from {{ @{fingerprint} }}\n"
        f' fields {{\n {identity} keyword means "Identità del contenuto"\n'
        f' {fingerprint} keyword means "Rappresentazione semantica"\n'
        f' {attribute} keyword values ["Aurora" means "Condizione polare"'
        ' aka ["storia artica"]] means "Classificazione editoriale"\n }\n'
        f" returns {{ default {{ {identity} {attribute} }}"
        f" detail {{ {identity} {fingerprint} }} }}\n"
        "}\n"
    ).encode()
    config = f'[tenant]\nid = "{tenant}"\n\n[stdlib]\nlanguage = "0.43"\n'.encode()
    files = (
        SnapshotFile("metis.toml", config, bytes_sha256(config)),
        SnapshotFile("catalogs/archive.metis", source, bytes_sha256(source)),
    )
    snapshot = ContextSnapshot(
        tenant_alias=tenant,
        tenant_id=tenant,
        root_device=1,
        root_inode=1,
        revision=_hash(f"snapshot:{suffix}"),
        toolchain_binding=binding or _hash("synthetic-toolchain"),
        files=files,
        total_bytes=sum(len(item.content) for item in files),
    )

    def semantic(text: str, *, aliases: list[str] | None = None):
        at = {"file": "catalogs/archive.metis", "line": 1}
        result = {"state": "reviewed", "at": at, "means": {"text": text, "at": at}}
        if aliases:
            result["aka"] = {"items": aliases, "at": at}
        return result

    fields = [
        {
            "name": name,
            "type": "keyword",
            "modifiers": [],
            "domain": {"kind": "none"},
            "semantic": semantic(meaning),
        }
        for name, meaning in (
            (identity, "Identità del contenuto"),
            (fingerprint, "Rappresentazione semantica"),
            (attribute, "Classificazione editoriale"),
        )
    ]
    fields[2]["domain"] = {
        "kind": "inline",
        "size": 1,
        "values": [
            {
                "literal": "Aurora",
                "semantic": semantic("Condizione polare", aliases=["storia artica"]),
            }
        ],
    }
    projection = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": tenant,
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": catalog,
                "driver": "opensearch",
                "file": "catalogs/archive.metis",
                "semantic": semantic("Archivio editoriale"),
                "fields": fields,
            }
        ],
    }
    raw = {
        "contract_id": TECHNICAL_AUTHORITY_CONTRACT,
        "tenant": tenant,
        "catalogs": [
            {
                "name": catalog,
                "driver": "opensearch",
                "capabilities": ["search", "record-similarity"],
                "fields": [
                    {key: copy.deepcopy(field[key]) for key in ("name", "type", "modifiers")}
                    for field in fields
                ],
                "id_field": identity,
                "similarity_field": fingerprint,
                "similarity_profiles": [
                    {"name": profile, "fields": [fingerprint], "binding": "opensearch-mlt-ares-v1"}
                ],
                "projections": [
                    {"name": "default", "fields": [identity, attribute]},
                    {"name": "detail", "fields": [identity, fingerprint]},
                ],
            }
        ],
    }
    return snapshot, projection, raw


def _bindings(snapshot: ContextSnapshot) -> dict[str, str]:
    return {
        "context_revision": snapshot.revision,
        "semantic_source_revision": snapshot.semantic_source_revision(),
        "toolchain_binding": snapshot.toolchain_binding,
        "tenant_id": snapshot.tenant_id,
    }


@pytest.mark.parametrize("suffix", ["alpha", "beta"])
def test_renamed_catalog_roles_are_bound_without_domain_constants(suffix: str) -> None:
    snapshot, projection, raw = _fixture(suffix)
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    checked = validate_technical_authority(sealed, projection=projection, **_bindings(snapshot))
    assert checked == sealed
    catalog = checked["catalogs"][0]
    assert catalog["name"] == f"{suffix}.archive_{suffix}"
    assert catalog["id_field"] == f"key_{suffix}"
    assert catalog["similarity_profiles"][0]["fields"] == [f"vector_{suffix}"]
    assert set(checked) == {
        "contract_id",
        "tenant",
        "catalogs",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "sha256",
    }
    assert "index" not in catalog and "semantic" not in catalog
    raw["catalogs"][0]["fields"][0]["name"] = "mutated"
    checked["catalogs"][0]["id_field"] = "mutated"
    assert sealed["catalogs"][0]["fields"][0]["name"] == f"key_{suffix}"
    assert sealed["catalogs"][0]["id_field"] == f"key_{suffix}"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["catalogs"].append(copy.deepcopy(raw["catalogs"][0])),
        lambda raw: raw["catalogs"].clear(),
        lambda raw: raw["catalogs"][0]["fields"].pop(),
        lambda raw: raw["catalogs"][0]["fields"].append(
            copy.deepcopy(raw["catalogs"][0]["fields"][0])
        ),
        lambda raw: raw["catalogs"][0]["fields"][0].update(type="number"),
        lambda raw: raw["catalogs"][0]["fields"][0].update(modifiers=["sort"]),
        lambda raw: raw["catalogs"][0].update(id_field="missing"),
        lambda raw: raw["catalogs"][0].update(similarity_field="other.key"),
        lambda raw: raw["catalogs"][0]["similarity_profiles"][0].update(fields=["missing"]),
        lambda raw: raw["catalogs"][0]["similarity_profiles"][0].update(fields=[]),
        lambda raw: raw["catalogs"][0]["similarity_profiles"].append(
            copy.deepcopy(raw["catalogs"][0]["similarity_profiles"][0])
        ),
        lambda raw: raw["catalogs"][0]["projections"][0].update(fields=["missing"]),
        lambda raw: raw["catalogs"][0]["fields"][0].update(semantic_role="recency"),
        lambda raw: raw["catalogs"][0].update(driver="valkey"),
        lambda raw: raw["catalogs"][0].update(settings={}),
        lambda raw: raw.update(endpoints=[]),
        lambda raw: raw.update(tenant="different"),
    ],
)
def test_technical_sidecar_rejects_incomplete_forged_or_extra_rosters(mutation) -> None:
    snapshot, projection, raw = _fixture()
    mutation(raw)
    with pytest.raises(BrainError):
        bind_technical_authority(raw, projection=projection, **_bindings(snapshot))


@pytest.mark.parametrize(
    "key", ["context_revision", "semantic_source_revision", "toolchain_binding", "tenant"]
)
def test_resealed_stale_authority_remains_rejected(key: str) -> None:
    snapshot, projection, raw = _fixture()
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    sealed[key] = "different" if key == "tenant" else _hash("different")
    sealed["sha256"] = canonical_sha256(
        {name: value for name, value in sealed.items() if name != "sha256"}
    )
    with pytest.raises(BrainError) as raised:
        validate_technical_authority(sealed, **_bindings(snapshot))
    assert raised.value.code == "STALE_CONTEXT"


def test_digest_tampering_fails_and_nullable_absent_roles_remain_absent() -> None:
    snapshot, projection, raw = _fixture()
    raw["catalogs"][0].update(
        id_field=None, similarity_field=None, similarity_profiles=[], projections=[]
    )
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    assert (
        validate_technical_authority(sealed, **_bindings(snapshot))["catalogs"][0]["id_field"]
        is None
    )
    sealed["sha256"] = _hash("forged")
    with pytest.raises(BrainError, match="digest differs"):
        validate_technical_authority(sealed, **_bindings(snapshot))


def test_nested_field_roster_is_exact_and_empty_return_projection_is_legal() -> None:
    snapshot, projection, raw = _fixture()
    nested = {
        "name": "record",
        "type": "object",
        "modifiers": [],
        "domain": {"kind": "none"},
        "fields": [
            {"name": "code", "type": "keyword", "modifiers": [], "domain": {"kind": "none"}}
        ],
    }
    projection["catalogs"][0]["fields"].append(nested)
    raw["catalogs"][0]["fields"].extend(
        [
            {"name": "record", "type": "object", "modifiers": []},
            {"name": "record.code", "type": "keyword", "modifiers": []},
        ]
    )
    raw["catalogs"][0]["projections"].append({"name": "empty", "fields": []})
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    assert sealed["catalogs"][0]["fields"][-1]["name"] == "record.code"


def test_retriever_caches_private_original_and_missing_sidecar_stays_missing() -> None:
    snapshot, projection, raw = _fixture()
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    calls: list[str] = []

    def loader(current):
        calls.append(current.revision)
        return LoadedProjection(
            projection, current.revision, current.semantic_source_revision(), sealed
        )

    retriever = Schema2SnapshotRetriever(loader)
    request = SimpleNamespace(instruction="storia artica")
    first = retriever.retrieve(lease=SimpleNamespace(snapshot=snapshot), request=request)
    assert first.grounding["status"] == "resolved"
    assert first.context["technical_authority"] == sealed
    first.context["technical_authority"]["catalogs"][0]["id_field"] = "modified"
    sealed["catalogs"][0]["id_field"] = "also_modified"
    second = retriever.retrieve(lease=SimpleNamespace(snapshot=snapshot), request=request)
    assert second.context["technical_authority"]["catalogs"][0]["id_field"] == "key_alpha"
    assert calls == [snapshot.revision]
    retriever.close()
    without = Schema2SnapshotRetriever(
        lambda current: LoadedProjection(
            projection, current.revision, current.semantic_source_revision()
        )
    )
    assert (
        "technical_authority"
        not in without.retrieve(lease=SimpleNamespace(snapshot=snapshot), request=request).context
    )
    without.close()


def test_retriever_rejects_sidecar_binding_after_snapshot_change() -> None:
    snapshot, projection, raw = _fixture()
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    retriever = Schema2SnapshotRetriever(
        lambda current: LoadedProjection(
            projection, current.revision, current.semantic_source_revision(), sealed
        )
    )
    changed = replace(snapshot, revision=_hash("changed"))
    with pytest.raises(BrainError) as raised:
        retriever.retrieve(
            lease=SimpleNamespace(snapshot=changed),
            request=SimpleNamespace(instruction="storia artica"),
        )
    assert raised.value.code == "STALE_CONTEXT"
    retriever.close()


@pytest.mark.parametrize("suffix", ["north", "south"])
def test_pinned_runner_emits_renamed_catalog_technical_declarations(suffix: str) -> None:
    root = os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT")
    node = os.environ.get("METIS_MODEL1_NODE")
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    metis_root, node_path = Path(root), Path(node)
    assert metis_root.is_dir() and node_path.is_file(), "configured test authority is unavailable"
    loader = PinnedCatalogProjectionLoader(metis_root=metis_root, node_path=node_path)
    try:
        snapshot, _projection, _raw = _fixture(suffix, binding=loader.toolchain_binding)
        loaded = loader(snapshot)
        assert loaded.technical_authority is not None
        checked = validate_technical_authority(
            loaded.technical_authority, projection=loaded.projection, **_bindings(snapshot)
        )
        catalog = checked["catalogs"][0]
        assert catalog["name"] == f"{suffix}.archive_{suffix}"
        assert catalog["id_field"] == f"key_{suffix}"
        assert catalog["similarity_field"] == f"vector_{suffix}"
        assert catalog["similarity_profiles"] == [
            {
                "name": f"related_{suffix}",
                "fields": [f"vector_{suffix}"],
                "binding": "opensearch-mlt-ares-v1",
            }
        ]
        assert catalog["projections"][0] == {
            "name": "default",
            "fields": [f"key_{suffix}", f"tag_{suffix}"],
        }
        assert "search" in catalog["capabilities"]
    finally:
        loader.close()
