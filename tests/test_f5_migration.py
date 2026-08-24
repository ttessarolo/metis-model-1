from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.f5_migration as f5
from metis_model1.f5_migration import F5FixtureError, F5ResultError

ROOT = Path(__file__).resolve().parents[1]
RUN_NONCE = "1" * 64


def _fixture_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "public-synthetic"
    legacy = workspace / "legacy"
    base = workspace / "base"
    (legacy / "endpoints").mkdir(parents=True)
    (legacy / "blocks").mkdir()
    (legacy / "queries").mkdir()
    (legacy / "properties").mkdir()
    (legacy / "endpoints" / "endpoint.json").write_text(
        json.dumps(
            {"id": "endpoint", "title": "Synthetic", "propertyId": "play", "blockId": "main"}
        )
    )
    (legacy / "blocks" / "main.json").write_text(
        json.dumps({"id": "main", "title": "Main", "isPage": True, "blocks": []})
    )
    (legacy / "queries" / "query.json").write_text(
        json.dumps(
            {"id": "query", "filter": [], "include": [], "exclude": [], "boost": [], "order": []}
        )
    )
    (legacy / "properties" / "play.json").write_text(json.dumps({"id": "play", "title": "play"}))
    golden = base / "properties" / "play" / "synthetic.metis"
    golden.parent.mkdir(parents=True)
    golden.write_text(
        "metis 0.43\n\nendpoint play.synthetic {\n  variant default { empty }\n}\n",
        encoding="utf-8",
    )
    return workspace, legacy, base


def _sealed(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path]:
    workspace, legacy, base = _fixture_workspace(tmp_path)
    fixture = f5.seal_f5_fixture(
        fixture_id="f5/public-synthetic/basic-endpoint",
        endpoint_id="endpoint",
        expected_endpoint="play.synthetic",
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        golden_path="properties/play/synthetic.metis",
    )
    return fixture, workspace, legacy, base


