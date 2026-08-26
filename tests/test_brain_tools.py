from __future__ import annotations

import json
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_tools as brain_tools_module
from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import grammar_stdlib_oracle as grammar_oracle
from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_protocol import BrainError, bytes_sha256
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import BrainCompiler


def _pin() -> dict[str, Any]:
    return {
        "catalog_pin_id": "catalog/test",
        "catalog_pin_sha256": "sha256:" + "d" * 64,
        "revision": "a" * 40,
        "tree": "b" * 40,
        "language_version": "0.43",
        "overlay": None,
    }


def _lease(*, files: int = 1) -> OperationLease:
    records = tuple(
        SnapshotFile(
            path=f"source-{index}.metis",
            content=f"metis 0.43\ntenant t{index} {{}}\n".encode(),
            sha256=bytes_sha256(f"metis 0.43\ntenant t{index} {{}}\n".encode()),
        )
        for index in range(files)
    )
    snapshot = ContextSnapshot(
        tenant_alias="demo",
        tenant_id="tenant-one",
        root_device=1,
        root_inode=2,
        revision="sha256:" + "c" * 64,
        toolchain_binding="sha256:" + "e" * 64,
        files=records,
        total_bytes=sum(len(item.content) for item in records),
    )
    return OperationLease(
        session_id="s" * 43,
        client_id="visix",
        tenant_alias="demo",
        capabilities=frozenset({"compile"}),
        snapshot=snapshot,
        cancellation=threading.Event(),
    )


def _compiler(
    monkeypatch: pytest.MonkeyPatch,
    observed: dict[str, Any],
    *,
    fail: bool = False,
) -> BrainCompiler:
    monkeypatch.setattr(
        brain_tools_module,
        "_brain_pin_identity",
        lambda metis_root: (
            observed.update({"metis_root": metis_root}) or (_pin(), ("a" * 40, "b" * 40, "c" * 64))
        ),
    )
    monkeypatch.setattr(catalog_pin, "load_catalog_maintenance_pin", lambda: {"runtime": {}})
    monkeypatch.setattr(catalog_pin, "_verify_node", lambda _path, _runtime: b"node")
    monkeypatch.setattr(catalog_pin, "SANDBOX_EXEC", Path("/bin/sh"))

    @contextmanager
    def isolated(**kwargs: Any):
        observed["isolation"] = kwargs
        yield Path("/isolated-metis")

    monkeypatch.setattr(brain_tools_module, "_isolated_metis_repository", isolated)

    class Session:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            observed["request"] = kwargs
            if fail:
                raise grammar_oracle.GrammarStdlibOracleError("secret internal detail")
            return {"status": "ok", "redacted": True}

    @contextmanager
    def session(**kwargs: Any):
        observed["session"] = kwargs
        yield Session()

    monkeypatch.setattr(grammar_oracle, "grammar_stdlib_oracle_session", session)
    return BrainCompiler(metis_root=Path("/metis"), node_path=Path("/node"))


def test_compiler_uses_git_objects_only_and_returns_source_redacted_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    secret = "metis 0.43\n// unique caller-only secret\ntenant candidate {}\n"
    lease = _lease()

    receipt = compiler.compile(
        lease=lease,
        source=secret,
        filename="candidate.metis",
        execution_mode="source",
        endpoint=None,
    )

    assert observed["isolation"]["metis_root"] == Path("/metis")
    assert observed["isolation"]["expected_identity"] == (
        "a" * 40,
        "b" * 40,
        "c" * 64,
    )
    assert observed["session"]["metis_root"] == Path("/isolated-metis")
    assert observed["request"]["workspace_sources"] == {
        "source-0.metis": "metis 0.43\ntenant t0 {}\n"
    }
    assert secret not in json.dumps(receipt)
    assert receipt["context_revision"] == lease.snapshot.revision
    assert receipt["claims"] == {
        "archive_snapshot": True,
        "network_denied": True,
        "writes_denied": True,
        "tenant_modified": False,
        "semantic_correctness": False,
    }
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert compiler.execution_count == 1


