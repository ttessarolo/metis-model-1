from __future__ import annotations

import json

import metis_model1.cli as cli
from metis_model1.video_private_artifacts import VideoArtifactBoundaryError


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
