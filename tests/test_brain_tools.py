from __future__ import annotations

import json
import stat
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_tools as brain_tools_module
from metis_model1 import catalog_maintenance_pin as sandbox_support
from metis_model1.brain_context import ContextSnapshot, SnapshotFile, toolchain_binding_from_pin
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_semantic_retrieval import LoadedProjection
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import (
    BrainCompiler,
    PinnedCatalogProjectionLoader,
    PinnedMetisAuthority,
)


def _pin() -> dict[str, Any]:
    return {
        "base_model": "qwen/test",
        "catalog_pin_id": "brain/test",
        "catalog_pin_sha256": "sha256:" + "d" * 64,
        "revision": "a" * 40,
        "tree": "b" * 40,
        "language_version": "0.43",
        "node_modules_sha256": "sha256:" + "c" * 64,
        "overlay": None,
        "runner_sha256": brain_tools_module.RUNNER_SHA256,
    }


PIN = _pin()
BINDING = toolchain_binding_from_pin(PIN)
EXPECTED_IDENTITY = (PIN["revision"], PIN["tree"], "c" * 64)


def _file(path: str, content: bytes) -> SnapshotFile:
    return SnapshotFile(path=path, content=content, sha256=bytes_sha256(content))


def _snapshot(*, binding: str = BINDING, files: int = 1) -> ContextSnapshot:
    records = [_file("metis.toml", b"[tenant]\nid = 'tenant-one'\n")]
    records.extend(
        _file(
            f"source-{index}.metis",
            f"metis 0.43\ntenant t{index} {{}}\n".encode(),
        )
        for index in range(files)
    )
    return ContextSnapshot(
        tenant_alias="demo",
        tenant_id="tenant-one",
        root_device=1,
        root_inode=2,
        revision="sha256:" + "e" * 64,
        toolchain_binding=binding,
        files=tuple(records),
        total_bytes=sum(len(item.content) for item in records),
    )


def _lease(*, binding: str = BINDING, files: int = 1) -> OperationLease:
    snapshot = _snapshot(binding=binding, files=files)
    return OperationLease(
        session_id="s" * 43,
        client_id="visix",
        tenant_alias="demo",
        capabilities=frozenset({"compile"}),
        snapshot=snapshot,
        cancellation=threading.Event(),
    )


