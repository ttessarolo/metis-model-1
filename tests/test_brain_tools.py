from __future__ import annotations

import errno
import hashlib
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
    CandidateCompileResult,
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
        "tooling_version": "0.23.97",
        "langium_version": "4.3.0",
        "metis_language_version": "0.43",
        "grammar_sha256": "sha256:" + "9" * 64,
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
        with pytest.raises(BrainError) as busy:
            authority.close()
        assert busy.value.code == "TOOLCHAIN_BUSY"
    assert not first_job.exists()
    with authority.job() as second:
        assert second.authority_root == first_authority
        assert second.job_root != first_job
        assert second.job_root.is_dir()
    assert archive_calls == 1

    temporary = authority._temporary
    assert temporary is not None

    class FlakyCleanup:
        def __init__(self) -> None:
            self.name = temporary.name
            self.remaining_failures = brain_tools_module.AUTHORITY_CLEANUP_ATTEMPTS
            self.calls = 0

        def cleanup(self) -> None:
            self.calls += 1
            if self.remaining_failures:
                self.remaining_failures -= 1
                raise OSError(errno.ENOTEMPTY, "Directory not empty", ".bin")
            temporary.cleanup()

    flaky = FlakyCleanup()
    authority._temporary = flaky  # type: ignore[assignment]
    with pytest.raises(BrainError) as failed:
        authority.close()
    assert failed.value.code == "TOOLCHAIN_CLEANUP_FAILED"
    assert first_authority.exists()
    with (
        pytest.raises(brain_tools_module._BrainIsolationError, match="closed"),
        authority.job(),
    ):
        pass

    flaky.remaining_failures = 1
    authority.close()
    assert flaky.calls == brain_tools_module.AUTHORITY_CLEANUP_ATTEMPTS + 2
    assert not first_authority.exists()
    authority.close()
    assert flaky.calls == brain_tools_module.AUTHORITY_CLEANUP_ATTEMPTS + 2


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


def _candidate_manifest() -> dict[str, Any]:
    null_hash = None
    digest = "sha256:" + "1" * 64
    endpoint_sha256 = "sha256:" + "2" * 64
    return {
        "schema_version": 1,
        "endpoint": "catalog.search",
        "endpoint_sha256": endpoint_sha256,
        "containers": [
            {
                "path": "endpoint",
                "kind": "endpoint",
                "name": "catalog.search",
                "activation_sha256": null_hash,
                "output_sha256": null_hash,
                "fallback_sha256": null_hash,
                "uses_sha256": null_hash,
                "semantics_sha256": digest,
                "presentation_sha256": digest,
            },
            {
                "path": "endpoint/inline",
                "kind": "block",
                "name": "catalog.search",
                "activation_sha256": null_hash,
                "output_sha256": null_hash,
                "fallback_sha256": null_hash,
                "uses_sha256": null_hash,
                "semantics_sha256": digest,
                "presentation_sha256": digest,
            },
        ],
        "fetches": [
            {
                "occurrence": 0,
                "stage_id": "inline.take.1",
                "container_path": "endpoint/inline",
                "source": {"kind": "catalog", "ref": "tenant.video"},
                "catalog": "tenant.video",
                "count": {"skip": 0, "take": 24},
                "activation_sha256": null_hash,
                "ordering_sha256": digest,
                "output_sha256": null_hash,
                "fallback_sha256": null_hash,
                "predicates": [],
                "semantics_sha256": digest,
            }
        ],
    }


