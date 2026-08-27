from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import metis_model1.video_private_artifacts as boundary
from metis_model1.video_private_artifacts import (
    ARTIFACT_ROOT_RELATIVE,
    SENTINEL_NAME,
    VideoArtifactBoundaryError,
    _default_git,
    _prepare_artifact_boundary,
    validate_public_receipt,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL)


def _root(tmp_path: Path, *, ignored: bool = True) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / ".gitignore").write_text("/artifacts/\n" if ignored else "", encoding="utf-8")
    _git(root, "init", "-q")
    return root


def test_positive_boundary_receipt_and_cleanup(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    receipt = _prepare_artifact_boundary(root, _default_git)
    validate_public_receipt(receipt)
    assert receipt["sensitive_material_accessed"] is False
    private = root / ARTIFACT_ROOT_RELATIVE
    assert private.is_dir() and not private.is_symlink()
    assert (private.stat().st_mode & 0o777) == 0o700
    assert not (private / SENTINEL_NAME).exists()
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert after == before


def test_default_git_ignores_path_and_inherited_git_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "invoked"
    fake_git = fake_bin / "git"
    fake_git.write_text(f"#!/bin/sh\nprintf invoked > {marker}\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "outside.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "outside.index"))

    result = _default_git(root, ("status", "--porcelain=v1"))

    assert result.returncode == 0
    assert not marker.exists()


def test_default_git_rejects_user_owned_authority_even_if_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    fake_git = tmp_path / "git"
    fake_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setattr(boundary, "_SYSTEM_GIT_PATH", fake_git)

    with pytest.raises(VideoArtifactBoundaryError):
        _default_git(root, ("status", "--porcelain=v1"))


def test_sentinel_is_created_private_before_cleanup(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    observed: dict[str, int] = {}
    original_unlink = boundary.os.unlink

    def inspect_then_unlink(path, *args, **kwargs):
        if path == SENTINEL_NAME:
            info = boundary.os.stat(path, dir_fd=kwargs["dir_fd"], follow_symlinks=False)
            observed["mode"] = info.st_mode & 0o777
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(boundary.os, "unlink", inspect_then_unlink)
    _prepare_artifact_boundary(root, _default_git)
    assert observed == {"mode": 0o600}


def test_receipt_key_allowlist_and_no_path_or_identity_material(tmp_path: Path) -> None:
    receipt = _prepare_artifact_boundary(_root(tmp_path), _default_git)
    assert set(receipt) == {
        "schema_version",
        "contract_id",
        "status",
        "root_contained",
        "root_not_symlink",
        "root_mode_0700",
        "file_mode_0600",
        "symlinks_rejected",
        "known_cloud_sync_path_absent",
        "universal_cloud_sync_scan_not_performed",
        "sentinel_ignored",
        "sentinel_removed",
        "git_status_unchanged",
        "tracked_collision",
        "sensitive_material_accessed",
    }
    encoded = json.dumps(receipt, sort_keys=True)
    assert "/" not in encoded
    assert "sha256" not in encoded
    assert "source" not in encoded.lower()


def test_wrong_root_mode_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    private = root / ARTIFACT_ROOT_RELATIVE
    private.parent.mkdir()
    private.mkdir(mode=0o755)
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert not (private / SENTINEL_NAME).exists()


def test_symlink_root_fails_without_touching_target(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    private_parent = root / "artifacts"
    private_parent.mkdir()
    (private_parent / "video-catalog-semantics-v1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert list(outside.iterdir()) == []


def test_missing_ignore_rule_fails_and_leaves_private_root_safe(tmp_path: Path) -> None:
    root = _root(tmp_path, ignored=False)
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    private = root / ARTIFACT_ROOT_RELATIVE
    assert private.is_dir() and not private.is_symlink()
    assert (private.stat().st_mode & 0o777) == 0o700
    assert list(private.iterdir()) == []


def test_tracked_payload_anywhere_under_private_root_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    private = root / ARTIFACT_ROOT_RELATIVE
    private.mkdir(parents=True, mode=0o700)
    payload = private / "synthetic-payload"
    payload.write_bytes(b"synthetic tracked payload\n")
    _git(root, "add", ".gitignore")
    _git(root, "add", "-f", str(payload.relative_to(root)))
    _git(root, "commit", "-qm", "synthetic")
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert payload.read_bytes() == b"synthetic tracked payload\n"
    assert not (private / SENTINEL_NAME).exists()


def test_tracked_sentinel_collision_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    private = root / ARTIFACT_ROOT_RELATIVE
    private.mkdir(parents=True, mode=0o700)
    sentinel = private / SENTINEL_NAME
    sentinel.write_bytes(b"tracked synthetic collision\n")
    _git(root, "add", ".gitignore")
    _git(root, "add", "-f", str(sentinel.relative_to(root)))
    _git(root, "commit", "-qm", "synthetic")
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert sentinel.read_bytes() == b"tracked synthetic collision\n"


def test_status_change_is_rejected_and_sentinel_is_removed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    status_calls = 0

    def changing_git(repo: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
        nonlocal status_calls
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if args[:1] == ("status",):
            status_calls += 1
            if status_calls > 1:
                return subprocess.CompletedProcess(
                    result.args, 0, result.stdout + b"synthetic-drift\n", b""
                )
        return result

    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, changing_git)
    assert not (root / ARTIFACT_ROOT_RELATIVE / SENTINEL_NAME).exists()


def test_known_sync_marker_is_rejected_by_testable_core(tmp_path: Path) -> None:
    root = _root(tmp_path / "Dropbox")
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert not (root / ARTIFACT_ROOT_RELATIVE).exists()


def test_hardlink_race_after_path_check_is_rejected(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    private = root / ARTIFACT_ROOT_RELATIVE
    hardlink = private / "synthetic-hardlink"
    original_unlink = boundary.os.unlink
    raced = False

    def link_before_unlink(path, *args, **kwargs):
        nonlocal raced
        if path == SENTINEL_NAME and not raced:
            os_source = private / SENTINEL_NAME
            boundary.os.link(os_source, hardlink, follow_symlinks=False)
            raced = True
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(boundary.os, "unlink", link_before_unlink)
    with pytest.raises(VideoArtifactBoundaryError):
        _prepare_artifact_boundary(root, _default_git)
    assert raced is True
    assert not (private / SENTINEL_NAME).exists()
    assert hardlink.exists()
    hardlink.unlink()


def test_receipt_validator_rejects_extra_sensitive_key(tmp_path: Path) -> None:
    receipt = _prepare_artifact_boundary(_root(tmp_path), _default_git)
    receipt["path"] = str(tmp_path)
    with pytest.raises(VideoArtifactBoundaryError):
        validate_public_receipt(receipt)


def test_public_policy_addendum_has_no_reserved_material() -> None:
    policy = json.loads(
        Path("manifests/video-private-artifact-policy-v1.json").read_text(encoding="utf-8")
    )
    assert policy["root_relative"] == "artifacts/video-catalog-semantics-v1"
    assert policy["tracked_payloads_allowed"] is False
    assert policy["cloud_sync"] == "known_path_markers_only"
    assert policy["universal_cloud_sync_scan"] == "not_performed"
    assert policy["root_mode"] == "0700"
    assert policy["file_mode"] == "0600"
    encoded = json.dumps(policy, sort_keys=True).lower()
    assert "sha256" not in encoded
    assert "password" not in encoded
    assert "token" not in encoded
    assert "secret" not in encoded
