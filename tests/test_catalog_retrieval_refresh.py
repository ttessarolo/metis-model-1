from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import metis_model1.catalog_retrieval_refresh as refresh
from metis_model1 import catalog_maintenance_pin as pin

ROOT = Path(__file__).resolve().parents[1]
METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
NODE = Path("/Users/tommasotessarolo/.hermes/node/bin/node")
CAN_RUN_PINNED_RUNTIME = METIS_ROOT.is_dir() and NODE.is_file()


def _pin_report() -> dict[str, str]:
    return {
        "status": "verified_local_cooperative",
        "pin_id": "catalog-domain-maintenance/2026-08-24-v1",
        "revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "tree": "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af",
        "manifest_sha256": (
            "sha256:0e3a4d9050f7ee9d6584fb284a0671f0e0eaf398597be29806943d7b6bffa987"
        ),
    }


def _assert_no_values(value: object) -> None:
    if isinstance(value, dict):
        assert "values" not in value
        for item in value.values():
            _assert_no_values(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_values(item)


def test_snapshot_policy_allows_only_the_exact_verified_node(tmp_path: Path) -> None:
    snapshot = (tmp_path / "snapshot").resolve()
    node = (tmp_path / "runtime" / "node").resolve()

    policy = refresh._snapshot_policy(snapshot, node)

    assert f'(allow file-read* (literal "{node}"))' in policy
    assert f'(allow file-read* (subpath "{node.parent}"))' not in policy
    assert f'(allow file-read* (subpath "{snapshot}"))' in policy
    assert "not_same_uid_adversary_resistant" in refresh.NONCLAIMS


def test_runtime_node_verification_normalizes_pin_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = tmp_path / "node"

    def reject(*_args: object, **_kwargs: object) -> bytes:
        raise pin.CatalogMaintenancePinError("sensitive pin detail")

    monkeypatch.setattr(pin, "_verify_node", reject)

    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="verification failed"):
        refresh._verify_runtime_node(node, {})


def test_runtime_node_postcheck_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = tmp_path / "node"
    monkeypatch.setattr(pin, "_verify_node", lambda *_args, **_kwargs: b"after")

    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="post-check mismatch"):
        refresh._verify_runtime_node(node, {}, expected=b"before")


@pytest.fixture(scope="module")
def public_report() -> dict[str, object]:
    if not CAN_RUN_PINNED_RUNTIME:
        pytest.skip("pinned Metis checkout/runtime unavailable")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            pin, "verify_catalog_maintenance_pin", lambda *_args, **_kwargs: _pin_report()
        )
        return refresh.run_catalog_retrieval_refresh(METIS_ROOT, NODE)


def test_public_synthetic_refresh_is_archive_bound_and_redacted(
    public_report: dict[str, object],
) -> None:
    report = public_report

    assert report["status"] == "verified_local_cooperative"
    assert report["counts"] == {
        "queries_in": 8,
        "queries_out": 8,
        "queries_distinct": 8,
        "queries_gaps": 0,
    }
    assert [item["summary"]["kind"] for item in report["queries"]] == [
        "describe",
        "inline",
        "list",
        "enum",
        "enum",
        "enum",
        "open",
        "none",
    ]
    assert report["queries"][3]["summary"]["nature"] == "editorial"
    assert report["queries"][4]["summary"]["nature"] == "reflected"
    assert report["policy"]["model_output_observed"] is False
    assert report["policy"]["training_authorized"] is False
    _assert_no_values(report)
    assert refresh.validate_catalog_retrieval_refresh_report(report) == []


@pytest.mark.skipif(not CAN_RUN_PINNED_RUNTIME, reason="pinned Metis checkout/runtime unavailable")
def test_invalid_query_has_no_partial_stdout_and_is_deterministic() -> None:
    manifest, _ = refresh._load_manifest()
    records, _ = refresh._fixture_records(refresh.FIXTURE_ROOT, manifest)
    with refresh._pinned_snapshot(METIS_ROOT, NODE) as snapshot:
        refresh._copy_fixture(refresh.FIXTURE_ROOT, snapshot.fixture, records)
        query = refresh.CatalogQuery("bad", "values", "video", "does_not_exist", {})
        messages: list[str] = []
        for _ in range(2):
            with pytest.raises(refresh.CatalogRetrievalRefreshError) as error:
                snapshot.run(query)
            messages.append(str(error.value))
        assert messages[0] == messages[1]
        assert "stdout=sha256:" in messages[0]


