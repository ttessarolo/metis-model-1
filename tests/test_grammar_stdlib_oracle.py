from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1 import grammar_stdlib_oracle as oracle
from metis_model1 import oracles


def _identity() -> dict[str, Any]:
    return {
        "revision": "a" * 40,
        "tree": "b" * 40,
        "runtime": {
            "node_version": "v22.22.3",
            "node_sha256": "sha256:" + "c" * 64,
            "package_sha256": "sha256:" + "d" * 64,
            "lock_sha256": "sha256:" + "e" * 64,
            "node_modules_sha256": "sha256:" + "f" * 64,
        },
    }


def _result(identity: dict[str, Any]) -> dict[str, Any]:
    inventory: dict[str, Any] = {"$type": "Model", "elements": []}
    runtime = {
        "node": identity["runtime"]["node_version"],
        "node_path": oracles.NODE_RUNTIME_IDENTITY,
        "loader_path": (
            f"snapshot://{identity['revision']}/{identity['tree']}"
            "/.metis-oracle/native_ts_loader.mjs"
        ),
        "loader_sha256": "sha256:" + oracles.PINNED_LOADER_SHA256,
        "loader_flags": list(oracles.LOADER_FLAGS),
        "runner_path": (
            f"snapshot://{identity['revision']}/{identity['tree']}/.metis-oracle/runner.ts"
        ),
        "snapshot_revision": identity["revision"],
        "snapshot_tree": identity["tree"],
        "tooling_package_sha256": identity["runtime"]["package_sha256"],
        "tooling_lock_sha256": identity["runtime"]["lock_sha256"],
        "node_modules_sha256": identity["runtime"]["node_modules_sha256"],
        "node_binary_sha256": identity["runtime"]["node_sha256"],
        "sandbox_exec_path": oracles.SANDBOX_EXEC_IDENTITY,
        "oracle_policy_version": oracles.SANDBOX_POLICY_VERSION,
        "oracle_policy_sha256": "sha256:" + oracles.SANDBOX_POLICY_SHA256,
        "execution_policy_sha256": "sha256:" + oracles.SANDBOX_POLICY_SHA256,
    }
    return {
        "schema_version": 1,
        "status": "ok",
        "endpoint": {"name": None, "count": 0},
        "diagnostics": {"parser": [], "link": [], "validation": [], "all": []},
        "ast": {"inventory": inventory, "signature": oracle._sha(inventory)},
        "ir": {"value": None, "signature": None},
        "toolchain": {
            "revision": identity["revision"],
            "tree": identity["tree"],
            "language_version": oracle.LANGUAGE_VERSION,
        },
        "runtime": runtime,
        "failure": None,
    }


def _session_base(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": identity["revision"],
        "tree": identity["tree"],
        "runtime": {
            "node_version": identity["runtime"]["node_version"],
            "node_sha256": identity["runtime"]["node_sha256"],
            "node_modules_sha256": identity["runtime"]["node_modules_sha256"],
        },
        "evidence": [
            {"id": "tooling_package", "sha256": identity["runtime"]["package_sha256"]},
            {"id": "tooling_lock", "sha256": identity["runtime"]["lock_sha256"]},
        ],
    }


