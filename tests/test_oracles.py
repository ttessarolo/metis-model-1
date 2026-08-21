from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.oracles as oracle_module
from metis_model1.oracles import (
    ARTIFACT_ROOT,
    OracleError,
    run_oracle,
    verify_oracle_envelope,
)

METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
RUNNER = Path(__file__).parents[1] / "runtime/metis_oracle/runner.ts"
PINNED_NODE = oracle_module._resolve_pinned_node()[0]
VALID = 'metis 0.43\nendpoint play.test as "test" {\n  variant v { empty }\n}\n'


@pytest.fixture
def artifact_tmp() -> Iterator[Path]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="oracle-test-", dir=ARTIFACT_ROOT))
    try:
        yield path
    finally:
        shutil.rmtree(path)


def execute(output_dir: Path, source: str = VALID, **kwargs: object) -> dict:
    return run_oracle(
        source,
        metis_root=METIS_ROOT,
        runner_path=RUNNER,
        output_path=output_dir / "oracle.json",
        **kwargs,
    )


def write_unqualified_node(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nprintf 'v0.0.0\\n'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_valid_source_has_structural_evidence_and_schema(artifact_tmp: Path) -> None:
    envelope = execute(artifact_tmp)
    assert envelope["result"]["status"] == "ok"
    assert envelope["result"]["diagnostics"] == {
        "all": [],
        "link": [],
        "parser": [],
        "validation": [],
    }
    assert envelope["result"]["ir"]["signature"].startswith("sha256:")
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/oracle-result.schema.json").read_text()
    )
    errors = list(Draft202012Validator(schema).iter_errors(envelope))
    assert errors == []


def test_repeat_is_byte_deterministic(artifact_tmp: Path) -> None:
    first = execute(artifact_tmp / "one")
    second = execute(artifact_tmp / "two")
    assert first == second
    assert (artifact_tmp / "one/oracle.json").read_bytes() == (
        artifact_tmp / "two/oracle.json"
    ).read_bytes()


def test_syntax_error_is_fail_closed(artifact_tmp: Path) -> None:
    result = execute(artifact_tmp, 'metis 0.43\nendpoint play.test as "test" { variant v {\n')
    assert result["result"]["status"] == "invalid"
    assert result["result"]["failure"]["kind"] == "parse"
    assert result["result"]["diagnostics"]["parser"]


def test_unknown_reference_is_link_error(artifact_tmp: Path) -> None:
    source = (
        'metis 0.43\nendpoint play.test as "test" {'
        ' take 1 from @video { include where @missing is "x" } }\n'
    )
    result = execute(artifact_tmp, source)
    assert result["result"]["status"] == "invalid"
    assert result["result"]["failure"]["kind"] == "link"
    assert result["result"]["diagnostics"]["link"]


def test_ambiguous_endpoint_is_rejected(artifact_tmp: Path) -> None:
    source = (
        "metis 0.43\n"
        'endpoint play.a as "a" { variant v { empty } }\n'
        'endpoint play.b as "b" { variant v { empty } }\n'
    )
    result = execute(artifact_tmp, source)
    assert result["result"]["failure"]["kind"] == "endpoint_ambiguous"
    assert result["result"]["endpoint"]["count"] == 2


def test_source_mode_validates_a_non_endpoint_document_without_compiling(
    artifact_tmp: Path,
) -> None:
    source = "metis 0.43\ncatalog video { fields { title keyword } }\n"
    envelope = execute(artifact_tmp, source, execution_mode="source")
    result = envelope["result"]
    assert result["status"] == "ok"
    assert result["endpoint"] == {"count": 0, "name": None}
    assert result["ast"]["signature"].startswith("sha256:")
    assert result["ir"] == {"signature": None, "value": None}
    request = oracle_module.build_oracle_request(source, execution_mode="source")
    assert verify_oracle_envelope(envelope, request=request) == envelope
    with pytest.raises(OracleError, match="inconsistent ok"):
        verify_oracle_envelope(envelope)


def test_source_mode_contract_rejects_endpoint_selection() -> None:
    with pytest.raises(OracleError, match="requires a null endpoint"):
        oracle_module.build_oracle_request(
            VALID,
            execution_mode="source",
            endpoint="play.test",
        )
    with pytest.raises(OracleError, match="execution_mode"):
        oracle_module.build_oracle_request(VALID, execution_mode="forged")


def test_tampered_revision_override_is_forbidden(artifact_tmp: Path) -> None:
    with pytest.raises(OracleError, match="overriding"):
        execute(artifact_tmp, expected_revision="0" * 40)