def _completed(
    stdout: str, *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["synthetic"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _green_stdout() -> str:
    return "\n".join(
        [
            "- `endpoints/endpoint` — IR-PARITY OK (synthetic)",
            "- `check` — ricompilati senza errori: 1/1 · parity golden: 1 ok / 0 diverge · "
            "NON_PROMOTE shape: 0 match / 0 diverge",
        ]
    )


def _stub_runtime(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = workspace / "metis-pin"
    node = workspace / "node"
    cli = root / "tooling/src/migrate/cli.ts"
    cli.parent.mkdir(parents=True)
    cli.write_text("synthetic")
    node.write_text("synthetic")
    monkeypatch.setattr(
        f5,
        "_pinned_execution_identity",
        lambda _: (root, node, f5._registered_execution_identity()),
    )
    monkeypatch.setattr(f5, "_git_full_status", lambda _: "")
    return root, node


def _write_green_outputs(command: list[str], base: Path, stdout: str) -> None:
    output = Path(command[command.index("--out") + 1])
    migrated = output / "properties/play/synthetic.metis"
    migrated.parent.mkdir(parents=True, exist_ok=True)
    migrated.write_bytes((base / "properties/play/synthetic.metis").read_bytes())
    (output / "migrate-report.md").write_text(stdout, encoding="utf-8")


def test_fixture_is_schema_valid_and_binds_public_synthetic_inputs(tmp_path: Path) -> None:
    fixture, _, _, _ = _sealed(tmp_path)
    schema = json.loads((ROOT / "schemas/f5-migration-fixture.schema.json").read_text())

    assert list(Draft202012Validator(schema).iter_errors(fixture)) == []
    assert f5.validate_f5_fixture(fixture) == fixture
    assert fixture["toolchain"] == {
        "revision": f5.PINNED_METIS_REVISION,
        "tree": f5.PINNED_METIS_TREE,
        "language_version": "0.43",
        "migrator_path": "tooling/src/migrate/cli.ts",
        "migrator_sha256": "sha256:" + f5.PINNED_MIGRATOR_SHA256,
        "migration_check_sha256": "sha256:" + f5.PINNED_MIGRATION_CHECK_SHA256,
    }


def test_fixture_hash_and_non_043_golden_fail_closed(tmp_path: Path) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    changed = deepcopy(fixture)
    changed["golden"]["expected_endpoint"] = "play.other"
    with pytest.raises(F5FixtureError, match="hash|path"):
        f5.validate_f5_fixture(changed)

    (base / "properties/play/synthetic.metis").write_text(
        "metis 0.42\nendpoint play.synthetic {}\n"
    )
    with pytest.raises(F5FixtureError, match="0.43"):
        f5.seal_f5_fixture(
            fixture_id="f5/public-synthetic/not-current",
            endpoint_id="endpoint",
            expected_endpoint="play.synthetic",
            workspace_root=workspace,
            legacy_root=legacy,
            base_root=base,
            golden_path="properties/play/synthetic.metis",
        )

    (base / "properties/play/synthetic.metis").write_text("metis 0.43\nendpoint play.other {}\n")
    with pytest.raises(F5FixtureError, match="exactly the expected endpoint"):
        f5.seal_f5_fixture(
            fixture_id="f5/public-synthetic/wrong-golden-endpoint",
            endpoint_id="endpoint",
            expected_endpoint="play.synthetic",
            workspace_root=workspace,
            legacy_root=legacy,
            base_root=base,
            golden_path="properties/play/synthetic.metis",
        )


def test_runner_uses_only_explicit_synthetic_paths_and_accepts_all_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, node = _stub_runtime(workspace, monkeypatch)
    seen: dict[str, object] = {}

    def run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        _write_green_outputs(command, base, _green_stdout())
        return _completed(_green_stdout())

    monkeypatch.setattr(f5.subprocess, "run", run)
    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )

    command = seen["command"]
    assert command[0] == str(node.resolve())
    assert command[command.index("--legacy") + 1] == str(legacy.resolve())
    assert command[command.index("--base") + 1] == str(base.resolve())
    assert "--out" in command and "--check" in command
    assert not any("Developer/ARES/tenants" in item for item in command)
    assert seen["kwargs"]["env"]["PATH"] == str(node.resolve().parent)
    assert seen["kwargs"]["env"]["NO_COLOR"] == "1"
    assert result["runner_checks_passed"] is True
    assert result["evidence_class"] == "local_runner_observation"
    assert result["promotion_eligible"] is False
    assert result["authority_gap"] == "protected_execution_receipt_missing"
    assert result["failure_reasons"] == []
    assert (
        f5.validate_f5_migration_result(result, fixture=fixture, workspace_root=workspace) == result
    )
    with pytest.raises(F5ResultError, match="requires its workspace"):
        f5.validate_f5_migration_result(result, fixture=fixture)


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        (
            "ricompilati senza errori: 1/1 · parity golden: 1 ok / 0 diverge",
            0,
            "missing_ir_parity_ok",
        ),
        (
            "IR-PARITY OK (synthetic)\n"
            "ricompilati senza errori: 1/1 · parity golden: 0 ok / 1 diverge",
            0,
            "parity_not_1_ok_0_diverge",
        ),
        (
            "IR-PARITY OK (synthetic)\n"
            "ricompilati senza errori: 1/1 · parity golden: 1 ok / 0 diverge\n"
            "NON_PROMOTE",
            0,
            "non_promote_present",
        ),
        (
            "IR-PARITY OK (synthetic)\n"
            "ricompilati senza errori: 0/1 · parity golden: 1 ok / 0 diverge",
            0,
            "migrated_not_1_of_1",
        ),
        (_green_stdout(), 1, "process_failed"),
    ],
)
def test_runner_fails_closed_on_any_missing_f5_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    returncode: int,
    expected: str,
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, _ = _stub_runtime(workspace, monkeypatch)
    monkeypatch.setattr(
        f5.subprocess, "run", lambda *args, **kwargs: _completed(stdout, returncode=returncode)
    )

    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )

    assert result["runner_checks_passed"] is False
    assert expected in result["failure_reasons"]


def test_source_hash_drift_stops_before_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    (legacy / "endpoints/endpoint.json").write_text("{}")
    monkeypatch.setattr(f5.subprocess, "run", lambda *args, **kwargs: pytest.fail("runner called"))

    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=workspace / "missing-metis",
        run_nonce=RUN_NONCE,
    )

    assert result["failure_reasons"] == ["source_hash_mismatch"]


def test_toolchain_identity_is_mandatory_before_process_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    monkeypatch.setattr(
        f5,
        "_pinned_execution_identity",
        lambda _: (_ for _ in ()).throw(f5.F5MigrationError("toolchain mismatch")),
    )
    monkeypatch.setattr(f5.subprocess, "run", lambda *args, **kwargs: pytest.fail("runner called"))

    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=workspace / "forged-metis",
        run_nonce=RUN_NONCE,
    )

    assert result["failure_reasons"] == ["toolchain_mismatch"]