def test_candidate_replaces_same_workspace_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    compiler.compile(
        lease=_lease(),
        source="metis 0.43\ntenant replacement {}\n",
        filename="source-0.metis",
        execution_mode="source",
        endpoint=None,
    )
    assert observed["request"]["workspace_sources"] == {}


def test_compiler_rejects_context_over_64_before_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    with pytest.raises(BrainError) as raised:
        compiler.compile(
            lease=_lease(files=65),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )
    assert raised.value.code == "CONTEXT_TOO_LARGE"
    assert "request" not in observed


def test_compiler_rejects_workspace_source_outside_oracle_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    raw = ("metis 0.43\n//" + "x" * grammar_oracle.MAX_SOURCE_BYTES).encode()
    base = _lease()
    oversized = ContextSnapshot(
        tenant_alias=base.snapshot.tenant_alias,
        tenant_id=base.snapshot.tenant_id,
        root_device=1,
        root_inode=2,
        revision=base.snapshot.revision,
        toolchain_binding=base.snapshot.toolchain_binding,
        files=(SnapshotFile("large.metis", raw, bytes_sha256(raw)),),
        total_bytes=len(raw),
    )
    lease = OperationLease(
        session_id=base.session_id,
        client_id=base.client_id,
        tenant_alias=base.tenant_alias,
        capabilities=base.capabilities,
        snapshot=oversized,
        cancellation=base.cancellation,
    )
    with pytest.raises(BrainError) as raised:
        compiler.compile(
            lease=lease,
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )
    assert raised.value.code == "CONTEXT_UNSUPPORTED"
    assert "request" not in observed


def test_cancelled_session_never_invokes_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    lease = _lease()
    lease.cancellation.set()
    with pytest.raises(BrainError) as raised:
        compiler.compile(
            lease=lease,
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )
    assert raised.value.code == "SESSION_REVOKED"
    assert "request" not in observed


def test_compiler_internal_error_is_normalized_without_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed, fail=True)
    with pytest.raises(BrainError) as raised:
        compiler.compile(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename="candidate.metis",
            execution_mode="source",
            endpoint=None,
        )
    assert raised.value.code == "COMPILER_FAILED"
    assert "secret" not in str(raised.value)


def test_compiler_timeout_is_normalized_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)

    @contextmanager
    def timed_out_session(**_kwargs: Any):
        class Session:
            def run(self, **_request: Any) -> dict[str, Any]:
                raise subprocess.TimeoutExpired(["pinned-compiler"], 120)

        yield Session()

    monkeypatch.setattr(
        grammar_oracle,
        "grammar_stdlib_oracle_session",
        timed_out_session,
    )
    request = {
        "lease": _lease(),
        "source": "metis 0.43\ntenant candidate {}\n",
        "filename": "candidate.metis",
        "execution_mode": "source",
        "endpoint": None,
    }
    for _attempt in range(2):
        with pytest.raises(BrainError) as raised:
            compiler.compile(**request)
        assert raised.value.code == "COMPILER_FAILED"


@pytest.mark.parametrize(
    ("filename", "mode", "endpoint", "code"),
    [
        ("../escape.metis", "source", None, "INVALID_SCHEMA"),
        ("a//b.metis", "source", None, "INVALID_SCHEMA"),
        ("a/./b.metis", "source", None, "INVALID_SCHEMA"),
        ("candidate.metis", "unknown", None, "INVALID_SCHEMA"),
        ("candidate.metis", "source", "endpoint.name", "INVALID_SCHEMA"),
    ],
)
def test_compiler_request_fields_are_strict(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    mode: str,
    endpoint: str | None,
    code: str,
) -> None:
    observed: dict[str, Any] = {}
    compiler = _compiler(monkeypatch, observed)
    with pytest.raises(BrainError) as raised:
        compiler.compile(
            lease=_lease(),
            source="metis 0.43\ntenant candidate {}\n",
            filename=filename,
            execution_mode=mode,
            endpoint=endpoint,
        )
    assert raised.value.code == code
    assert "request" not in observed