def test_output_inside_metis_or_non_artifact_is_rejected(artifact_tmp: Path) -> None:
    with pytest.raises(OracleError, match="inside the Metis checkout"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=RUNNER,
            output_path=METIS_ROOT / "generated/oracle.json",
        )
    with pytest.raises(OracleError, match="artifacts directory"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=RUNNER,
            output_path=artifact_tmp.parent.parent / "outside.json",
        )


def test_symlink_output_parent_is_rejected(artifact_tmp: Path) -> None:
    outside = artifact_tmp / "outside"
    outside.mkdir()
    link = artifact_tmp / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OracleError, match="contains a symlink"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=RUNNER,
            output_path=link / "oracle.json",
        )
    with pytest.raises(OracleError, match="end in .json"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=RUNNER,
            output_path=artifact_tmp / "oracle.txt",
        )


def test_runner_inside_metis_is_rejected(artifact_tmp: Path) -> None:
    with pytest.raises(OracleError, match="runner_path may not be inside"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=METIS_ROOT / "tooling/test/headless.ts",
            output_path=artifact_tmp / "oracle.json",
        )


def test_forged_external_runner_is_rejected(artifact_tmp: Path) -> None:
    forged = artifact_tmp / "forged.ts"
    forged.write_text("process.stdout.write('{}')\n", encoding="utf-8")
    with pytest.raises(OracleError, match="pinned Model1 oracle runner"):
        run_oracle(
            VALID,
            metis_root=METIS_ROOT,
            runner_path=forged,
            output_path=artifact_tmp / "oracle.json",
        )


