from __future__ import annotations

import json
from pathlib import Path

import metis_model1.cli as cli
from metis_model1.brain_protocol import BrainError, canonical_sha256


def test_latency_cli_emits_only_redacted_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    receipt = {
        "status": "MEASURED_NOT_PROMOTED",
        "identity": {"benchmark_id": "frozen"},
        "denominator": {"pairs": 6},
        "aggregates": {"prefix": {"turn_ms": {"p95": 30_000}}},
        "claims": {"latency_promoted": False},
        "receipt_sha256": canonical_sha256("receipt"),
    }
    monkeypatch.setattr(cli, "run_latency_benchmark", lambda **_kwargs: receipt)

    assert (
        cli.main(
            [
                "brain-latency-benchmark",
                "--config",
                str(tmp_path / "config.json"),
                "--case",
                str(tmp_path / "case.json"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    emitted = json.loads(capsys.readouterr().out)
    assert set(emitted) == {
        "schema_version",
        "operation",
        "status",
        "benchmark_id",
        "denominator",
        "aggregates",
        "claims",
        "receipt_sha256",
        "receipt_path",
    }
    assert "instruction" not in emitted


def test_latency_cli_fails_closed_without_error_message(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    def blocked(**_kwargs):
        raise BrainError("BENCHMARK_INVALID", 400, "SECRET prompt")

    monkeypatch.setattr(cli, "run_latency_benchmark", blocked)
    assert (
        cli.main(
            [
                "brain-latency-benchmark",
                "--config",
                str(tmp_path / "config.json"),
                "--case",
                str(tmp_path / "case.json"),
                "--output",
                str(tmp_path / "receipt.json"),
            ]
        )
        == 1
    )
    emitted = json.loads(capsys.readouterr().out)
    assert emitted == {
        "schema_version": 1,
        "operation": "brain-latency-benchmark",
        "status": "BLOCKED",
        "error_code": "BENCHMARK_INVALID",
    }
