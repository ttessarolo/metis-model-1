from __future__ import annotations

import json

import pytest

from metis_model1 import initial_local_qlora_dataset as builder
from metis_model1.catalog_retrieval_refresh import CatalogRetrievalRefreshError


def _fake_success():
    body = {"status": "verified", "source": "public-synthetic"}
    return {"catalogs": [{"name": "public.video", "fields": []}]}, {
        **body,
        "receipt_sha256": builder._hash(body),
    }


def test_blueprint_is_exact_and_fresh() -> None:
    blueprint = builder.build_blueprint()
    assert len(blueprint["roster"]) == 80
    assert blueprint["counts"] == {
        "train": {"F-1": 22, "F-2": 21, "F-3": 21},
        "dev": {"F-1": 5, "F-2": 5, "F-3": 6},
    }
    assert [row["kind"] for row in blueprint["roster"][:48]].count("canonicality") == 48
    assert [row["kind"] for row in blueprint["roster"][48:64]].count("replay") == 16
    assert (
        max(
            sum(row["group"] == group for row in blueprint["roster"])
            for group in {row["group"] for row in blueprint["roster"]}
        )
        <= 4
    )
    text = json.dumps(blueprint, sort_keys=True).lower()
    assert "successor" not in text and "catalog-maintenance" not in text and "w5xs-" not in text
    assert blueprint["b12_roster_sha256"] == builder.B12_ROSTER_SHA256
    train_roots = {row["template_root"] for row in blueprint["roster"] if row["split"] == "train"}
    dev_roots = {row["template_root"] for row in blueprint["roster"] if row["split"] == "dev"}
    assert len(train_roots) == len(dev_roots) == 3
    assert train_roots.isdisjoint(dev_roots)
    assert "catalog public.video" in builder._source("F-1", 32)
    assert "id clip_32" in builder._source("F-1", 32)
    assert "catalog public.video" in builder._source("F-1", 0)


def test_materialize_uses_fake_oracle_and_verifies(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_describe(snapshot, source):
        calls.append(source)
        return _fake_success()

    monkeypatch.setattr(builder, "_describe_source_in_snapshot", fake_describe)

    class Snapshot:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(builder, "_pinned_snapshot", lambda *args: Snapshot())
    monkeypatch.setattr(builder, "ARTIFACT_ROOT", tmp_path)
    destination = tmp_path / "dataset"
    receipt = builder.materialize(
        metis_root=str(tmp_path / "pinned"), node_path="node", destination=destination
    )
    assert receipt["counts"] == builder.COUNTS
    assert len(calls) == 107  # F1/F2 fixed plus the F3 mutated and fixed checks.
    assert builder.verify(destination) == []
    provenance = [
        json.loads(line) for line in (destination / "provenance.jsonl").read_text().splitlines()
    ]
    mutated = [
        envelope["result"]["result"]
        for item in provenance
        for envelope in item["oracle_envelopes"]
        if envelope["phase"] == "mutated"
    ]
    assert {item["failure_code"] for item in mutated} == {"external_domain_inline_values_forbidden"}
    assert not any("amber" in json.dumps(item) for item in mutated)
    assert (destination / "train.jsonl").read_text()
    assert (destination / "dev.jsonl").read_text()


def test_materialize_does_not_publish_when_staged_verifier_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(builder, "_describe_source_in_snapshot", lambda *_args: _fake_success())

    class Snapshot:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(builder, "_pinned_snapshot", lambda *args: Snapshot())
    monkeypatch.setattr(builder, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(builder, "verify", lambda *_args, **_kwargs: ["forced failure"])
    destination = tmp_path / "dataset"
    with pytest.raises(ValueError, match="staged dataset verification failed"):
        builder.materialize(
            metis_root=str(tmp_path / "pinned"), node_path="node", destination=destination
        )
    assert not destination.exists()


def test_f2_is_one_replacement_and_f3_has_real_failure_diagnostic(monkeypatch, tmp_path) -> None:
    def fake_describe(snapshot, source):
        if " keyword multi enum(" in source and " values [" in source:
            raise CatalogRetrievalRefreshError("legacy declaration")
        return _fake_success()

    monkeypatch.setattr(builder, "_describe_source_in_snapshot", fake_describe)
    assert builder._source("F-2", 1, "mutated").replace(
        'values ["Open", "Closed"]', "enum(2)", 1
    ) == builder._source("F-2", 1)
    example, _ = builder._example(builder._rows()[59], snapshot=object())
    assert '"failure_code": "catalog_domain_rejected"' in example["input"]["request"]
    assert "legacy declaration" not in example["input"]["request"]


def test_f3_surface_oracle_rejects_values_even_when_describe_normalizes_them(monkeypatch) -> None:
    monkeypatch.setattr(builder, "_describe_source_in_snapshot", lambda *_args: _fake_success())
    source = builder._source("F-3", 0, "mutated")
    result = builder._call_with_external_domain_contract(source, snapshot=object())
    assert result["result"]["status"] == "invalid"
    assert result["result"]["failure_code"] == "external_domain_inline_values_forbidden"
    assert "amber" not in json.dumps(result)