def test_green_transcript_cannot_hide_migrated_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, _ = _stub_runtime(workspace, monkeypatch)

    def run(command, **kwargs):
        _write_green_outputs(command, base, _green_stdout())
        output = Path(command[command.index("--out") + 1])
        (output / "properties/play/synthetic.metis").write_text(
            "metis 0.43\nendpoint play.invented {}\n"
        )
        return _completed(_green_stdout())

    monkeypatch.setattr(f5.subprocess, "run", run)
    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )

    assert result["runner_checks_passed"] is False
    assert "migrated_source_mismatch" in result["failure_reasons"]


def test_rehashed_fixture_metadata_cannot_hide_wrong_golden_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    old_golden = base / "properties/play/synthetic.metis"
    new_golden = base / "properties/play/other.metis"
    new_golden.write_bytes(old_golden.read_bytes())
    old_golden.unlink()
    changed = deepcopy(fixture)
    changed["golden"]["path"] = "properties/play/other.metis"
    changed["golden"]["expected_endpoint"] = "play.other"
    changed["base_source"]["tree_sha256"] = f5._tree_sha256(
        base, frozenset({".metis", ".json", ".toml"})
    )
    body = {key: value for key, value in changed.items() if key != "fixture_sha256"}
    changed["fixture_sha256"] = f5._sha(body)
    assert f5.validate_f5_fixture(changed) == changed
    monkeypatch.setattr(f5.subprocess, "run", lambda *args, **kwargs: pytest.fail("runner called"))

    result = f5.run_f5_migration_fixture(
        fixture=changed,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=workspace / "unused-metis",
        run_nonce=RUN_NONCE,
    )

    assert result["failure_reasons"] == ["golden_endpoint_mismatch"]


def test_extra_directory_symlink_blocks_green_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, _ = _stub_runtime(workspace, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.txt").write_text("not part of the result")

    def run(command, **kwargs):
        _write_green_outputs(command, base, _green_stdout())
        output = Path(command[command.index("--out") + 1])
        (output / "unexpected-dir").symlink_to(outside, target_is_directory=True)
        return _completed(_green_stdout())

    monkeypatch.setattr(f5.subprocess, "run", run)
    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )

    assert result["runner_checks_passed"] is False
    assert "output_roster_mismatch" in result["failure_reasons"]


def test_same_run_nonce_fails_closed_without_overwriting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, _ = _stub_runtime(workspace, monkeypatch)
    output = workspace / "f5-output" / fixture["fixture_id"].replace("/", "_") / RUN_NONCE
    output.mkdir(parents=True)
    marker = output / "preexisting.txt"
    marker.write_text("preserve")
    monkeypatch.setattr(f5.subprocess, "run", lambda *args, **kwargs: pytest.fail("runner called"))

    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )

    assert result["failure_reasons"] == ["output_not_fresh"]
    assert marker.read_text() == "preserve"


def test_result_schema_hash_and_acceptance_invariants_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, workspace, legacy, base = _sealed(tmp_path)
    metis_root, _ = _stub_runtime(workspace, monkeypatch)

    def run(command, **kwargs):
        _write_green_outputs(command, base, _green_stdout())
        return _completed(_green_stdout())

    monkeypatch.setattr(f5.subprocess, "run", run)
    result = f5.run_f5_migration_fixture(
        fixture=fixture,
        workspace_root=workspace,
        legacy_root=legacy,
        base_root=base,
        metis_root=metis_root,
        run_nonce=RUN_NONCE,
    )
    schema = json.loads((ROOT / "schemas/f5-migration-result.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(result)) == []

    tampered = deepcopy(result)
    tampered["observed"]["non_promote_seen"] = True
    body = {key: value for key, value in tampered.items() if key != "result_sha256"}
    tampered["result_sha256"] = f5._sha(body)
    with pytest.raises(F5ResultError, match="required migration gate"):
        f5.validate_f5_migration_result(tampered, fixture=fixture, workspace_root=workspace)

    forged_authority = deepcopy(result)
    forged_authority["promotion_eligible"] = True
    body = {key: value for key, value in forged_authority.items() if key != "result_sha256"}
    forged_authority["result_sha256"] = f5._sha(body)
    with pytest.raises(F5ResultError, match="schema|promotional authority"):
        f5.validate_f5_migration_result(forged_authority, fixture=fixture, workspace_root=workspace)
