from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import metis_model1.video_private_artifacts as boundary
import metis_model1.video_private_io as private_io
import metis_model1.video_semantics_private_runner as runner
import metis_model1.video_source_extraction as extraction
from metis_model1.video_private_io import (
    MAX_PRIVATE_FILE_BYTES,
    read_private_json,
    write_private_bytes_atomic,
)
from metis_model1.video_semantics_contracts import (
    FIXTURE_ROOT,
    literal_sha256,
    load_json,
    manifest_digest,
    semantic_concept_id,
)
from metis_model1.video_semantics_private_runner import (
    PRIVATE_ACQUISITION_BUNDLE,
    PRIVATE_ONTOLOGY_JSONL,
    PRIVATE_SOURCE_FREEZE,
    PRIVATE_SOURCE_TEXT_BUNDLE,
    VideoSemanticsPrivateRunnerError,
    acquire_sources,
    blocked_result,
    extract_sources,
    freeze_sources,
    validate_ontology,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def isolated_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".gitignore").write_text("/artifacts/\n", encoding="utf-8")
    _git(project, "init", "-q")
    source = tmp_path / "authorized-source"
    source.mkdir()
    (source / "source.txt").write_text("synthetic editorial source", encoding="utf-8")
    monkeypatch.setattr(boundary, "PROJECT_ROOT", project)
    monkeypatch.setattr(private_io, "PROJECT_ROOT", project)
    monkeypatch.setattr(runner, "PROJECT_ROOT", project)
    return project, source


def _private(project: Path, relative: str) -> Path:
    return project / "artifacts/video-catalog-semantics-v1" / relative


def test_acquire_and_freeze_are_private_atomic_and_public_safe(isolated_runner) -> None:
    project, source = isolated_runner
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project,
        check=True,
        capture_output=True,
    ).stdout
    acquired = acquire_sources(source, run_id="run-fixed-0001")
    assert acquired["status"] == "VALID"
    assert acquired["private_roster_complete"] is True
    assert acquired["gaps"] == 0
    encoded = json.dumps(acquired, sort_keys=True)
    assert str(source) not in encoded
    assert "source.txt" not in encoded
    assert "sha256:" not in encoded
    assert acquire_sources(source, run_id="run-fixed-0002") == acquired

    bundle_path = _private(project, PRIVATE_ACQUISITION_BUNDLE)
    assert bundle_path.is_file() and bundle_path.stat().st_mode & 0o777 == 0o600
    bundle = read_private_json(PRIVATE_ACQUISITION_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    assert bundle["locator_registry"]["root_locator"] == str(source.resolve())

    frozen = freeze_sources()
    assert frozen == {
        "schema_version": 1,
        "operation": "freeze-sources",
        "status": "VALID",
        "private_roster_complete": True,
        "gaps": 0,
        "sensitivity": "internal_confidential",
        "raw_payloads_present": False,
        "error_codes": [],
    }
    assert _private(project, PRIVATE_SOURCE_FREEZE).is_file()
    assert freeze_sources() == frozen
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project,
        check=True,
        capture_output=True,
    ).stdout
    assert after == before


def test_idempotent_acquisition_blocks_any_stable_evidence_drift(isolated_runner) -> None:
    _project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    (source / "source.txt").write_text("changed synthetic source", encoding="utf-8")
    with pytest.raises(VideoSemanticsPrivateRunnerError):
        acquire_sources(source, run_id="run-fixed-0002")