@pytest.fixture
def toolchain_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Inject the pinned boundary while retaining real temporary directories."""

    metis_root = tmp_path / "metis"
    node_path = tmp_path / "node"
    metis_root.mkdir()
    node_path.mkdir()
    observed: dict[str, Any] = {
        "metis_root": metis_root,
        "node_path": node_path,
        "isolations": [],
        "materializations": [],
        "sandbox_checks": [],
    }

    def pin_identity(root: Path, node: Path) -> tuple[dict[str, Any], tuple[str, str, str]]:
        observed["pin_calls"] = observed.get("pin_calls", 0) + 1
        observed["pin_args"] = (root, node)
        return dict(PIN), EXPECTED_IDENTITY

    monkeypatch.setattr(brain_tools_module, "_brain_pin_identity", pin_identity)
    monkeypatch.setattr(sandbox_support, "SANDBOX_EXEC", Path("/bin/sh"))

    def sandbox_check(root: Path, policy: str) -> None:
        observed["sandbox_checks"].append((root, policy))

    monkeypatch.setattr(sandbox_support, "_assert_sandbox_boundaries", sandbox_check)

    isolation_number = 0

    @contextmanager
    def isolated(**kwargs: Any):
        nonlocal isolation_number
        isolation_number += 1
        isolated_root = tmp_path / f"isolated-{isolation_number}"
        (isolated_root / "tooling").mkdir(parents=True)
        observed["isolations"].append(kwargs)
        yield isolated_root

    monkeypatch.setattr(brain_tools_module, "_isolated_metis_repository", isolated)

    original_materialize = brain_tools_module._materialize_snapshot

    def materialize(snapshot: ContextSnapshot, root: Path, **kwargs: Any) -> Path:
        destination = original_materialize(snapshot, root, **kwargs)
        observed["materializations"].append(
            {"snapshot": snapshot, "root": root, "kwargs": kwargs, "path": destination}
        )
        return destination

    monkeypatch.setattr(brain_tools_module, "_materialize_snapshot", materialize)

    def run_runner(**kwargs: Any) -> dict[str, Any]:
        observed["runner_calls"] = observed.get("runner_calls", 0) + 1
        observed["runner"] = kwargs
        return {
            "schema_version": 1,
            "operation": "compile",
            "status": "ok",
            "diagnostics": [],
            "endpoint": kwargs["request"].get("endpoint"),
            "endpoint_sha256": None,
            "runtime_context_sha256": "sha256:" + "f" * 64,
        }

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", run_runner)
    observed["compiler"] = BrainCompiler(metis_root=metis_root, node_path=node_path)
    observed["loader"] = PinnedCatalogProjectionLoader(metis_root=metis_root, node_path=node_path)
    return observed


def test_compiler_receipt_is_source_redacted_and_snapshot_bound(
    toolchain_harness: dict[str, Any],
) -> None:
    compiler = toolchain_harness["compiler"]
    lease = _lease()
    secret = "metis 0.43\n// caller-only secret\ntenant candidate {}\n"

    receipt = compiler.compile(
        lease=lease,
        source=secret,
        filename="candidate.metis",
        execution_mode="source",
        endpoint=None,
    )

    assert toolchain_harness["pin_args"] == (
        toolchain_harness["metis_root"],
        toolchain_harness["node_path"],
    )
    isolation = toolchain_harness["isolations"][0]
    assert isolation["metis_root"] == toolchain_harness["metis_root"]
    assert isolation["node_path"] == toolchain_harness["node_path"]
    assert isolation["expected_identity"] == EXPECTED_IDENTITY
    request = toolchain_harness["runner"]["request"]
    assert request["operation"] == "compile"
    assert request["endpoint"] is None
    assert secret not in json.dumps(receipt)
    assert receipt["candidate"] == {
        "filename": "candidate.metis",
        "execution_mode": "source",
        "endpoint": None,
        "source_sha256": canonical_sha256(secret),
        "context_revision": lease.snapshot.revision,
    }
    assert receipt["claims"] == {
        "archive_snapshot": True,
        "network_denied": True,
        "writes_denied": True,
        "tenant_modified": False,
        "semantic_correctness": False,
    }
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert compiler.execution_count == 1


def test_compiler_and_retriever_can_share_one_verified_authority(
    toolchain_harness: dict[str, Any],
) -> None:
    before = toolchain_harness["pin_calls"]
    authority = PinnedMetisAuthority(
        metis_root=toolchain_harness["metis_root"],
        node_path=toolchain_harness["node_path"],
    )
    compiler = BrainCompiler(
        metis_root=toolchain_harness["metis_root"],
        node_path=toolchain_harness["node_path"],
        authority=authority,
    )
    loader = PinnedCatalogProjectionLoader(
        metis_root=toolchain_harness["metis_root"],
        node_path=toolchain_harness["node_path"],
        authority=authority,
    )

    assert toolchain_harness["pin_calls"] == before + 1
    assert compiler.authority is authority
    assert loader.authority is authority
    compiler.close()
    loader.close()
    authority.close()


def test_authority_capsule_is_built_once_and_jobs_are_ephemeral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metis_root = tmp_path / "metis"
    modules = metis_root / "tooling/node_modules/package"
    modules.mkdir(parents=True)
    modules.joinpath("index.js").write_text("export {};", encoding="utf-8")
    node_path = tmp_path / "node"
    node_path.write_bytes(b"node")
    archive_calls = 0

    monkeypatch.setattr(
        brain_tools_module,
        "_brain_pin_identity",
        lambda _root, _node: (dict(PIN), EXPECTED_IDENTITY),
    )
    monkeypatch.setattr(
        brain_tools_module.brain_pin,
        "load_metis_brain_toolchain_pin",
        lambda: {**PIN, "runtime": {}},
    )
    monkeypatch.setattr(brain_tools_module.brain_pin, "_verify_node", lambda *_args: b"node")
    monkeypatch.setattr(
        brain_tools_module.brain_pin,
        "_node_modules_sha256",
        lambda _path: EXPECTED_IDENTITY[2],
    )

    def archive(*_args: Any, **_kwargs: Any) -> bytes:
        nonlocal archive_calls
        archive_calls += 1
        return b"pinned-archive"

    monkeypatch.setattr(brain_tools_module.brain_pin, "_git", archive)
    monkeypatch.setattr(brain_tools_module, "_runner_bytes", lambda: b"runner")
    monkeypatch.setattr(sandbox_support, "SANDBOX_EXEC", Path("/bin/sh"))
    monkeypatch.setattr(
        sandbox_support,
        "_safe_extract_archive",
        lambda _archive, destination: destination.joinpath("tooling").mkdir(),
    )

    authority = PinnedMetisAuthority(metis_root=metis_root, node_path=node_path)
    with authority.job() as first:
        first_authority = first.authority_root
        first_job = first.job_root
        assert first_job.is_dir()
        sealed_module = first_authority / "tooling/node_modules/package/index.js"
        assert sealed_module.lstat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert not first_job.exists()
    with authority.job() as second:
        assert second.authority_root == first_authority
        assert second.job_root != first_job
        assert second.job_root.is_dir()
    assert archive_calls == 1

    authority.close()
    assert not first_authority.exists()


def test_candidate_replaces_same_workspace_filename(
    toolchain_harness: dict[str, Any],
) -> None:
    compiler = toolchain_harness["compiler"]
    replacement = b"metis 0.43\ntenant replacement {}\n"

    compiler.compile(
        lease=_lease(),
        source=replacement.decode(),
        filename="source-0.metis",
        execution_mode="source",
        endpoint=None,
    )

    materialized = toolchain_harness["materializations"][0]
    candidate_path = materialized["path"] / "source-0.metis"
    assert candidate_path.read_bytes() == replacement
    assert materialized["path"].joinpath("metis.toml").is_file()


def test_stale_toolchain_is_rejected_before_materialization(
    toolchain_harness: dict[str, Any],
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].compile(
            lease=_lease(binding="sha256:" + "0" * 64),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )

    assert raised.value.code == "STALE_CONTEXT"
    assert not toolchain_harness["materializations"]
    assert "runner_calls" not in toolchain_harness


def test_cancelled_session_is_rejected_without_runner(
    toolchain_harness: dict[str, Any],
) -> None:
    lease = _lease()
    lease.cancellation.set()

    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].compile(
            lease=lease,
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )

    assert raised.value.code == "SESSION_REVOKED"
    assert "runner_calls" not in toolchain_harness


def test_compiler_capacity_is_busy_and_released(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_runner(**kwargs: Any) -> dict[str, Any]:
        toolchain_harness["runner_calls"] = toolchain_harness.get("runner_calls", 0) + 1
        started.set()
        assert release.wait(2)
        return {
            "schema_version": 1,
            "operation": "compile",
            "status": "ok",
            "diagnostics": [],
            "endpoint": None,
            "endpoint_sha256": None,
            "runtime_context_sha256": "sha256:" + "f" * 64,
        }

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", blocking_runner)
    compiler = BrainCompiler(
        metis_root=toolchain_harness["metis_root"],
        node_path=toolchain_harness["node_path"],
        max_concurrency=1,
    )
    request = {
        "lease": _lease(),
        "source": "metis 0.43\ntenant candidate {}\n",
        "filename": "candidate.metis",
        "execution_mode": "source",
        "endpoint": None,
    }
    errors: list[BaseException] = []

    def run_first() -> None:
        try:
            compiler.compile(**request)
        except BaseException as error:  # pragma: no cover - assertion reports worker errors
            errors.append(error)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert started.wait(2)
    with pytest.raises(BrainError) as raised:
        compiler.compile(**request)
    assert raised.value.code == "COMPILER_BUSY"
    release.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert not errors

    # The first lease was released even though the runner was held in-flight.
    compiler.compile(**request)
    assert compiler.execution_count == 2


@pytest.mark.parametrize(
    "error",
    [
        brain_tools_module._BrainIsolationError("secret internal detail"),
        subprocess.TimeoutExpired(["pinned-compiler"], 180),
    ],
)
def test_internal_and_timeout_failures_are_normalized(
    toolchain_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    def fail_runner(**_kwargs: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", fail_runner)
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].compile(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )

    assert raised.value.code == "COMPILER_FAILED"
    assert raised.value.status == 503
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("filename", "mode", "endpoint"),
    [
        ("../escape.metis", "source", None),
        ("a//b.metis", "source", None),
        ("a/./b.metis", "source", None),
        ("candidate.metis", "unknown", None),
        ("candidate.metis", "source", "endpoint.name"),
        ("candidate.metis", "endpoint", None),
    ],
)
def test_compile_request_filename_and_mode_are_strict(
    toolchain_harness: dict[str, Any],
    filename: str,
    mode: str,
    endpoint: str | None,
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].compile(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename=filename,
            execution_mode=mode,
            endpoint=endpoint,
        )

    assert raised.value.code == "INVALID_SCHEMA"
    assert "runner_calls" not in toolchain_harness


def test_endpoint_mode_passes_endpoint_to_runner(
    toolchain_harness: dict[str, Any],
) -> None:
    receipt = toolchain_harness["compiler"].compile(
        lease=_lease(),
        source="metis 0.43\ntenant candidate {}\n",
        filename="candidate.metis",
        execution_mode="endpoint",
        endpoint="catalog.search",
    )

    assert receipt["candidate"]["execution_mode"] == "endpoint"
    assert receipt["candidate"]["endpoint"] == "catalog.search"
    assert toolchain_harness["runner"]["request"]["endpoint"] == "catalog.search"


def _projection_response() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "semantic-catalog",
        "describe": {"catalogs": []},
        "values": [],
        "counts": {"catalogs": 1, "finite_fields": 0, "values": 0},
    }


def test_projection_loader_returns_shape_counts_and_snapshot_binding(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = {
        "schema": 2,
        "projection_contract": "test-contract",
        "tenant": "tenant-one",
        "catalogs": [],
    }
    receipt = {
        "counts": {
            "catalogs": 1,
            "fields": 0,
            "finite_fields_expected": 0,
            "values_responses": 0,
            "values": 0,
            "semantic_values": 0,
            "gaps": 0,
        }
    }

    def semantic_runner(**kwargs: Any) -> dict[str, Any]:
        toolchain_harness["semantic_runner"] = kwargs
        return _projection_response()

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", semantic_runner)
    monkeypatch.setattr(
        brain_tools_module,
        "build_catalog_semantic_projection",
        lambda describe, values: {"projection": projection, "receipt": receipt},
    )
    monkeypatch.setattr(brain_tools_module, "validate_catalog_projection_receipt", lambda _: [])

    snapshot = _snapshot()
    loaded = toolchain_harness["loader"](snapshot)

    assert isinstance(loaded, LoadedProjection)
    assert loaded.projection is projection
    assert loaded.snapshot_revision == snapshot.revision
    assert loaded.semantic_source_revision == snapshot.semantic_source_revision()
    assert toolchain_harness["semantic_runner"]["request"]["operation"] == "semantic-catalog"
    assert receipt["counts"]["values"] == 0


@pytest.mark.parametrize(
    "response",
    [
        {"schema_version": 1, "operation": "semantic-catalog", "describe": {}, "values": []},
        {
            **_projection_response(),
            "counts": {"catalogs": 2, "finite_fields": 0, "values": 0},
        },
    ],
)
def test_projection_loader_rejects_shape_or_count_drift(
    toolchain_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", lambda **_: response)
    monkeypatch.setattr(
        brain_tools_module,
        "build_catalog_semantic_projection",
        lambda *_args: {
            "projection": {"schema": 2, "projection_contract": "test", "tenant": "tenant-one"},
            "receipt": {
                "counts": {
                    "catalogs": 1,
                    "values_responses": 0,
                    "values": 0,
                }
            },
        },
    )
    monkeypatch.setattr(brain_tools_module, "validate_catalog_projection_receipt", lambda _: [])

    with pytest.raises(BrainError) as raised:
        toolchain_harness["loader"](_snapshot())
    assert raised.value.code == "RETRIEVAL_UNAVAILABLE"


def test_projection_loader_rejects_stale_snapshot_binding(
    toolchain_harness: dict[str, Any],
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["loader"](_snapshot(binding="sha256:" + "0" * 64))

    assert raised.value.code == "STALE_CONTEXT"
    assert "runner_calls" not in toolchain_harness


def test_runner_applies_sandbox_path_check_and_parses_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_root = tmp_path / "isolated"
    (isolated_root / "tooling").mkdir(parents=True)
    node_path = tmp_path / "node"
    node_path.mkdir()
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        brain_tools_module,
        "_sandbox_policy",
        lambda root, node, *extra: (
            observed.update({"policy_args": (root, node), "policy_extra": extra}) or "TEST-POLICY"
        ),
    )
    monkeypatch.setattr(
        sandbox_support,
        "_assert_sandbox_boundaries",
        lambda root, policy: observed.update({"sandbox_args": (root, policy)}),
    )
    monkeypatch.setattr(sandbox_support, "SANDBOX_EXEC", Path("/usr/bin/env"))
    monkeypatch.setattr(sandbox_support, "_probe_process_environment", lambda: {"PATH": "/bin"})

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed["command"] = command
        observed["run_kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b'{"ok":true}', b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    response = brain_tools_module._run_brain_runner(
        isolated_root=isolated_root,
        node_path=node_path,
        request={"operation": "compile"},
    )

    assert response == {"ok": True}
    assert observed["policy_args"] == (isolated_root, node_path)
    assert observed["policy_extra"] == ((),)
    assert observed["sandbox_args"] == (isolated_root, "TEST-POLICY")
    assert observed["command"][-3:] == [
        "--import",
        "tsx",
        str(isolated_root / "runtime/metis_brain/runner.mts"),
    ]
    assert observed["run_kwargs"]["cwd"] == isolated_root / "tooling"
    assert observed["run_kwargs"]["input"] == b'{"operation":"compile"}'


def test_runner_policy_allows_only_authority_and_current_job(tmp_path: Path) -> None:
    authority = (tmp_path / "authority").resolve()
    current_job = (tmp_path / "jobs/current").resolve()
    sibling_job = (tmp_path / "jobs/sibling").resolve()
    node = (tmp_path / "node").resolve()

    policy = brain_tools_module._sandbox_policy(authority, node, (current_job,))

    assert str(authority) in policy
    assert str(current_job) in policy
    assert str(node) in policy
    assert str(sibling_job) not in policy