def test_manifest_and_fixture_mutations_fail_closed(tmp_path: Path) -> None:
    manifest, _ = refresh._load_manifest()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    for item in manifest["files"]:
        source = refresh.FIXTURE_ROOT / Path(*item["path"].split("/"))
        target = fixture / Path(*item["path"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    changed = fixture / "metis.toml"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="fixture file drift"):
        refresh._fixture_records(fixture, manifest)
    changed.write_bytes((refresh.FIXTURE_ROOT / "metis.toml").read_bytes())

    extra = fixture / "extra.metis"
    extra.write_text("metis 0.43\n", encoding="utf-8")
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="extra or missing"):
        refresh._fixture_records(fixture, manifest)
    extra.unlink()

    symlink = fixture / "symlink.metis"
    symlink.symlink_to(fixture / "metis.toml")
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="symlink"):
        refresh._fixture_records(fixture, manifest)
    symlink.unlink()

    records, _ = refresh._fixture_records(fixture, manifest)
    changed.write_text(changed.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="changed before copy"):
        refresh._copy_fixture(fixture, tmp_path / "copied", records)


def test_query_roster_and_pin_mutations_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, _ = refresh._load_manifest()
    expected = manifest["queries"][0]["expected"]
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="path-inert"):
        refresh._query_from_manifest(
            {
                "id": "bad",
                "operation": "values",
                "catalog": "../video",
                "field": "title",
                "expected": expected,
            }
        )
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="requires catalog and field"):
        refresh._query_from_manifest(
            {
                "id": "bad",
                "operation": "values",
                "catalog": None,
                "field": None,
                "expected": expected,
            }
        )

    monkeypatch.setattr(
        pin, "validate_catalog_maintenance_pin_contract", lambda _root: ["pin drift"]
    )
    with pytest.raises(refresh.CatalogRetrievalRefreshError, match="pin drift"):
        refresh.run_catalog_retrieval_refresh(METIS_ROOT, NODE)


def test_resigned_report_mutations_fail_closed(public_report: dict[str, object]) -> None:
    def resign(report: dict[str, object]) -> None:
        report["receipt_sha256"] = refresh._report_hash(report)

    mutations = []

    changed_id = deepcopy(public_report)
    changed_id["queries"][0]["id"] = "forged-id"  # type: ignore[index]
    mutations.append(changed_id)

    changed_query = deepcopy(public_report)
    changed_query["queries"][0]["query"]["catalog"] = "video"  # type: ignore[index]
    mutations.append(changed_query)

    duplicate_id = deepcopy(public_report)
    duplicate_id["queries"][1]["id"] = duplicate_id["queries"][0]["id"]  # type: ignore[index]
    mutations.append(duplicate_id)

    changed_upstream = deepcopy(public_report)
    changed_upstream["upstream"]["manifest_sha256"] = "sha256:" + "0" * 64  # type: ignore[index]
    mutations.append(changed_upstream)

    changed_output = deepcopy(public_report)
    changed_output["queries"][0]["output_sha256"] = "sha256:" + "0" * 64  # type: ignore[index]
    mutations.append(changed_output)

    changed_inner_receipt = deepcopy(public_report)
    changed_inner_receipt["queries"][0]["receipt_sha256"] = "sha256:" + "0" * 64  # type: ignore[index]
    mutations.append(changed_inner_receipt)

    changed_summary = deepcopy(public_report)
    changed_summary["queries"][0]["summary"]["field_count"] = 10  # type: ignore[index]
    mutations.append(changed_summary)

    for attacked in mutations:
        resign(attacked)
        assert refresh.validate_catalog_retrieval_refresh_report(attacked)


def test_execution_schema_digest_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    public_report: dict[str, object],
) -> None:
    original = refresh._stable_bytes

    def drifted(path: Path, label: str, limit: int) -> bytes:
        raw = original(path, label, limit)
        if path.name == refresh.SCHEMA_PATH.name:
            return raw.replace(b'"verified_local_cooperative"', b'"forged_local_cooperative"')
        return raw

    monkeypatch.setattr(refresh, "_stable_bytes", drifted)
    errors = refresh.validate_catalog_retrieval_refresh_report(public_report)
    assert errors == ["catalog retrieval execution schema differs from its fixed digest"]