def _fake_session_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, int], Path]:
    identity = _identity()
    counts = {"pin": 0, "snapshot": 0, "install": 0, "run": 0}
    root = tmp_path / "snapshot"
    tooling = root / "tooling"
    modules = tooling / "node_modules"
    modules.mkdir(parents=True)
    (tooling / "compiler.ts").write_text("export {};\n", encoding="utf-8")
    node = root / "node"
    node.write_text("node", encoding="utf-8")
    runner = root / "runner.ts"
    loader = root / "loader.mjs"
    runner.write_text("runner", encoding="utf-8")
    loader.write_text("loader", encoding="utf-8")

    def validate(*, metis_root: Path) -> dict[str, Any]:
        del metis_root
        counts["pin"] += 1
        return {"pin": "validated"}

    @contextmanager
    def snapshot(_metis_root: Path, _node_path: Path) -> Any:
        counts["snapshot"] += 1
        yield SimpleNamespace(root=root, tooling=tooling, node=node, policy="(version 1)")

    def install(_snapshot: Any, _identity_value: Any) -> tuple[Path, Path]:
        counts["install"] += 1
        return runner, loader

    def node_modules(_root: Path) -> str:
        return "e" * 64 if (_root / "tamper").exists() else "f" * 64

    def git(_root: Path, *arguments: str, text: bool = True) -> str | bytes:
        del text
        if arguments == ("status", "--porcelain=v1", "--untracked-files=no"):
            return ""
        if arguments == ("rev-parse", "HEAD"):
            return identity["revision"]
        if arguments == ("rev-parse", "HEAD^{tree}"):
            return identity["tree"]
        raise AssertionError(arguments)

    def run(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        request = json.loads(kwargs["input"].decode("utf-8"))
        assert request["source"].startswith("metis 0.43")
        counts["run"] += 1
        return SimpleNamespace(
            stdout=oracle._canonical(_result(identity)), stderr=b"", returncode=0
        )

    monkeypatch.setattr(oracle, "validate_grammar_stdlib_pin", validate)
    monkeypatch.setattr(
        oracle.catalog_pin,
        "load_catalog_maintenance_pin",
        lambda: _session_base(identity),
    )
    monkeypatch.setattr(oracle.refresh, "_pinned_snapshot", snapshot)
    monkeypatch.setattr(oracle, "_install_runner", install)
    monkeypatch.setattr(oracle.catalog_pin, "_node_modules_sha256", node_modules)
    monkeypatch.setattr(oracle.catalog_pin, "_run_git", git)
    monkeypatch.setattr(oracle.subprocess, "run", run)
    return counts, tooling


def test_session_reuses_one_validated_snapshot_and_redacts_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts, _tooling = _fake_session_runtime(tmp_path, monkeypatch)
    secret = "metis 0.43\n// caller-only fixture text\n"

    with oracle.grammar_stdlib_oracle_session(
        metis_root=tmp_path / "metis", node_path=tmp_path / "node"
    ) as session:
        first = session.run(source=secret, filename="first.metis")
        second = session.run(source="metis 0.43\n", filename="second.metis")

    assert counts == {"pin": 1, "snapshot": 1, "install": 1, "run": 2}
    assert first["evidence"]["request_sha256"] != second["evidence"]["request_sha256"]
    assert secret not in json.dumps(first, ensure_ascii=False)
    assert first["evidence"]["archive_snapshot"] is True
    assert first["evidence"]["network_denied"] is True
    assert first["evidence"]["writes_denied"] is True


def test_session_fails_closed_when_archived_tooling_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _counts, tooling = _fake_session_runtime(tmp_path, monkeypatch)

    with (
        pytest.raises(oracle.GrammarStdlibOracleError, match="modified isolated tooling"),
        oracle.grammar_stdlib_oracle_session(
            metis_root=tmp_path / "metis", node_path=tmp_path / "node"
        ),
    ):
        (tooling / "compiler.ts").write_text("tampered\n", encoding="utf-8")


def test_session_fails_closed_when_archived_node_modules_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _counts, tooling = _fake_session_runtime(tmp_path, monkeypatch)

    with (
        pytest.raises(
            oracle.GrammarStdlibOracleError, match="modified the isolated tooling runtime"
        ),
        oracle.grammar_stdlib_oracle_session(
            metis_root=tmp_path / "metis", node_path=tmp_path / "node"
        ),
    ):
        (tooling / "node_modules" / "tamper").write_text("tampered\n", encoding="utf-8")


def test_session_fails_closed_when_external_checkout_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _counts, _tooling = _fake_session_runtime(tmp_path, monkeypatch)
    observed = iter(
        [
            ("", "a" * 40, "b" * 40),
            ("", "c" * 40, "b" * 40),
        ]
    )
    monkeypatch.setattr(oracle, "_external_checkout_identity", lambda _root: next(observed))

    with (
        pytest.raises(oracle.GrammarStdlibOracleError, match="changed the external Metis checkout"),
        oracle.grammar_stdlib_oracle_session(
            metis_root=tmp_path / "metis", node_path=tmp_path / "node"
        ),
    ):
        pass


def test_result_validator_requires_complete_canonical_runtime_evidence() -> None:
    identity = _identity()
    result = _result(identity)

    assert oracle._validated_result(result, identity=identity, mode="source") == result

    result["runtime"].pop("node_path")
    with pytest.raises(oracle.GrammarStdlibOracleError, match="runtime identity drift"):
        oracle._validated_result(result, identity=identity, mode="source")


def test_result_validator_rejects_forged_ast_signature() -> None:
    identity = _identity()
    result = _result(identity)
    result["ast"]["signature"] = "sha256:" + "0" * 64

    with pytest.raises(oracle.GrammarStdlibOracleError, match="AST signature"):
        oracle._validated_result(result, identity=identity, mode="source")


def test_result_validator_rejects_a_different_selected_endpoint() -> None:
    identity = _identity()
    result = _result(identity)
    result["endpoint"] = {"name": "gsl_d18.other", "count": 1}
    result["ir"] = {"value": {"node": "Endpoint"}, "signature": None}
    result["ir"]["signature"] = oracle._sha(result["ir"]["value"])

    with pytest.raises(oracle.GrammarStdlibOracleError, match="unique IR"):
        oracle._validated_result(
            result,
            identity=identity,
            mode="endpoint",
            requested_endpoint="gsl_d18.expected",
        )


def test_public_api_rejects_endpoint_and_workspace_boundary_violations() -> None:
    arguments = {
        "metis_root": Path("/does-not-matter"),
        "node_path": Path("/does-not-matter"),
        "source": "metis 0.43\n",
        "filename": "candidate.metis",
    }

    with pytest.raises(oracle.GrammarStdlibOracleError, match="null endpoint"):
        oracle.run_grammar_stdlib_oracle(
            **arguments, execution_mode="source", endpoint="not-permitted"
        )
    with pytest.raises(oracle.GrammarStdlibOracleError, match="duplicates the candidate"):
        oracle.run_grammar_stdlib_oracle(
            **arguments,
            workspace_sources={"candidate.metis": "metis 0.43\n"},
        )


def test_overlay_uses_only_declared_git_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = "a" * 40
    tree = "b" * 40
    comparison_revision = "c" * 40
    comparison_tree = "d" * 40
    paths = dict(oracle._OVERLAY_PATHS)
    ordered = list(paths)
    blobs = {f"{index:x}" * 40: name.encode("utf-8") for index, name in enumerate(ordered, start=1)}
    evidence = [
        {
            "id": name,
            "path": paths[name],
            "blob_oid": oid,
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        for name, (oid, blob) in zip(ordered, blobs.items(), strict=True)
    ]
    by_id = {item["id"]: item for item in evidence}
    overlay = {
        "schema_version": 1,
        "pin_id": "grammar-stdlib/2026-08-25-v1",
        "repository": "ares-matioska/metis",
        "revision": revision,
        "tree": tree,
        "language_version": "0.43",
        "grammar": dict(by_id["grammar"]),
        "stdlib": dict(by_id["stdlib"]),
        "version_evidence": dict(by_id["version"]),
        "comparison": {
            "revision": comparison_revision,
            "tree": comparison_tree,
            "same_evidence_blobs": True,
        },
        "policy": {
            "git_objects_only": True,
            "worktree_payloads_excluded": True,
            "untracked_worktree_excluded": True,
            "credentials_and_env_excluded": True,
            "no_model_execution": True,
            "no_training_authority": True,
            "no_external_writes": True,
        },
        "nonclaims": [
            "no_tenant_payload",
            "no_model_output",
            "no_training_authority",
            "no_accuracy_claim",
            "no_runtime_parity_claim",
            "nonpromotable",
        ],
        "evidence": evidence,
    }
    overlay_path = tmp_path / "grammar-stdlib-pin-v1.json"
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

    def git(_root: Path, *arguments: str, text: bool = True) -> str | bytes:
        if arguments[0] == "ls-tree":
            path = arguments[-1]
            item = next(row for row in evidence if row["path"] == path)
            return f"100644 blob {item['blob_oid']}\t{path}\n"
        if arguments[:2] == ("cat-file", "blob"):
            return blobs[arguments[2]]
        if arguments == ("rev-parse", f"{comparison_revision}^{{tree}}"):
            return comparison_tree
        raise AssertionError(arguments)

    monkeypatch.setattr(oracle, "OVERLAY_PATH", overlay_path)
    monkeypatch.setattr(oracle.catalog_pin, "_run_git", git)
    result = oracle._overlay(tmp_path, {"revision": revision, "tree": tree})

    assert result is not None
    assert [row["id"] for row in result["evidence"]] == sorted(ordered)