def test_unqualified_node_runtime_is_rejected(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = artifact_tmp / "bad-node-bin"
    write_unqualified_node(bad / "node")
    monkeypatch.delenv(oracle_module.NODE_RUNTIME_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bad}:/usr/bin:/bin")
    with pytest.raises(OracleError, match="node runtime mismatch"):
        execute(artifact_tmp)


def test_source_node_is_never_executed_during_candidate_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("source Node candidate was executed before snapshot isolation")

    monkeypatch.setattr(oracle_module.subprocess, "run", forbidden)
    resolved, digest = oracle_module._validate_node_binary(PINNED_NODE)
    assert resolved == PINNED_NODE.resolve()
    assert digest == oracle_module.PINNED_NODE_BINARY_SHA256


def test_pinned_node_is_found_after_an_unqualified_path_entry(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = artifact_tmp / "bad-node-bin"
    good = artifact_tmp / "good-node-bin"
    good.mkdir()
    write_unqualified_node(bad / "node")
    (good / "node").symlink_to(PINNED_NODE)
    monkeypatch.delenv(oracle_module.NODE_RUNTIME_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bad}:{good}:/usr/bin:/bin")
    envelope = execute(artifact_tmp / "result")
    assert envelope["result"]["status"] == "ok"


def test_unreadable_path_candidate_does_not_mask_pinned_node(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = artifact_tmp / "unreadable-node-bin"
    good = artifact_tmp / "good-node-bin"
    unreadable = write_unqualified_node(bad / "node")
    unreadable.chmod(0o111)
    good.mkdir()
    (good / "node").symlink_to(PINNED_NODE)
    monkeypatch.delenv(oracle_module.NODE_RUNTIME_ENV, raising=False)
    monkeypatch.setenv("PATH", f"{bad}:{good}:/usr/bin:/bin")
    envelope = execute(artifact_tmp / "result")
    assert envelope["result"]["status"] == "ok"


def test_explicit_pinned_node_overrides_hostile_path(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = artifact_tmp / "bad-node-bin"
    write_unqualified_node(bad / "node")
    monkeypatch.setenv(oracle_module.NODE_RUNTIME_ENV, str(PINNED_NODE))
    monkeypatch.setenv("PATH", f"{bad}:/usr/bin:/bin")
    envelope = execute(artifact_tmp)
    assert envelope["result"]["status"] == "ok"


def test_explicit_unqualified_node_is_rejected(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = write_unqualified_node(artifact_tmp / "unqualified-node")
    monkeypatch.setenv(oracle_module.NODE_RUNTIME_ENV, str(wrong))
    with pytest.raises(OracleError, match="binary hash"):
        execute(artifact_tmp)


def test_multi_file_workspace_resolves_candidate_dependency(artifact_tmp: Path) -> None:
    candidate = (
        'metis 0.43\nendpoint play.test as "test" {\n'
        '  variant v { take 1 from @video { include where @title is "x" } }\n}\n'
    )
    dependency = "metis 0.43\ncatalog video { fields { title keyword } }\n"
    envelope = execute(
        artifact_tmp,
        candidate,
        workspace_sources={"catalogs/video.metis": dependency},
    )
    assert envelope["result"]["status"] == "ok"
    assert envelope["result"]["diagnostics"]["link"] == []


def test_isolated_node_modules_mutation_between_validation_and_execution_is_rejected(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = oracle_module._build_isolated_snapshot

    def attacked(*args: object, **kwargs: object) -> object:
        holder, snapshot, modules, snapshot_runner, snapshot_node = original(*args, **kwargs)
        target = modules / "langium/package.json"
        target.write_text("{}\n", encoding="utf-8")
        return holder, snapshot, modules, snapshot_runner, snapshot_node

    monkeypatch.setattr(oracle_module, "_build_isolated_snapshot", attacked)
    with pytest.raises(OracleError, match="changed before execution"):
        execute(artifact_tmp)


def test_forged_runtime_path_is_rejected_even_with_rehashed_envelope(artifact_tmp: Path) -> None:
    envelope = execute(artifact_tmp)
    envelope["result"]["runtime"]["tsx_path"] = "snapshot://forged/tsx"
    envelope["evidence"]["runtime_identity"]["tsx_path"] = "snapshot://forged/tsx"
    envelope["evidence"]["runtime_sha256"] = oracle_module._sha(
        envelope["evidence"]["runtime_identity"]
    )
    envelope["evidence"].pop("envelope_sha256")
    envelope["evidence"]["envelope_sha256"] = oracle_module._sha(envelope)
    with pytest.raises(OracleError, match="runtime identity"):
        verify_oracle_envelope(envelope)


def test_runner_mutation_after_snapshot_build_is_rejected(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = oracle_module._build_isolated_snapshot

    def attacked(*args: object, **kwargs: object) -> object:
        holder, snapshot, modules, snapshot_runner, snapshot_node = original(*args, **kwargs)
        snapshot_runner.write_text("process.stdout.write('{}')\n", encoding="utf-8")
        return holder, snapshot, modules, snapshot_runner, snapshot_node

    monkeypatch.setattr(oracle_module, "_build_isolated_snapshot", attacked)
    with pytest.raises(OracleError, match="isolated runner changed before execution"):
        execute(artifact_tmp)


def test_sandbox_policy_denies_write_canary() -> None:
    oracle_module._assert_sandbox_policy()


def test_sandbox_policy_denies_network_without_external_targets() -> None:
    assert "(deny network*)" in oracle_module.SANDBOX_POLICY
    assert '"127.0.0.1", 0' in oracle_module.NETWORK_CANARY_PROGRAM
    assert "connect" in oracle_module.NETWORK_CANARY_PROGRAM
    assert "bind" in oracle_module.NETWORK_CANARY_PROGRAM
    assert "getaddrinfo" not in oracle_module.NETWORK_CANARY_PROGRAM
    assert "http" not in oracle_module.NETWORK_CANARY_PROGRAM.lower()
    oracle_module._assert_sandbox_policy()


def test_broadened_sandbox_policy_fails_network_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadened = "(version 1) (allow default) (deny file-write*)"
    monkeypatch.setattr(oracle_module, "SANDBOX_POLICY", broadened)
    monkeypatch.setattr(
        oracle_module,
        "SANDBOX_POLICY_SHA256",
        oracle_module.hashlib.sha256(broadened.encode()).hexdigest(),
    )
    with pytest.raises(OracleError, match="failed to deny network"):
        oracle_module._assert_sandbox_policy()


def test_hostile_node_options_are_not_inherited(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--require=/definitely/missing/preload.js")
    envelope = execute(artifact_tmp)
    assert envelope["result"]["status"] == "ok"
    assert envelope["evidence"]["runtime_identity"]["node_binary_sha256"] == (
        "sha256:" + oracle_module.PINNED_NODE_BINARY_SHA256
    )


def test_metis_checkout_status_is_unchanged_after_isolated_execution(artifact_tmp: Path) -> None:
    before = subprocess.run(
        ["git", "-C", str(METIS_ROOT), "status", "--porcelain=v1", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    execute(artifact_tmp)
    after = subprocess.run(
        ["git", "-C", str(METIS_ROOT), "status", "--porcelain=v1", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert after == before