def _candidate_compile_response(
    *, status: str = "ok", manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    selected = _candidate_manifest() if manifest is None else manifest
    if status == "invalid":
        return {
            "schema_version": 1,
            "operation": "compile-candidate",
            "status": "invalid",
            "diagnostics": [{"code": "BRAIN_MANIFEST_INVALID"}],
            "endpoint": None,
            "endpoint_sha256": None,
            "runtime_context_sha256": None,
            "manifest": None,
            "manifest_sha256": None,
        }
    return {
        "schema_version": 1,
        "operation": "compile-candidate",
        "status": "ok",
        "diagnostics": [],
        "endpoint": "catalog.search",
        "endpoint_sha256": selected["endpoint_sha256"],
        "runtime_context_sha256": "sha256:" + "3" * 64,
        "manifest": selected,
        "manifest_sha256": canonical_sha256(selected),
    }


def test_compile_candidate_compiles_once_and_keeps_manifest_out_of_public_receipt(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _candidate_compile_response()
    observed: dict[str, Any] = {}

    def runner(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return response

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", runner)
    result = toolchain_harness["compiler"].compile_candidate(
        lease=_lease(),
        source="metis 0.43\ntenant candidate {}\n",
        filename="candidate.metis",
        endpoint="catalog.search",
    )

    assert isinstance(result, CandidateCompileResult)
    assert result.manifest == response["manifest"]
    assert result.manifest_sha256 == response["manifest_sha256"]
    assert "manifest" not in json.dumps(result.receipt)
    assert result.receipt["compiler"]["operation"] == "compile"
    assert result.receipt["compiler"]["endpoint_sha256"] == response["endpoint_sha256"]
    assert observed["request"]["operation"] == "compile-candidate"
    assert toolchain_harness["compiler"].execution_count == 1


def test_compile_candidate_preserves_bounded_invalid_as_public_compile_receipt(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        brain_tools_module,
        "_run_brain_runner",
        lambda **_: _candidate_compile_response(status="invalid"),
    )
    result = toolchain_harness["compiler"].compile_candidate(
        lease=_lease(),
        source="metis 0.43\ntenant candidate {}\n",
        filename="candidate.metis",
        endpoint="catalog.search",
    )

    assert result.manifest is None
    assert result.manifest_sha256 is None
    assert result.receipt["status"] == "invalid"
    assert result.receipt["compiler"]["status"] == "invalid"


@pytest.mark.parametrize(
    "corruption",
    ["catalog", "stage", "hash", "container_semantics_missing", "container_semantics_invalid"],
)
def test_compile_candidate_rejects_untrusted_manifest_shapes(
    toolchain_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    manifest = _candidate_manifest()
    if corruption == "catalog":
        manifest["fetches"][0]["catalog"] = "tenant.other"
    elif corruption == "stage":
        manifest["fetches"].append(dict(manifest["fetches"][0], occurrence=1))
    elif corruption == "container_semantics_missing":
        del manifest["containers"][0]["semantics_sha256"]
    elif corruption == "container_semantics_invalid":
        manifest["containers"][0]["semantics_sha256"] = "not-a-hash"
    response = _candidate_compile_response(manifest=manifest)
    if corruption == "hash":
        response["manifest_sha256"] = "sha256:" + "f" * 64
    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", lambda **_: response)

    with pytest.raises(BrainError, match="invalid manifest") as raised:
        toolchain_harness["compiler"].compile_candidate(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            endpoint="catalog.search",
        )
    assert raised.value.code == "COMPILER_FAILED"


def test_compile_structure_uses_private_runner_and_returns_provenance_free_ir(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    structural_ir = {
        "irVersion": "0.6",
        "node": "Endpoint",
        "name": "catalog.search",
        "inline": {
            "name": "catalog.search",
            "node": "Block",
            "takes": [
                {
                    "count": {"skip": 0, "take": 24},
                    "node": "Fetch",
                    "source": {"kind": "catalog", "ref": "tenant.video"},
                }
            ],
        },
    }
    structural_json = json.dumps(
        structural_ir,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    )
    response = {
        "schema_version": 1,
        "operation": "compile-structure",
        "status": "ok",
        "diagnostics": [],
        "endpoint": "catalog.search",
        "structural_ir": structural_ir,
        "structural_sha256": "sha256:" + hashlib.sha256(structural_json.encode()).hexdigest(),
    }
    observed: dict[str, Any] = {}

    def runner(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return response

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", runner)
    result = toolchain_harness["compiler"].compile_structure(
        lease=_lease(),
        source="metis 0.43\ntenant candidate {}\n",
        filename="candidate.metis",
        endpoint="catalog.search",
    )

    assert result == response
    assert "provenance" not in json.dumps(result["structural_ir"])
    assert observed["request"] == {
        "schema_version": 1,
        "operation": "compile-structure",
        "tenant_root": str(toolchain_harness["materializations"][0]["path"]),
        "endpoint": "catalog.search",
    }
    assert toolchain_harness["materializations"][0]["kwargs"] == {
        "candidate_filename": "candidate.metis",
        "candidate_source": "metis 0.43\ntenant candidate {}\n",
    }
    assert toolchain_harness["compiler"].execution_count == 1


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            {
                "schema_version": 1,
                "operation": "compile-structure",
                "status": "ok",
                "diagnostics": [],
                "endpoint": "catalog.search",
                "structural_ir": {},
            },
            "invalid receipt",
        ),
        (
            {
                "schema_version": 1,
                "operation": "compile-structure",
                "status": "ok",
                "diagnostics": [],
                "endpoint": "other.endpoint",
                "structural_ir": {},
                "structural_sha256": "sha256:" + "a" * 64,
            },
            "invalid receipt",
        ),
        (
            {
                "schema_version": 1,
                "operation": "compile-structure",
                "status": "ok",
                "diagnostics": [],
                "endpoint": "catalog.search",
                "structural_ir": {},
                "structural_sha256": "not-a-sha256",
            },
            "invalid receipt",
        ),
        (
            {
                "schema_version": 1,
                "operation": "compile-structure",
                "status": "ok",
                "diagnostics": [],
                "endpoint": "catalog.search",
                "structural_ir": {"node": "Endpoint", "name": "catalog.search"},
                "structural_sha256": "sha256:" + "a" * 64,
            },
            "invalid receipt",
        ),
    ],
)
def test_compile_structure_rejects_malformed_or_mismatched_receipts(
    toolchain_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    message: str,
) -> None:
    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", lambda **_: response)

    with pytest.raises(BrainError, match=message) as raised:
        toolchain_harness["compiler"].compile_structure(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            endpoint="catalog.search",
        )

    assert raised.value.code == "COMPILER_FAILED"


@pytest.mark.parametrize(
    ("filename", "endpoint"),
    [("../candidate.metis", "catalog.search"), ("candidate.metis", None), ("candidate.metis", "")],
)
def test_compile_structure_request_identity_is_strict(
    toolchain_harness: dict[str, Any], filename: str, endpoint: str | None
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].compile_structure(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename=filename,
            endpoint=endpoint,
        )

    assert raised.value.code == "INVALID_SCHEMA"
    assert "runner_calls" not in toolchain_harness


def test_lossless_inventory_and_apply_use_only_snapshot_override(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[dict[str, Any]] = []

    def runner(**kwargs: Any) -> dict[str, Any]:
        request = kwargs["request"]
        observed.append(request)
        return {"operation": request["operation"], "status": "test-receipt"}

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", runner)
    compiler = toolchain_harness["compiler"]
    lease = _lease()
    source = "metis 0.43\ntenant replacement {}\n"
    inventory = compiler.lossless_inventory(
        lease=lease,
        source=source,
        filename="source-0.metis",
        endpoint="demo.test",
    )
    plan = {
        "contract": "metis-lossless-edit-plan/v1",
        "baseSha256": bytes_sha256(source.encode()),
        "operations": [],
    }
    applied = compiler.lossless_apply(
        lease=lease,
        source=source,
        filename="source-0.metis",
        endpoint="demo.test",
        plan=plan,
    )

    assert inventory == {"operation": "lossless-inventory", "status": "test-receipt"}
    assert applied == {"operation": "lossless-apply", "status": "test-receipt"}
    assert [item["operation"] for item in observed] == [
        "lossless-inventory",
        "lossless-apply",
    ]
    assert "plan" not in observed[0]
    assert observed[1]["plan"] == plan
    assert compiler.lossless_toolchain_identity == {
        "toolingVersion": "0.23.97",
        "langiumVersion": "4.3.0",
        "metisLanguageVersion": "0.43",
        "grammarSha256": "sha256:" + "9" * 64,
    }
    assert [
        item["kwargs"]["candidate_source"] for item in toolchain_harness["materializations"][-2:]
    ] == [source, source]


def test_lossless_target_must_already_exist_in_snapshot(
    toolchain_harness: dict[str, Any],
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].lossless_inventory(
            lease=_lease(),
            source="endpoint demo.test {}",
            filename="absent.metis",
            endpoint="demo.test",
        )

    assert raised.value.code == "STALE_CONTEXT"
    assert "runner_calls" not in toolchain_harness


def test_edit_surface_uses_exact_request_roster_and_snapshot_override(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = {
        "schema_version": 1,
        "operation": "edit-surface",
        "consumer_owned": {"opaque": True},
    }
    observed: dict[str, Any] = {}

    def runner(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return envelope

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", runner)
    compiler = toolchain_harness["compiler"]
    lease = _lease()
    original = next(item for item in lease.snapshot.files if item.path == "source-0.metis")
    replacement = "metis 0.43\ntenant replacement {}\n"
    draft_path = "drafts/new-endpoint.metis"

    result = compiler.edit_surface(
        lease=lease,
        source=replacement,
        filename=draft_path,
        endpoint="demo.test",
        allow_new=True,
    )

    materialized = toolchain_harness["materializations"][-1]
    tenant_root = materialized["path"]
    assert result is envelope
    assert observed["request"] == {
        "schema_version": 1,
        "operation": "edit-surface",
        "tenant_root": str(tenant_root),
        "relative_path": draft_path,
        "endpoint": "demo.test",
    }
    assert set(observed["request"]) == {
        "schema_version",
        "operation",
        "tenant_root",
        "relative_path",
        "endpoint",
    }
    assert "plan" not in observed["request"]
    assert materialized["kwargs"] == {
        "candidate_filename": draft_path,
        "candidate_source": replacement,
    }
    assert tenant_root.joinpath(draft_path).read_text(encoding="utf-8") == replacement
    assert tenant_root.joinpath("source-0.metis").read_bytes() == original.content
    assert all(item.path != draft_path for item in lease.snapshot.files)
    assert original.content == b"metis 0.43\ntenant t0 {}\n"
    assert compiler.execution_count == 0


def test_edit_surface_rejects_plan_at_transport_boundary_without_runner(
    toolchain_harness: dict[str, Any],
) -> None:
    compiler = toolchain_harness["compiler"]
    with pytest.raises(BrainError, match="contains a plan") as raised:
        compiler._lossless_call(
            operation="edit-surface",
            lease=_lease(),
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
            plan={"not": "admitted"},
        )

    assert raised.value.code == "INVALID_SCHEMA"
    assert "runner_calls" not in toolchain_harness
    assert not toolchain_harness["materializations"]


def test_edit_surface_public_api_does_not_accept_a_plan(
    toolchain_harness: dict[str, Any],
) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'plan'"):
        toolchain_harness["compiler"].edit_surface(
            lease=_lease(),
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
            plan={},
        )

    assert "runner_calls" not in toolchain_harness


def test_edit_surface_new_path_requires_explicit_strict_boolean_authority(
    toolchain_harness: dict[str, Any],
) -> None:
    request = {
        "lease": _lease(),
        "source": "metis 0.43\ntenant replacement {}\n",
        "filename": "drafts/new-endpoint.metis",
        "endpoint": "demo.test",
    }
    with pytest.raises(BrainError) as default_denied:
        toolchain_harness["compiler"].edit_surface(**request)
    assert default_denied.value.code == "STALE_CONTEXT"

    for invalid in (1, None, "true"):
        with pytest.raises(BrainError) as malformed:
            toolchain_harness["compiler"].edit_surface(**request, allow_new=invalid)
        assert malformed.value.code == "INVALID_SCHEMA"

    with pytest.raises(TypeError, match="unexpected keyword argument 'unknown'"):
        toolchain_harness["compiler"].edit_surface(**request, unknown=True)

    assert "runner_calls" not in toolchain_harness
    assert not toolchain_harness["materializations"]


@pytest.mark.parametrize(
    ("filename", "endpoint", "code"),
    [
        ("../source-0.metis", "demo.test", "INVALID_SCHEMA"),
        ("source-0.metis", None, "INVALID_SCHEMA"),
    ],
)
def test_edit_surface_rejects_api_identity_misuse_before_runner(
    toolchain_harness: dict[str, Any],
    filename: str,
    endpoint: str | None,
    code: str,
) -> None:
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].edit_surface(
            lease=_lease(),
            source="metis 0.43\ntenant replacement {}\n",
            filename=filename,
            endpoint=endpoint,
        )

    assert raised.value.code == code
    assert "runner_calls" not in toolchain_harness
    assert not toolchain_harness["materializations"]


def test_edit_surface_rejects_cancellation_and_toolchain_drift_before_runner(
    toolchain_harness: dict[str, Any],
) -> None:
    cancelled = _lease()
    cancelled.cancellation.set()
    with pytest.raises(BrainError) as revoked:
        toolchain_harness["compiler"].edit_surface(
            lease=cancelled,
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
        )
    assert revoked.value.code == "SESSION_REVOKED"

    with pytest.raises(BrainError) as stale:
        toolchain_harness["compiler"].edit_surface(
            lease=_lease(binding="sha256:" + "0" * 64),
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
        )
    assert stale.value.code == "STALE_CONTEXT"
    assert "runner_calls" not in toolchain_harness
    assert not toolchain_harness["materializations"]


@pytest.mark.parametrize(
    "error",
    [
        brain_tools_module._BrainIsolationError("private runner detail"),
        subprocess.TimeoutExpired(["pinned-edit-surface"], 180),
        OSError("private operating-system detail"),
    ],
)
def test_edit_surface_normalizes_isolation_timeout_and_os_failures(
    toolchain_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    def fail_runner(**_kwargs: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", fail_runner)
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].edit_surface(
            lease=_lease(),
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
        )

    assert raised.value.code == "LOSSLESS_FAILED"
    assert raised.value.status == 503
    assert "private" not in str(raised.value)


def test_edit_surface_honors_post_runner_cancellation(
    toolchain_harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = _lease()

    def cancel_runner(**_kwargs: Any) -> dict[str, Any]:
        lease.cancellation.set()
        return {"operation": "edit-surface", "private": "consumer-owned"}

    monkeypatch.setattr(brain_tools_module, "_run_brain_runner", cancel_runner)
    with pytest.raises(BrainError) as raised:
        toolchain_harness["compiler"].edit_surface(
            lease=lease,
            source="metis 0.43\ntenant replacement {}\n",
            filename="source-0.metis",
            endpoint="demo.test",
        )

    assert raised.value.code == "SESSION_REVOKED"


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