def test_validate_ontology_reads_only_fixed_private_artifacts(isolated_runner) -> None:
    _project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    freeze_sources()
    extracted = extract_sources()
    assert extracted["status"] == "VALID"
    bundle = read_private_json(PRIVATE_ACQUISITION_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    source_ref = bundle["manifest"]["sources"][0]["source_ref"]
    source_envelope = read_private_json(PRIVATE_SOURCE_TEXT_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    source_locator = extraction.private_unit_roster(source_envelope)[source_ref][0]
    concept = load_json(FIXTURE_ROOT / "concept.json")
    concept["editorial_source_ref"] = source_ref
    concept["source_locator"] = source_locator
    concept["concept_id"] = semantic_concept_id(concept)
    payload = (json.dumps(concept, ensure_ascii=False) + "\n").encode("utf-8")
    write_private_bytes_atomic(PRIVATE_ONTOLOGY_JSONL, payload)
    roster_body = {
        "schema_version": 1,
        "artifact_kind": "video-semantics/unit-disposition-roster-v1",
        "source_envelope_sha256": manifest_digest(source_envelope),
        "ontology_sha256": literal_sha256(payload),
        "entries": [
            {
                "source_ref": source_ref,
                "source_locator": source_locator,
                "disposition": "concepts",
                "reason": "synthetic concept retained",
                "concept_ids": [concept["concept_id"]],
            }
        ],
        "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
    }
    roster = dict(roster_body, roster_sha256=manifest_digest(roster_body))
    write_private_bytes_atomic(
        runner.PRIVATE_UNIT_DISPOSITION_ROSTER,
        (json.dumps(roster, sort_keys=True) + "\n").encode("utf-8"),
    )
    result = validate_ontology()
    assert result["status"] == "VALID"
    assert result["ontology_valid"] is True
    assert result["private_roster_complete"] is True
    assert result["gaps"] == 0
    assert "source_ref" not in json.dumps(result, sort_keys=True)


def test_validate_ontology_requires_current_source_freeze(isolated_runner) -> None:
    _project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    with pytest.raises(VideoSemanticsPrivateRunnerError):
        validate_ontology()


def test_extract_sources_rejects_synthetic_evidence_before_persisting(
    isolated_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    freeze_sources()
    bundle = read_private_json(PRIVATE_ACQUISITION_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    outcome = extraction.extract_private_source(bundle, runner=extraction_test_runner())
    monkeypatch.setattr(runner, "extract_private_source", lambda document: outcome)
    with pytest.raises(VideoSemanticsPrivateRunnerError):
        extract_sources()
    assert not _private(project, PRIVATE_SOURCE_TEXT_BUNDLE).exists()


@pytest.mark.skipif(
    not Path("/usr/bin/sandbox-exec").is_file(),
    reason="requires the pinned macOS sandbox boundary",
)
def test_real_extraction_is_idempotent_and_existing_drift_blocks(isolated_runner) -> None:
    project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    freeze_sources()
    first = extract_sources()
    assert first["status"] == "VALID"
    assert extract_sources() == first

    source_envelope = read_private_json(PRIVATE_SOURCE_TEXT_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    source_envelope["sources"][0]["units"][0]["text"] = "tampered"
    monkeypatch_target = runner.read_private_json

    def drifted(relative_path, max_bytes):
        if relative_path == PRIVATE_SOURCE_TEXT_BUNDLE:
            return source_envelope
        return monkeypatch_target(relative_path, max_bytes)

    original = runner.read_private_json
    runner.read_private_json = drifted
    try:
        with pytest.raises(VideoSemanticsPrivateRunnerError):
            extract_sources()
    finally:
        runner.read_private_json = original
    assert _private(project, PRIVATE_SOURCE_TEXT_BUNDLE).is_file()


def extraction_test_runner() -> object:
    """Keep the runner test independent of the production sandbox process."""

    class FakeRunner:
        def __call__(self, argv, env, timeout, stdin_fd):
            command = list(argv)[3:]
            if command[0] == "/bin/cat" and len(command) > 1:
                return subprocess.CompletedProcess(argv, 1, b"", b"denied")
            if command[0] in {"/usr/bin/touch", "/usr/bin/nc"}:
                return subprocess.CompletedProcess(argv, 1, b"", b"denied")
            if stdin_fd is not None:
                prefix = os.pread(stdin_fd, 64, 0)
                if prefix == b"synthetic-sandbox-canary":
                    return subprocess.CompletedProcess(argv, 0, prefix, b"")
            return subprocess.CompletedProcess(argv, 0, b"synthetic extracted\n", b"")

    import os

    return FakeRunner()


def test_validate_ontology_rejects_tampered_source_freeze(
    isolated_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    freeze_sources()
    original = runner.read_private_json

    def tampered(relative_path, max_bytes):
        value = original(relative_path, max_bytes)
        if relative_path == PRIVATE_SOURCE_FREEZE:
            value["status"] = "TAMPERED"
        return value

    monkeypatch.setattr(runner, "read_private_json", tampered)
    with pytest.raises(VideoSemanticsPrivateRunnerError):
        validate_ontology()


def test_source_root_inside_repository_is_rejected_before_acquisition(isolated_runner) -> None:
    project, _source = isolated_runner
    inside = project / "private-input"
    inside.mkdir()
    (inside / "input.txt").write_text("synthetic", encoding="utf-8")
    with pytest.raises(VideoSemanticsPrivateRunnerError) as raised:
        acquire_sources(inside, run_id="run-fixed-0001")
    assert raised.value.code == "SOURCE_ROOT_NOT_ISOLATED"
    assert not _private(project, PRIVATE_ACQUISITION_BUNDLE).exists()


def test_repository_ancestor_is_rejected_before_any_census(isolated_runner) -> None:
    project, _source = isolated_runner
    with pytest.raises(VideoSemanticsPrivateRunnerError) as raised:
        acquire_sources(project.parent, run_id="run-fixed-0001")
    assert raised.value.code == "SOURCE_ROOT_NOT_ISOLATED"
    assert not _private(project, PRIVATE_ACQUISITION_BUNDLE).exists()


def test_tampered_bundle_blocks_freeze_without_leaking_details(isolated_runner) -> None:
    _project, source = isolated_runner
    acquire_sources(source, run_id="run-fixed-0001")
    original = runner.read_private_json

    def tampered(relative_path, max_bytes):
        value = original(relative_path, max_bytes)
        value["bundle_sha256"] = "sha256:" + "0" * 64
        return value

    runner.read_private_json = tampered
    try:
        with pytest.raises(VideoSemanticsPrivateRunnerError) as raised:
            freeze_sources()
        assert str(raised.value) == "PRIVATE_OPERATION_BLOCKED"
    finally:
        runner.read_private_json = original


def test_blocked_result_is_finite_and_redacted() -> None:
    result = blocked_result("freeze-sources", "SOURCE_ROOT_NOT_ISOLATED")
    assert result["status"] == "BLOCKED"
    assert result["error_codes"] == ["SOURCE_ROOT_NOT_ISOLATED"]
    assert set(result) == {
        "schema_version",
        "operation",
        "status",
        "private_roster_complete",
        "gaps",
        "sensitivity",
        "raw_payloads_present",
        "error_codes",
    }
    arbitrary = blocked_result("/private/synthetic-secret-path")
    assert arbitrary["operation"] == "private-operation"
    assert "/private/" not in json.dumps(arbitrary, sort_keys=True)
