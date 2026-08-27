from __future__ import annotations

import json

import pytest

import metis_model1.cli as cli
from metis_model1.video_private_artifacts import VideoArtifactBoundaryError
from metis_model1.video_semantics_private_runner import VideoSemanticsPrivateRunnerError
from metis_model1.video_source_extraction import VideoSourceExtractionError


def _receipt() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "video-private-artifact-boundary-v1",
        "status": "VALID",
        "root_contained": True,
        "root_not_symlink": True,
        "root_mode_0700": True,
        "file_mode_0600": True,
        "symlinks_rejected": True,
        "known_cloud_sync_path_absent": True,
        "universal_cloud_sync_scan_not_performed": True,
        "sentinel_ignored": True,
        "sentinel_removed": True,
        "git_status_unchanged": True,
        "tracked_collision": False,
        "sensitive_material_accessed": False,
    }


def test_bootstrap_artifacts_emits_only_the_public_receipt(monkeypatch, capsys) -> None:
    receipt = _receipt()
    monkeypatch.setattr(cli, "prepare_artifact_boundary", lambda: receipt)
    monkeypatch.setattr(cli, "validate_public_receipt", lambda value: None)

    assert cli.main(["video-semantics", "bootstrap-artifacts"]) == 0
    assert json.loads(capsys.readouterr().out) == receipt


def test_bootstrap_artifacts_redacts_internal_failure(monkeypatch, capsys) -> None:
    def fail() -> dict[str, object]:
        raise VideoArtifactBoundaryError("sensitive local detail must not escape")

    monkeypatch.setattr(cli, "prepare_artifact_boundary", fail)

    assert cli.main(["video-semantics", "bootstrap-artifacts"]) == 1
    output = capsys.readouterr().out
    assert "sensitive local detail" not in output
    assert json.loads(output) == {
        "schema_version": 1,
        "operation": "bootstrap-artifacts",
        "status": "BLOCKED",
        "error_code": "ARTIFACT_BOUNDARY_INVALID",
    }


def _private_result(operation: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": operation,
        "status": "VALID",
        "private_roster_complete": True,
        "gaps": 0,
        "sensitivity": "internal_confidential",
        "raw_payloads_present": False,
        "error_codes": [],
    }


def test_private_video_commands_emit_only_runner_results(monkeypatch, capsys, tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    expected = {
        **_private_result("acquire-video-source-roster"),
        "sensitivity": "internal_editorial",
    }
    monkeypatch.setattr(cli, "acquire_sources", lambda value: expected)
    assert cli.main(["video-semantics", "acquire-sources", "--source-root", str(source)]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    expected = _private_result("freeze-sources")
    monkeypatch.setattr(cli, "freeze_sources", lambda: expected)
    assert cli.main(["video-semantics", "freeze-sources"]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    expected = {**_private_result("validate-ontology"), "ontology_valid": True}
    monkeypatch.setattr(cli, "validate_ontology", lambda: expected)
    assert cli.main(["video-semantics", "validate-ontology"]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    expected = {
        "schema_version": 1,
        "operation": "extract-sources",
        "status": "VALID",
        "private_roster_complete": True,
        "sandbox_verified": True,
        "format_supported": True,
        "raw_payloads_present": False,
        "gaps": 0,
        "error_codes": [],
    }
    monkeypatch.setattr(cli, "extract_sources", lambda: expected)
    assert cli.main(["video-semantics", "extract-sources"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_private_video_command_redacts_store_failure(monkeypatch, capsys) -> None:
    def fail() -> dict[str, object]:
        raise VideoSemanticsPrivateRunnerError("PRIVATE_OPERATION_BLOCKED")

    monkeypatch.setattr(cli, "freeze_sources", fail)
    assert cli.main(["video-semantics", "freeze-sources"]) == 1
    output = capsys.readouterr().out
    assert "/Users/" not in output
    assert json.loads(output) == {
        "schema_version": 1,
        "operation": "freeze-sources",
        "status": "BLOCKED",
        "private_roster_complete": False,
        "gaps": 1,
        "sensitivity": "internal_confidential",
        "raw_payloads_present": False,
        "error_codes": ["PRIVATE_OPERATION_BLOCKED"],
    }


def test_extract_command_redacts_extraction_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "extract_sources",
        lambda: (_ for _ in ()).throw(VideoSourceExtractionError("EXTRACTION_FAILED")),
    )
    assert cli.main(["video-semantics", "extract-sources"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "schema_version": 1,
        "operation": "extract-sources",
        "status": "INVALID",
        "private_roster_complete": False,
        "sandbox_verified": False,
        "format_supported": True,
        "raw_payloads_present": False,
        "gaps": 1,
        "error_codes": ["EXTRACTION_FAILED"],
    }


def test_cli_rejects_arbitrary_runner_mapping_and_generic_exception(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "freeze_sources",
        lambda: {
            **_private_result("/private/synthetic-secret-path"),
            "private_text": "must-not-escape",
        },
    )
    assert cli.main(["video-semantics", "freeze-sources"]) == 1
    output = capsys.readouterr().out
    assert "/private/" not in output
    assert "must-not-escape" not in output
    assert json.loads(output)["operation"] == "freeze-sources"

    def fail() -> dict[str, object]:
        raise RecursionError("/private/synthetic-secret-path")

    monkeypatch.setattr(cli, "validate_ontology", fail)
    assert cli.main(["video-semantics", "validate-ontology"]) == 1
    output = capsys.readouterr().out
    assert "/private/" not in output
    assert json.loads(output)["operation"] == "validate-ontology"


def test_public_result_validator_rejects_semantic_contradictions() -> None:
    invalid_schema = _private_result("freeze-sources")
    invalid_schema["schema_version"] = True
    incomplete_valid = _private_result("freeze-sources")
    incomplete_valid["private_roster_complete"] = False
    unsupported_valid = {
        "schema_version": 1,
        "operation": "extract-sources",
        "status": "VALID",
        "private_roster_complete": True,
        "sandbox_verified": True,
        "format_supported": False,
        "raw_payloads_present": False,
        "gaps": 0,
        "error_codes": [],
    }
    for command, value in (
        ("freeze-sources", invalid_schema),
        ("freeze-sources", incomplete_valid),
        ("extract-sources", unsupported_valid),
    ):
        with pytest.raises(ValueError):
            cli._validated_video_result(command, value)
