import json

import pytest

from metis_model1 import initial_local_qlora_b12 as b12


def test_frozen_b12_contracts_are_exact_and_terminal() -> None:
    roster, freeze, baseline = b12._load_contracts(
        b12.DEFAULT_ROSTER, b12.DEFAULT_FREEZE, b12.DEFAULT_BASELINE
    )
    assert len(roster["tasks"]) == 12
    assert [task["task_id"] for task in roster["tasks"]] == [
        task["task_id"] for task in freeze["tasks"]
    ]
    assert baseline["counts"]["semantic_correct"] == 11


def test_frozen_b12_file_drift_is_rejected(tmp_path) -> None:
    roster = json.loads(b12.DEFAULT_ROSTER.read_text())
    roster["tasks"] = roster["tasks"][:-1]
    tampered = tmp_path / "roster.json"
    tampered.write_text(json.dumps(roster))
    with pytest.raises(b12.B12ReplayError, match="identity drift"):
        b12._load_contracts(tampered, b12.DEFAULT_FREEZE, b12.DEFAULT_BASELINE)


def test_source_extraction_is_single_source_only() -> None:
    source, error = b12._extract_source("```metis\nmetis 0.43\nendpoint x { }\n```")
    assert error is None and source == "metis 0.43\nendpoint x { }\n"
    assert b12._extract_source("text\n```metis\nmetis 0.43\n```")[0] is None


def test_b12_semantic_score_requires_both_ir_and_ast() -> None:
    task = {"family": "F-1"}
    frozen = {
        "truth": {
            "target": {
                "normalized_ir": {"node": "Endpoint", "name": "x"},
                "ast_inventory": {"elements": [{"name": "x"}]},
            }
        }
    }
    result = {
        "status": "ok",
        "ir": {"value": {"node": "Endpoint", "name": "x", "provenance": {"line": 1}}},
        "ast": {"inventory": {"elements": [{"name": "x"}]}},
    }
    assert b12._score(task, frozen, "metis 0.43\n", result, None)[0] is True
    result["ast"] = {"inventory": {"elements": [{"name": "y"}]}}
    success, category, details = b12._score(task, frozen, "metis 0.43\n", result, None)
    assert success is False and category == "semantic" and details["ir_match"] is True


def test_b12_selection_receipt_cannot_claim_observed_b12(tmp_path, monkeypatch) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.json").write_text("{}")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    monkeypatch.setattr(
        b12,
        "verify_selection_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(b12.RuntimeContractError("b12 observed")),
    )
    body = {
        "schema_version": 1,
        "status": "selected",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16_only",
        "b12_observed": True,
        "selected_step": 25,
        "checkpoint_manifest_sha256": b12._prefixed_sha256(adapter / "manifest.json"),
        "adapter_sha256": b12._prefixed_sha256(adapter / "adapters.safetensors"),
        "base_semantic_correct": 1,
        "selected_semantic_correct": 1,
    }
    receipt = {**body, "selection_sha256": b12._canonical_hash(body)}
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(b12.B12ReplayError, match="selection receipt"):
        b12._selection(path, adapter, tmp_path / "dataset-receipt.json")


def test_strict_selection_failure_stops_before_terminal_output(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    output = project / "artifacts/initial-local-qlora-v1/run-v1/b12-adapter"
    monkeypatch.setattr(b12, "PROJECT_ROOT", project)
    monkeypatch.setattr(b12, "DEFAULT_OUTPUT", output)
    monkeypatch.setattr(
        b12,
        "_selection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            b12.B12ReplayError("strict selection rejected")
        ),
    )
    with pytest.raises(b12.B12ReplayError, match="strict selection rejected"):
        b12.replay_b12(
            adapter=tmp_path / "adapter",
            selection_receipt=tmp_path / "selection.json",
            output=output,
        )
    assert not output.exists()


def test_b12_evidence_roster_rejects_symlink(tmp_path) -> None:
    output = tmp_path / "b12"
    output.mkdir()
    (output / "worker.stderr.log").write_text("")
    (output / "linked").symlink_to(output / "worker.stderr.log")
    with pytest.raises(b12.B12ReplayError, match="unsafe"):
        b12._evidence_records(output)
