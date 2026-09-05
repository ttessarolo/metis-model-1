from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
from jsonschema import Draft202012Validator

import metis_model1.oracles as oracle_module
from metis_model1.oracles import (
    ARTIFACT_ROOT,
    OracleError,
    OracleSession,
    run_oracle,
    verify_oracle_envelope,
)

METIS_ROOT = Path(
    os.environ.get(
        "METIS_MODEL1_METIS_ROOT",
        "/Users/tommasotessarolo/Developer/ares-matioska/metis",
    )
).resolve()
RUNNER = Path(__file__).parents[1] / "runtime/metis_oracle/runner.ts"
PINNED_NODE = oracle_module._resolve_pinned_node()[0]
VALID = 'metis 0.43\nendpoint play.test as "test" {\n  variant v { empty }\n}\n'


def test_l66_public_capsule_execution_stops_before_request_filesystem_or_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        observed.append("forbidden-boundary")
        raise AssertionError("public Oracle crossed the protected-broker STOP")

    monkeypatch.setattr(oracle_module, "_validate_capsule_request", forbidden)
    monkeypatch.setattr(oracle_module, "_strict_canonical_path", forbidden)
    monkeypatch.setattr(oracle_module.subprocess, "Popen", forbidden)
    with pytest.raises(OracleError, match="protected execution broker"):
        oracle_module.run_oracle_from_capsule(
            {},
            capsule_root="absent-capsule",
            process_root="absent-process",
            output_path="absent-output",
        )
    assert observed == []


def test_l66_registered_broker_still_stops_before_unimplemented_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        observed.append("forbidden-boundary")
        raise AssertionError("public Oracle crossed the unimplemented transport STOP")

    monkeypatch.setattr(
        oracle_module,
        "REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256",
        "sha256:" + "1" * 64,
    )
    monkeypatch.setattr(oracle_module, "_validate_capsule_request", forbidden)
    monkeypatch.setattr(oracle_module, "_strict_canonical_path", forbidden)
    monkeypatch.setattr(oracle_module.subprocess, "Popen", forbidden)
    with pytest.raises(OracleError, match="transport is not implemented"):
        oracle_module.run_oracle_from_capsule(
            {},
            capsule_root="absent-capsule",
            process_root="absent-process",
            output_path="absent-output",
        )
    assert observed == []


@pytest.fixture
def capsule_interior_test_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authorize only tests that explicitly exercise post-broker internals."""

    assert oracle_module.REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None
    monkeypatch.setattr(oracle_module, "_require_protected_execution_broker", lambda: None)


def _oracle_open_fd_snapshot() -> dict[int, tuple[int, int, int, int]]:
    """Measure live descriptors by fstat; discard the closed /dev/fd scan handle."""

    discovered = [int(name) for name in os.listdir("/dev/fd") if name.isdigit()]
    ceiling = max([64, *discovered]) + 32
    census: dict[int, tuple[int, int, int, int]] = {}
    for descriptor in range(ceiling):
        try:
            metadata = os.fstat(descriptor)
        except OSError:
            continue
        census[descriptor] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_rdev,
        )
    return census


def _oracle_raise_on_line_after(
    function: object,
    needle: str,
    invoke: object,
    *,
    target_needle: str | None = None,
) -> BaseException:
    """Inject a BaseException at a source-resolved post-acquisition line."""

    source_function = getattr(function, "__wrapped__", function)
    source, start = inspect.getsourcelines(source_function)
    matches = [index for index, line in enumerate(source) if needle in line]
    assert len(matches) == 1, (needle, matches)
    target_index = matches[0] + 1
    if target_needle is not None:
        targets = [
            index
            for index, line in enumerate(source[target_index:], start=target_index)
            if target_needle in line
        ]
        assert targets, (needle, target_needle)
        target_index = targets[0]
    target_line = start + target_index

    def trace(frame: object, event: str, _argument: object):
        if (
            event == "line"
            and frame.f_code.co_filename == source_function.__code__.co_filename
            and frame.f_lineno == target_line
        ):
            sys.settrace(None)
            raise KeyboardInterrupt
        return trace

    retained: list[BaseException] = []
    sys.settrace(trace)
    try:
        invoke()
    except BaseException as error:
        retained.append(error)
    finally:
        sys.settrace(None)
    assert len(retained) == 1
    assert isinstance(retained[0], KeyboardInterrupt)
    assert retained[0].__traceback__ is not None
    return retained[0]


ORACLE_FD_TRANSFER_CASES = (
    "capsule-directory-dup",
    "capsule-directory-child-fstat",
    "capsule-roster-child-return",
    "capsule-read-parent-return",
    "capsule-materialize-target-open",
    "capsule-materialize-parent-return",
    "capsule-materialize-directory-return",
    "secure-output-child-fstat",
    "capsule-run-materializer-return",
    "run-oracle-directory-open",
)


@pytest.mark.parametrize("case", ORACLE_FD_TRANSFER_CASES)
def test_oracle_fd_transfer_windows_are_baseexception_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Every sequential descriptor handoff must close on interruption and I/O failure."""

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fds: list[int] = []
    probe_fds: list[int] = []
    probe_identities: list[tuple[int, int]] = []
    function: object
    invoke: object
    needle: str
    target_needle: str | None = None

    if case.startswith("capsule-directory"):
        root = tmp_path / case
        root.mkdir(mode=0o700)
        if case == "capsule-directory-child-fstat":
            (root / "child").mkdir(mode=0o700)
        root_fd = os.open(root, directory_flags)
        fds.append(root_fd)
        function = oracle_module._open_capsule_preimage_directory_at
        if case == "capsule-directory-dup":
            needle = "current_fd = os.dup(root_fd)"

            def invoke() -> None:
                function(root_fd, (), create=False)

        else:
            needle = "child_fd = os.open(component, flags, dir_fd=current_fd)"
            target_needle = "metadata = os.fstat(child_fd)"

            def invoke() -> None:
                function(root_fd, ("child",), create=False)
    elif case == "capsule-roster-child-return":
        root = tmp_path / case
        child = root / "child"
        child.mkdir(parents=True, mode=0o700)
        root_fd = os.open(root, directory_flags)
        fds.append(root_fd)
        function = oracle_module._capsule_preimage_roster_at
        needle = "child_fd = _open_capsule_preimage_directory_at("
        target_needle = "child_files, child_directories = _capsule_preimage_roster_at("
        original_open_directory = oracle_module._open_capsule_preimage_directory_at

        def observe_open_directory(*args: object, **kwargs: object) -> int:
            descriptor = original_open_directory(*args, **kwargs)
            metadata = os.fstat(descriptor)
            probe_fds.append(descriptor)
            probe_identities.append((metadata.st_dev, metadata.st_ino))
            return descriptor

        monkeypatch.setattr(
            oracle_module,
            "_open_capsule_preimage_directory_at",
            observe_open_directory,
        )

        def invoke() -> None:
            function(root_fd)
    elif case == "capsule-read-parent-return":
        root = tmp_path / case
        root.mkdir(mode=0o700)
        (root / "value").write_bytes(b"value")
        root_fd = os.open(root, directory_flags)
        fds.append(root_fd)
        function = oracle_module._read_capsule_preimage_file_at
        needle = "parent_fd = _open_capsule_preimage_directory_at("
        target_needle = "descriptor = os.open("

        def invoke() -> None:
            function(root_fd, PurePosixPath("value"), 64, "fd read")
    elif case.startswith("capsule-materialize"):
        invocation = tmp_path / f"{case}-invocation"
        invocation.mkdir(mode=0o700)
        invocation_fd = os.open(invocation, directory_flags)
        fds.append(invocation_fd)
        manifest: dict[str, object] = {
            "manifest_sha256": "sha256:" + "1" * 64,
            "files": [],
        }
        contents: dict[str, bytes] = {}
        if case != "capsule-materialize-target-open":
            contents = (
                {"value": b"value"}
                if case == "capsule-materialize-parent-return"
                else {"nested/value": b"value"}
            )
            manifest["files"] = [{"path": name, "mode": 0o444} for name in contents]
        function = oracle_module._materialize_runtime_capsule_preimage
        if case == "capsule-materialize-target-open":
            needle = "target_fd = os.open("
            target_needle = "all_files ="
        elif case == "capsule-materialize-parent-return":
            needle = "parent_fd = _open_capsule_preimage_directory_at("
            target_needle = "_write_capsule_preimage_file_at("
        else:
            needle = "directory_fd = _open_capsule_preimage_directory_at("
            target_needle = "os.fchmod(directory_fd"

        def invoke() -> None:
            function(invocation, invocation_fd, manifest, contents)
    elif case == "secure-output-child-fstat":
        root = tmp_path / case
        root.mkdir(mode=0o700)
        output = root / "nested" / "result.json"
        function = oracle_module._secure_output_parent
        needle = "child_fd = os.open(component, directory_flags, dir_fd=parent_fd)"
        target_needle = "metadata = os.fstat(child_fd)"

        def invoke() -> None:
            with function(root, output):
                pass

    elif case == "capsule-run-materializer-return":
        assert oracle_module.REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None
        monkeypatch.setattr(
            oracle_module,
            "_require_protected_execution_broker",
            lambda: None,
        )
        capsule = tmp_path / f"{case}-capsule"
        capsule.mkdir(mode=0o700)
        process = tmp_path / f"{case}-process"
        process.mkdir(mode=0o700)
        semantic = oracle_module.build_oracle_request(
            VALID,
            endpoint="play.test",
            revision=oracle_module.PINNED_METIS_REVISION,
            tree=oracle_module.PINNED_METIS_TREE,
        )
        request = {
            "schema_version": 3,
            "protocol": oracle_module.CAPSULE_PROTOCOL,
            "execution_id": "candidate-fd.author",
            "run_nonce": "1" * 64,
            "capsule_manifest_sha256": "sha256:" + "2" * 64,
            "request": semantic,
        }
        manifest = {"manifest_sha256": request["capsule_manifest_sha256"], "files": []}
        leaked: list[int] = []
        monkeypatch.setattr(
            oracle_module,
            "verify_runtime_capsule",
            lambda *_args, **_kwargs: (capsule, manifest),
        )
        monkeypatch.setattr(oracle_module, "_capture_runtime_capsule_contents", lambda *_: {})
        monkeypatch.setattr(
            oracle_module,
            "_resolve_pinned_node",
            lambda: (Path(sys.executable).resolve(), oracle_module.PINNED_NODE_BINARY_SHA256),
        )

        @contextlib.contextmanager
        def runtime_preimage(invocation: Path, *_args: object):
            root_descriptor = os.open(invocation, directory_flags)
            node_path = Path(sys.executable).resolve()
            node_descriptor = os.open(node_path, os.O_RDONLY | os.O_CLOEXEC)
            try:
                yield invocation, node_path, root_descriptor, node_descriptor
            finally:
                os.close(node_descriptor)
                os.close(root_descriptor)

        monkeypatch.setattr(
            oracle_module,
            "_owned_materialized_runtime_preimage",
            runtime_preimage,
        )

        def materialize(invocation: Path, *_args: object) -> tuple[Path, int]:
            descriptor = os.open(invocation, directory_flags)
            leaked.append(descriptor)
            return invocation, descriptor

        monkeypatch.setattr(oracle_module, "_materialize_runtime_capsule_preimage", materialize)
        function = oracle_module.run_oracle_from_capsule
        needle = "_owned_materialized_runtime_capsule_preimage("
        target_needle = "write_fd = -1"

        def invoke() -> None:
            function(
                request,
                capsule_root=capsule,
                process_root=process,
                output_path=process / "result.json",
            )
    else:
        root = tmp_path / "run-oracle-root"
        root.mkdir(mode=0o700)
        modules = root / "tooling/node_modules"
        modules.mkdir(parents=True)
        (root / "tooling/package.json").write_text("{}\n", encoding="utf-8")
        (root / "tooling/package-lock.json").write_text("{}\n", encoding="utf-8")
        runner = tmp_path / "runner.ts"
        runner.write_text("runner", encoding="utf-8")
        loader = tmp_path / "native_ts_loader.mjs"
        loader.write_text("loader", encoding="utf-8")
        node = Path(sys.executable).resolve()
        output = tmp_path / "run-oracle-results" / "oracle.json"
        result = {"diagnostics": {}, "ast": {"inventory": {}}, "ir": {"value": None}}

        class Holder:
            def cleanup(self) -> None:
                return None

        monkeypatch.setattr(oracle_module, "_assert_sandbox_policy", lambda: None)
        monkeypatch.setattr(
            oracle_module,
            "validate_pinned_metis",
            lambda *_args, **_kwargs: (
                root,
                oracle_module.PINNED_METIS_REVISION,
                oracle_module.PINNED_METIS_TREE,
                {
                    "package_sha256": oracle_module.PINNED_TOOLING_PACKAGE_SHA256,
                    "lock_sha256": oracle_module.PINNED_TOOLING_LOCK_SHA256,
                    "node_modules_sha256": oracle_module.PINNED_NODE_MODULES_SHA256,
                },
            ),
        )
        monkeypatch.setattr(oracle_module, "_validate_runner_path", lambda path, *_: Path(path))
        monkeypatch.setattr(oracle_module, "_validate_output_path", lambda path, *_: Path(path))
        monkeypatch.setattr(
            oracle_module,
            "_resolve_pinned_node",
            lambda: (node, oracle_module.PINNED_NODE_BINARY_SHA256),
        )
        monkeypatch.setattr(
            oracle_module,
            "_runtime_identity",
            lambda *_: oracle_module._runtime_identity_policy(
                oracle_module.PINNED_METIS_REVISION,
                oracle_module.PINNED_METIS_TREE,
            ),
        )
        monkeypatch.setattr(
            oracle_module,
            "_node_modules_sha256",
            lambda *_: oracle_module.PINNED_NODE_MODULES_SHA256,
        )
        monkeypatch.setattr(
            oracle_module,
            "_file_sha256",
            lambda path: (
                oracle_module.PINNED_NODE_BINARY_SHA256
                if Path(path) == node
                else oracle_module.PINNED_TOOLING_PACKAGE_SHA256
                if Path(path).name == "package.json"
                else oracle_module.PINNED_TOOLING_LOCK_SHA256
                if Path(path).name == "package-lock.json"
                else oracle_module.PINNED_LOADER_SHA256
                if Path(path).name == "native_ts_loader.mjs"
                else oracle_module.PINNED_RUNNER_SHA256
            ),
        )
        monkeypatch.setattr(
            oracle_module,
            "_git",
            lambda _root, *args: (
                oracle_module.PINNED_METIS_REVISION
                if args == ("rev-parse", "HEAD")
                else oracle_module.PINNED_METIS_TREE
                if args == ("rev-parse", "HEAD^{tree}")
                else ""
            ),
        )
        monkeypatch.setattr(
            oracle_module,
            "_build_isolated_snapshot",
            lambda *_args: (Holder(), root, modules, runner, loader, node),
        )
        monkeypatch.setattr(
            oracle_module,
            "_check_response",
            lambda value, *_args, **_kwargs: value,
        )
        monkeypatch.setattr(oracle_module, "verify_oracle_envelope", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            oracle_module.subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout=oracle_module._canonical(result).decode(), stderr=""
            ),
        )
        function = oracle_module.OracleSession.run
        needle = "directory_fd = os.open(output.parent, os.O_RDONLY)"
        target_needle = "os.fsync(directory_fd)"

        def invoke() -> None:
            oracle_module.run_oracle(
                VALID,
                metis_root=root,
                runner_path=runner,
                output_path=output,
            )

    before = _oracle_open_fd_snapshot()
    after: dict[int, tuple[int, int, int, int]] = {}
    extra_fds: set[int] = set()
    try:
        _oracle_raise_on_line_after(
            function,
            needle,
            invoke,
            target_needle=target_needle,
        )
        after = _oracle_open_fd_snapshot()
        extra_fds = set(after) - set(before)

        if case == "capsule-roster-child-return":
            assert len(probe_fds) == len(probe_identities) == 1
            expected = (root / "child").stat()
            assert probe_identities == [(expected.st_dev, expected.st_ino)]
            assert after == before, "roster child descriptor survived the try-boundary interrupt"
        elif case == "capsule-directory-child-fstat":
            # The same acquisition must also close its child when the real fstat fails.
            for descriptor in extra_fds:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            before_oserror = _oracle_open_fd_snapshot()
            original_fstat = oracle_module.os.fstat
            fstat_failed = False

            def fail_child_fstat(descriptor: int):
                nonlocal fstat_failed
                if not fstat_failed:
                    fstat_failed = True
                    raise OSError("injected child fstat failure")
                return original_fstat(descriptor)

            monkeypatch.setattr(oracle_module.os, "fstat", fail_child_fstat)
            with pytest.raises(OSError, match="injected child fstat failure"):
                invoke()
            after_oserror = _oracle_open_fd_snapshot()
            assert after == before, "KeyboardInterrupt after child open leaked descriptors"
            assert after_oserror == before_oserror, "child fstat OSError leaked descriptors"
            monkeypatch.setattr(oracle_module.os, "fstat", original_fstat)
        else:
            assert after == before
    finally:
        for descriptor in probe_fds:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        for descriptor in set(after) - set(before):
            with contextlib.suppress(OSError):
                os.close(descriptor)
        for descriptor in fds:
            with contextlib.suppress(OSError):
                os.close(descriptor)


@pytest.fixture
def artifact_tmp() -> Iterator[Path]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="oracle-test-", dir=ARTIFACT_ROOT))
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture(scope="module")
def reusable_oracle_session() -> Iterator[OracleSession]:
    with OracleSession(metis_root=METIS_ROOT, runner_path=RUNNER) as session:
        yield session


def execute(
    output_dir: Path,
    source: str = VALID,
    *,
    session: OracleSession | None = None,
    **kwargs: object,
) -> dict:
    if session is not None:
        return session.run(source, **kwargs)
    return run_oracle(
        source,
        metis_root=METIS_ROOT,
        runner_path=RUNNER,
        output_path=output_dir / "oracle.json",
        **kwargs,
    )


@pytest.fixture
def synthetic_session_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A tiny authority that exercises session lifecycle without the real runtime."""

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    root = tmp_path / "metis"
    modules = root / "tooling/node_modules/pkg"
    modules.mkdir(parents=True)
    module_file = modules / "value.js"
    module_file.write_bytes(b"safe")
    package = root / "tooling/package.json"
    lock = root / "tooling/package-lock.json"
    package.write_text('{"name":"fixture"}\n', encoding="utf-8")
    lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    runner = tmp_path / "runner.ts"
    loader = tmp_path / "native_ts_loader.mjs"
    node = tmp_path / "node"
    sandbox = tmp_path / "sandbox-exec"
    schema = tmp_path / "oracle-result.schema.json"
    runner.write_text("runner\n", encoding="utf-8")
    loader.write_text("loader\n", encoding="utf-8")
    node.write_bytes(b"node")
    node.chmod(0o755)
    sandbox.write_bytes(b"sandbox")
    sandbox.chmod(0o755)
    schema.write_text("{}\n", encoding="utf-8")

    modules_digest = oracle_module._node_modules_sha256(root / "tooling/node_modules")
    package_digest = oracle_module._file_sha256(package)
    lock_digest = oracle_module._file_sha256(lock)
    runner_digest = oracle_module._file_sha256(runner)
    loader_digest = oracle_module._file_sha256(loader)
    node_digest = oracle_module._file_sha256(node)
    state: dict[str, object] = {
        "builds": 0,
        "runs": 0,
        "snapshots": [],
        "status": "",
        "on_run": None,
    }

    monkeypatch.setattr(oracle_module, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(oracle_module, "RUNNER_PATH", runner.resolve())
    monkeypatch.setattr(oracle_module, "LOADER_PATH", loader.resolve())
    monkeypatch.setattr(oracle_module, "SCHEMA_PATH", schema.resolve())
    monkeypatch.setattr(oracle_module, "SANDBOX_EXEC_PATH", sandbox.resolve())
    monkeypatch.setattr(oracle_module, "PINNED_TOOLING_PACKAGE_SHA256", package_digest)
    monkeypatch.setattr(oracle_module, "PINNED_TOOLING_LOCK_SHA256", lock_digest)
    monkeypatch.setattr(oracle_module, "PINNED_NODE_MODULES_SHA256", modules_digest)
    monkeypatch.setattr(oracle_module, "PINNED_RUNNER_SHA256", runner_digest)
    monkeypatch.setattr(oracle_module, "PINNED_LOADER_SHA256", loader_digest)
    monkeypatch.setattr(oracle_module, "PINNED_NODE_BINARY_SHA256", node_digest)
    monkeypatch.setattr(oracle_module, "PINNED_NODE_BYTES", len(node.read_bytes()))
    monkeypatch.setattr(oracle_module, "_assert_sandbox_policy", lambda: None)
    monkeypatch.setattr(
        oracle_module, "_resolve_pinned_node", lambda: (node.resolve(), node_digest)
    )

    def validate(*_args: object, **_kwargs: object):
        return (
            root.resolve(),
            oracle_module.PINNED_METIS_REVISION,
            oracle_module.PINNED_METIS_TREE,
            {
                "package_sha256": package_digest,
                "lock_sha256": lock_digest,
                "node_modules_sha256": modules_digest,
            },
        )

    monkeypatch.setattr(oracle_module, "validate_pinned_metis", validate)

    def build(*_args: object):
        state["builds"] = int(state["builds"]) + 1
        holder = tempfile.TemporaryDirectory(prefix="session-fixture-", dir=tmp_path)
        snapshot = Path(holder.name)
        shutil.copytree(root, snapshot, dirs_exist_ok=True)
        snapshot_runner = snapshot / ".metis-oracle/runner.ts"
        snapshot_loader = snapshot / ".metis-oracle/native_ts_loader.mjs"
        snapshot_node = snapshot / ".metis-oracle/node"
        snapshot_runner.parent.mkdir()
        shutil.copyfile(runner, snapshot_runner)
        shutil.copyfile(loader, snapshot_loader)
        shutil.copyfile(node, snapshot_node)
        shutil.copymode(node, snapshot_node)
        snapshots = state["snapshots"]
        assert isinstance(snapshots, list)
        snapshots.append(snapshot)
        return (
            holder,
            snapshot,
            snapshot / "tooling/node_modules",
            snapshot_runner,
            snapshot_loader,
            snapshot_node,
        )

    monkeypatch.setattr(oracle_module, "_build_isolated_snapshot", build)

    def git(_root: Path, *args: str) -> str:
        if args == ("status", "--porcelain=v1", "--untracked-files=no"):
            return str(state["status"])
        if args == ("rev-parse", "HEAD"):
            return oracle_module.PINNED_METIS_REVISION
        if args == ("rev-parse", "HEAD^{tree}"):
            return oracle_module.PINNED_METIS_TREE
        raise AssertionError(args)

    monkeypatch.setattr(oracle_module, "_git", git)

    result = {"diagnostics": {}, "ast": {"inventory": {}}, "ir": {"value": None}}

    def run(*_args: object, **_kwargs: object):
        state["runs"] = int(state["runs"]) + 1
        callback = state["on_run"]
        if callback is not None:
            assert callable(callback)
            callback()
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=oracle_module._canonical(result).decode("utf-8"),
            stderr="",
        )

    monkeypatch.setattr(oracle_module.subprocess, "run", run)
    monkeypatch.setattr(oracle_module, "_check_response", lambda value, *_args, **_kwargs: value)
    monkeypatch.setattr(
        oracle_module,
        "verify_oracle_envelope",
        lambda envelope, **_kwargs: envelope,
    )
    return {
        "artifact_root": artifact_root,
        "root": root.resolve(),
        "modules": root / "tooling/node_modules",
        "module_file": module_file,
        "runner": runner.resolve(),
        "state": state,
    }


def _synthetic_session(authority: dict) -> OracleSession:
    return OracleSession(
        metis_root=authority["root"],
        runner_path=authority["runner"],
    )


def test_oracle_session_reuses_one_snapshot_and_is_byte_equal_to_one_shot(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    artifacts = authority["artifact_root"]
    with _synthetic_session(authority) as session:
        first = session.run(VALID, output_path=artifacts / "session-one.json")
        second = session.run(VALID, output_path=artifacts / "session-two.json")
    one_shot = run_oracle(
        VALID,
        metis_root=authority["root"],
        runner_path=authority["runner"],
        output_path=artifacts / "one-shot.json",
    )

    state = authority["state"]
    assert state["builds"] == 2
    assert state["runs"] == 3
    assert first == second == one_shot
    assert (artifacts / "session-one.json").read_bytes() == (
        artifacts / "session-two.json"
    ).read_bytes()
    assert (artifacts / "session-one.json").read_bytes() == (
        artifacts / "one-shot.json"
    ).read_bytes()


def test_oracle_session_returned_envelope_cannot_mutate_private_runtime_identity(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    artifacts = authority["artifact_root"]
    with _synthetic_session(authority) as session:
        first = session.run(VALID, output_path=artifacts / "first.json")
        first_runtime = first["evidence"]["runtime_identity"]
        first_runtime["loader_path"] = "snapshot://forged/loader"
        first_runtime["loader_flags"].append("--forged")

        second = session.run(VALID, output_path=artifacts / "second.json")

    second_runtime = second["evidence"]["runtime_identity"]
    assert (
        second_runtime["loader_path"]
        == oracle_module._runtime_identity_policy(
            oracle_module.PINNED_METIS_REVISION,
            oracle_module.PINNED_METIS_TREE,
            {
                "package_sha256": oracle_module.PINNED_TOOLING_PACKAGE_SHA256,
                "lock_sha256": oracle_module.PINNED_TOOLING_LOCK_SHA256,
                "node_modules_sha256": oracle_module.PINNED_NODE_MODULES_SHA256,
            },
        )["loader_path"]
    )
    assert second_runtime["loader_flags"] == list(oracle_module.LOADER_FLAGS)


def test_oracle_session_roster_root_metadata_is_guarded(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    output = authority["artifact_root"] / "blocked.json"
    session = _synthetic_session(authority)
    with pytest.raises(OracleError, match="isolated tooling metadata changed"), session:
        assert session._snapshot_modules is not None
        session._snapshot_modules.chmod(0o700)
        session.run(VALID, output_path=output)
    assert not output.exists()


def test_oracle_session_roster_detects_topology_change_during_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "roster-race"
    root.mkdir()
    descriptor = oracle_module._open_metadata_directory(root, "test roster")
    original_listdir = oracle_module.os.listdir
    changed = False

    def mutate_after_listing(directory_fd: int) -> list[str]:
        nonlocal changed
        names = original_listdir(directory_fd)
        if not changed:
            changed = True
            (root / "late-entry").write_bytes(b"late")
        return names

    monkeypatch.setattr(oracle_module.os, "listdir", mutate_after_listing)
    try:
        with pytest.raises(OracleError, match="changed during traversal"):
            oracle_module._directory_metadata_roster(descriptor)
    finally:
        oracle_module.os.close(descriptor)
    assert changed


def test_oracle_session_roster_has_explicit_entry_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bounded-roster"
    root.mkdir()
    (root / "one").write_bytes(b"1")
    (root / "two").write_bytes(b"2")
    descriptor = oracle_module._open_metadata_directory(root, "test roster")
    monkeypatch.setattr(oracle_module, "_MAX_ORACLE_SESSION_ROSTER_ENTRIES", 2)
    try:
        with pytest.raises(OracleError, match="roster exceeds its bound"):
            oracle_module._directory_metadata_roster(descriptor)
    finally:
        oracle_module.os.close(descriptor)


@pytest.mark.parametrize("attack", ("add", "remove", "symlink"))
def test_oracle_session_snapshot_roster_drift_poisoned_before_publication(
    synthetic_session_authority: dict,
    attack: str,
) -> None:
    authority = synthetic_session_authority
    output = authority["artifact_root"] / "blocked.json"
    session = _synthetic_session(authority)
    with pytest.raises(OracleError, match="isolated tooling metadata changed"), session:
        assert session._snapshot_modules is not None
        target = session._snapshot_modules / "pkg/value.js"
        if attack == "add":
            (session._snapshot_modules / "added.js").write_bytes(b"added")
        elif attack == "remove":
            target.unlink()
        else:
            target.unlink()
            target.symlink_to("/etc/passwd")
        session.run(VALID, output_path=output)
    assert not output.exists()
    with pytest.raises(OracleError, match="not active"):
        session.run(VALID, output_path=output)


def test_oracle_session_source_same_size_mtime_restore_is_detected_by_ctime(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    target = authority["module_file"]
    before = target.stat()
    output = authority["artifact_root"] / "blocked.json"
    session = _synthetic_session(authority)
    with pytest.raises(OracleError, match="source tooling metadata changed"), session:
        target.write_bytes(b"evil")
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        session.run(VALID, output_path=output)
    assert not output.exists()


def test_oracle_session_detects_runtime_mutation_during_child_before_publication(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    output = authority["artifact_root"] / "blocked.json"
    session = _synthetic_session(authority)

    def attack() -> None:
        assert session._snapshot_modules is not None
        (session._snapshot_modules / "pkg/value.js").write_bytes(b"evil")

    authority["state"]["on_run"] = attack
    with pytest.raises(OracleError, match="isolated tooling metadata changed"), session:
        session.run(VALID, output_path=output)
    assert not output.exists()


@pytest.mark.parametrize("binding", ("policy", "path"))
def test_oracle_session_process_binding_drift_is_fail_closed(
    synthetic_session_authority: dict,
    monkeypatch: pytest.MonkeyPatch,
    binding: str,
) -> None:
    authority = synthetic_session_authority
    output = authority["artifact_root"] / "blocked.json"
    session = _synthetic_session(authority)
    pattern = "process authority" if binding == "policy" else "Node resolution environment"
    with pytest.raises(OracleError, match=pattern), session:
        if binding == "policy":
            monkeypatch.setattr(oracle_module, "SANDBOX_POLICY_VERSION", "drift")
        else:
            monkeypatch.setenv("PATH", "/drift")
        session.run(VALID, output_path=output)
    assert not output.exists()


def test_oracle_session_is_pid_bound_and_non_reentrant(
    synthetic_session_authority: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = synthetic_session_authority
    session = _synthetic_session(authority)
    original_getpid = os.getpid
    with session:
        creator_pid = original_getpid()
        monkeypatch.setattr(oracle_module.os, "getpid", lambda: creator_pid + 1)
        with pytest.raises(OracleError, match="process boundary"):
            session.run(VALID, output_path=authority["artifact_root"] / "pid.json")
        monkeypatch.setattr(oracle_module.os, "getpid", original_getpid)
        assert session._run_lock.acquire(blocking=False)
        try:
            with pytest.raises(OracleError, match="sequential"):
                session.run(VALID, output_path=authority["artifact_root"] / "locked.json")
        finally:
            session._run_lock.release()


def test_oracle_session_git_drift_poisoning_blocks_reuse(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    session = _synthetic_session(authority)
    output = authority["artifact_root"] / "blocked.json"
    with pytest.raises(OracleError, match="Metis checkout identity changed"), session:
        authority["state"]["status"] = " M tooling/package.json"
        with pytest.raises(OracleError, match="Metis checkout identity changed"):
            session.run(VALID, output_path=output)
        with pytest.raises(OracleError, match="poisoned"):
            session.run(VALID, output_path=output)
    assert not output.exists()


def test_oracle_session_full_exit_hash_rejects_metadata_baseline_laundering(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    session = _synthetic_session(authority)
    with pytest.raises(OracleError, match="isolated tooling content changed"), session:
        assert session._snapshot_modules is not None
        target = session._snapshot_modules / "pkg/value.js"
        target.write_bytes(b"evil")
        session._snapshot_roster = oracle_module._directory_metadata_roster(session._snapshot_fd)


def test_oracle_session_full_hash_blocks_publication_after_roster_laundering(
    synthetic_session_authority: dict,
) -> None:
    authority = synthetic_session_authority
    output = authority["artifact_root"] / "must-not-exist.json"
    session = _synthetic_session(authority)
    with pytest.raises(OracleError, match="isolated tooling content changed"), session:
        assert session._snapshot_modules is not None
        target = session._snapshot_modules / "pkg/value.js"
        target.write_bytes(b"evil")
        session._snapshot_roster = oracle_module._directory_metadata_roster(session._snapshot_fd)
        session.run(VALID, output_path=output)
    assert not output.exists()


def test_oracle_session_entry_baseexception_cleans_snapshot_and_descriptors(
    synthetic_session_authority: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = synthetic_session_authority

    def interrupt(_descriptor: int):
        raise KeyboardInterrupt

    monkeypatch.setattr(oracle_module, "_directory_metadata_roster", interrupt)
    session = _synthetic_session(authority)
    with pytest.raises(KeyboardInterrupt):
        session.__enter__()
    snapshots = authority["state"]["snapshots"]
    assert isinstance(snapshots, list) and len(snapshots) == 1
    assert not snapshots[0].exists()
    assert session._root_fd == session._source_modules_fd == -1
    assert session._snapshot_fd == session._snapshot_modules_fd == -1


def write_unqualified_node(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nprintf 'v0.0.0\\n'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_valid_source_has_structural_evidence_and_schema(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    envelope = execute(artifact_tmp, session=reusable_oracle_session)
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


def test_oracle_session_repeat_is_byte_deterministic(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    first = execute(artifact_tmp / "session-one", session=reusable_oracle_session)
    second = execute(artifact_tmp / "session-two", session=reusable_oracle_session)
    assert first == second
    assert oracle_module._canonical(first) == oracle_module._canonical(second)


def test_syntax_error_is_fail_closed(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    result = execute(
        artifact_tmp,
        'metis 0.43\nendpoint play.test as "test" { variant v {\n',
        session=reusable_oracle_session,
    )
    assert result["result"]["status"] == "invalid"
    assert result["result"]["failure"]["kind"] == "parse"
    assert result["result"]["diagnostics"]["parser"]


def test_unknown_reference_is_link_error(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    source = (
        'metis 0.43\nendpoint play.test as "test" {'
        ' take 1 from @video { include where @missing is "x" } }\n'
    )
    result = execute(artifact_tmp, source, session=reusable_oracle_session)
    assert result["result"]["status"] == "invalid"
    assert result["result"]["failure"]["kind"] == "link"
    assert result["result"]["diagnostics"]["link"]


def test_ambiguous_endpoint_is_rejected(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    source = (
        "metis 0.43\n"
        'endpoint play.a as "a" { variant v { empty } }\n'
        'endpoint play.b as "b" { variant v { empty } }\n'
    )
    result = execute(artifact_tmp, source, session=reusable_oracle_session)
    assert result["result"]["failure"]["kind"] == "endpoint_ambiguous"
    assert result["result"]["endpoint"]["count"] == 2


def test_source_mode_validates_a_non_endpoint_document_without_compiling(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    source = "metis 0.43\ncatalog video { fields { title keyword } }\n"
    envelope = execute(
        artifact_tmp,
        source,
        session=reusable_oracle_session,
        execution_mode="source",
    )
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
    with pytest.raises(OracleError, match="executable file"):
        execute(artifact_tmp)


def test_multi_file_workspace_resolves_candidate_dependency(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    candidate = (
        'metis 0.43\nendpoint play.test as "test" {\n'
        '  variant v { take 1 from @video { include where @title is "x" } }\n}\n'
    )
    dependency = "metis 0.43\ncatalog video { fields { title keyword } }\n"
    envelope = execute(
        artifact_tmp,
        candidate,
        session=reusable_oracle_session,
        workspace_sources={"catalogs/video.metis": dependency},
    )
    assert envelope["result"]["status"] == "ok"
    assert envelope["result"]["diagnostics"]["link"] == []


def test_isolated_node_modules_mutation_between_validation_and_execution_is_rejected(
    artifact_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = oracle_module._build_isolated_snapshot

    def attacked(*args: object, **kwargs: object) -> object:
        holder, snapshot, modules, snapshot_runner, snapshot_loader, snapshot_node = original(
            *args, **kwargs
        )
        target = modules / "langium/package.json"
        target.write_text("{}\n", encoding="utf-8")
        return holder, snapshot, modules, snapshot_runner, snapshot_loader, snapshot_node

    monkeypatch.setattr(oracle_module, "_build_isolated_snapshot", attacked)
    with pytest.raises(OracleError, match="changed before execution"):
        execute(artifact_tmp)


def test_forged_runtime_path_is_rejected_even_with_rehashed_envelope(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    envelope = execute(artifact_tmp, session=reusable_oracle_session)
    envelope["result"]["runtime"]["loader_path"] = "snapshot://forged/loader"
    envelope["evidence"]["runtime_identity"]["loader_path"] = "snapshot://forged/loader"
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
        holder, snapshot, modules, snapshot_runner, snapshot_loader, snapshot_node = original(
            *args, **kwargs
        )
        snapshot_runner.write_text("process.stdout.write('{}')\n", encoding="utf-8")
        return holder, snapshot, modules, snapshot_runner, snapshot_loader, snapshot_node

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
    artifact_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    reusable_oracle_session: OracleSession,
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--require=/definitely/missing/preload.js")
    envelope = execute(artifact_tmp, session=reusable_oracle_session)
    assert envelope["result"]["status"] == "ok"
    assert envelope["evidence"]["runtime_identity"]["node_binary_sha256"] == (
        "sha256:" + oracle_module.PINNED_NODE_BINARY_SHA256
    )


def test_metis_checkout_status_is_unchanged_after_isolated_execution(
    artifact_tmp: Path,
    reusable_oracle_session: OracleSession,
) -> None:
    before = subprocess.run(
        ["git", "-C", str(METIS_ROOT), "status", "--porcelain=v1", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    execute(artifact_tmp, session=reusable_oracle_session)
    after = subprocess.run(
        ["git", "-C", str(METIS_ROOT), "status", "--porcelain=v1", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert after == before


def _capsule_fixture(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "capsule"
    files = {
        ".metis-oracle/native_ts_loader.mjs": (
            oracle_module.LOADER_PATH.read_bytes(),
            0o444,
            "loader",
        ),
        ".metis-oracle/runner.ts": (
            oracle_module.RUNNER_PATH.read_bytes(),
            0o444,
            "runner",
        ),
        "tooling/package.json": (b"{}", 0o444, "tooling"),
    }
    rows = []
    for name, (raw, mode, role) in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)
        rows.append(
            {
                "path": name,
                "size": len(raw),
                "mode": mode,
                "sha256": "sha256:" + oracle_module.hashlib.sha256(raw).hexdigest(),
                "role": role,
            }
        )
    rows.sort(key=lambda row: row["path"])
    by_role = {row["role"]: row for row in rows}
    body = {
        "schema_version": 3,
        "capsule_id": "pytest-capsule-v3",
        "revision": oracle_module.PINNED_METIS_REVISION,
        "tree": oracle_module.PINNED_METIS_TREE,
        "language_version": "0.43",
        "loader": {key: by_role["loader"][key] for key in ("path", "sha256", "mode")},
        "runner": {key: by_role["runner"][key] for key in ("path", "sha256", "mode")},
        "tooling": {
            "package_sha256": "sha256:" + oracle_module.PINNED_TOOLING_PACKAGE_SHA256,
            "lock_sha256": "sha256:" + oracle_module.PINNED_TOOLING_LOCK_SHA256,
            "node_modules_sha256": "sha256:" + oracle_module.PINNED_NODE_MODULES_SHA256,
        },
        "counts": {"files": len(rows), "bytes": sum(row["size"] for row in rows)},
        "files": rows,
        "roster_sha256": oracle_module._sha(rows),
    }
    manifest = {**body, "manifest_sha256": oracle_module._sha(body)}
    (root / "capsule.json").write_bytes(oracle_module._canonical(manifest))
    (root / "capsule.json").chmod(0o444)
    for directory in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    root.chmod(0o555)
    return root, manifest


@pytest.mark.parametrize("value", ["bin//node", "bin/./node"])
def test_capsule_path_rejects_noncanonical_lexical_aliases(value: str) -> None:
    with pytest.raises(OracleError, match="forbidden"):
        oracle_module._safe_capsule_path(value, "capsule path")


def test_runtime_capsule_verifier_accepts_only_exact_immutable_roster(tmp_path: Path) -> None:
    root, manifest = _capsule_fixture(tmp_path)
    verified_root, verified = oracle_module.verify_runtime_capsule(
        root, expected_manifest_sha256=manifest["manifest_sha256"]
    )
    assert verified_root == root
    assert verified == manifest


def test_runtime_capsule_rejects_symlink_in_parent_ancestry(tmp_path: Path) -> None:
    root, manifest = _capsule_fixture(tmp_path)
    alias = tmp_path / "capsule-parent-alias"
    alias.symlink_to(root.parent, target_is_directory=True)

    with pytest.raises(OracleError, match="ancestry contains a symlink"):
        oracle_module.verify_runtime_capsule(
            alias / root.name,
            expected_manifest_sha256=manifest["manifest_sha256"],
        )


@pytest.mark.parametrize("attack", ["extra", "mode", "symlink", "revision", "hash"])
def test_runtime_capsule_mutations_fail_closed(tmp_path: Path, attack: str) -> None:
    root, manifest = _capsule_fixture(tmp_path)
    root.chmod(0o755)
    changed = manifest
    if attack == "extra":
        (root / "extra").write_text("x")
        (root / "extra").chmod(0o444)
    elif attack == "mode":
        (root / ".metis-oracle/native_ts_loader.mjs").chmod(0o555)
    elif attack == "symlink":
        (root / "escape").symlink_to(tmp_path / "outside")
    else:
        changed = json.loads(oracle_module._canonical(manifest))
        if attack == "revision":
            changed["revision"] = "0" * 40
        else:
            changed["files"][0]["sha256"] = "sha256:" + "0" * 64
        body = {key: value for key, value in changed.items() if key != "manifest_sha256"}
        changed["manifest_sha256"] = oracle_module._sha(body)
        (root / "capsule.json").chmod(0o644)
        (root / "capsule.json").write_bytes(oracle_module._canonical(changed))
        (root / "capsule.json").chmod(0o444)
    root.chmod(0o555)
    with pytest.raises(OracleError):
        oracle_module.verify_runtime_capsule(
            root,
            expected_manifest_sha256=(
                changed["manifest_sha256"]
                if attack in {"revision", "hash"}
                else manifest["manifest_sha256"]
            ),
        )
    root.chmod(0o755)
    for item in root.rglob("*"):
        if item.is_symlink():
            item.unlink()
        elif item.is_dir():
            item.chmod(0o755)
        else:
            item.chmod(0o644)


@pytest.mark.parametrize("forbidden_role", ["node", "tsx"])
def test_runtime_capsule_rejects_executable_or_legacy_loader_in_trusted_roster(
    tmp_path: Path, forbidden_role: str
) -> None:
    root, manifest = _capsule_fixture(tmp_path)
    root.chmod(0o755)
    forbidden = root / "forbidden" / forbidden_role
    forbidden.parent.mkdir()
    forbidden.write_bytes(b"forbidden")
    forbidden.chmod(0o444)
    row = {
        "path": forbidden.relative_to(root).as_posix(),
        "size": len(b"forbidden"),
        "mode": 0o444,
        "sha256": "sha256:" + hashlib.sha256(b"forbidden").hexdigest(),
        "role": forbidden_role,
    }
    changed = json.loads(oracle_module._canonical(manifest))
    changed["files"].append(row)
    changed["files"].sort(key=lambda item: item["path"])
    changed["counts"] = {
        "files": len(changed["files"]),
        "bytes": sum(item["size"] for item in changed["files"]),
    }
    changed["roster_sha256"] = oracle_module._sha(changed["files"])
    body = {key: value for key, value in changed.items() if key != "manifest_sha256"}
    changed["manifest_sha256"] = oracle_module._sha(body)
    (root / "capsule.json").chmod(0o644)
    (root / "capsule.json").write_bytes(oracle_module._canonical(changed))
    (root / "capsule.json").chmod(0o444)
    forbidden.parent.chmod(0o555)
    root.chmod(0o555)

    with pytest.raises(OracleError, match="file record is invalid"):
        oracle_module.verify_runtime_capsule(
            root,
            expected_manifest_sha256=changed["manifest_sha256"],
        )


def _run_native_loader_probe(
    capsule: Path, runner_source: str
) -> subprocess.CompletedProcess[bytes]:
    loader = capsule / ".metis-oracle/native_ts_loader.mjs"
    runner = capsule / ".metis-oracle/probe.ts"
    loader.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(oracle_module.LOADER_PATH, loader)
    runner.write_text(runner_source, encoding="utf-8")
    return subprocess.run(
        [
            str(PINNED_NODE),
            *oracle_module.LOADER_FLAGS,
            str(loader),
            str(runner),
        ],
        cwd=capsule,
        capture_output=True,
        check=False,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
    )


def test_native_loader_exact_flags_transform_inside_capsule_without_warning(tmp_path: Path) -> None:
    capsule = tmp_path / "native-loader-success"
    capsule.mkdir()
    (capsule / "inside.ts").write_text(
        'export const marker: string = "native-loader-ok";\n', encoding="utf-8"
    )
    completed = _run_native_loader_probe(
        capsule,
        'import { marker } from "../inside.js"; process.stdout.write(marker);\n',
    )
    assert completed.returncode == 0
    assert completed.stdout == b"native-loader-ok"
    assert completed.stderr == b""


@pytest.mark.parametrize("attack", ["absolute", "symlink", "ambient-package"])
def test_native_loader_blocks_escape_and_ambient_resolution(tmp_path: Path, attack: str) -> None:
    capsule = tmp_path / "native-loader-blocked" / "capsule"
    capsule.mkdir(parents=True)
    outside = tmp_path / "native-loader-blocked" / "outside.mjs"
    outside.write_text('export const marker = "outside";\n', encoding="utf-8")
    if attack == "absolute":
        specifier = outside.as_uri()
    elif attack == "symlink":
        (capsule / "escape.mjs").symlink_to(outside)
        specifier = "../escape.mjs"
    else:
        package = capsule.parent / "node_modules" / "ambient-fixture"
        package.mkdir(parents=True)
        (package / "package.json").write_text(
            '{"exports":"./index.mjs","type":"module"}', encoding="utf-8"
        )
        (package / "index.mjs").write_text('export const marker = "ambient";\n', encoding="utf-8")
        specifier = "ambient-fixture"
    completed = _run_native_loader_probe(
        capsule,
        f"import {{ marker }} from {json.dumps(specifier)}; process.stdout.write(marker);\n",
    )
    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"native loader blocked" in completed.stderr


def _complete_mock_capsule_manifest(capsule: Path, manifest: dict) -> None:
    records = []
    for role in ("loader", "runner"):
        path = capsule / manifest[role]["path"]
        path.chmod(0o444)
        raw = path.read_bytes()
        records.append(
            {
                "path": manifest[role]["path"],
                "size": len(raw),
                "mode": 0o444,
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "role": role,
            }
        )
    manifest["files"] = records
    manifest["manifest_sha256"] = "sha256:" + "2" * 64


def _runtime_node_fixture(tmp_path: Path, name: str) -> tuple[Path, Path]:
    runtime = tmp_path / name
    node = runtime / "bin/node"
    node.parent.mkdir(parents=True)
    node.write_bytes(b"#!/bin/sh\nexit 0\n")
    node.chmod(0o755)
    return runtime, node


def _tiny_registered_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    raw = b"node"
    source = tmp_path / "registered-node"
    source.write_bytes(raw)
    source.chmod(0o755)
    monkeypatch.setattr(oracle_module, "PINNED_NODE_BYTES", len(raw))
    monkeypatch.setattr(
        oracle_module,
        "PINNED_NODE_BINARY_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    return source


def test_runtime_preimage_fd_materializer_has_exact_node_only_roster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _tiny_registered_node(tmp_path, monkeypatch)
    invocation = tmp_path / "invocation"
    invocation.mkdir(mode=0o700)
    invocation_fd = os.open(
        invocation,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    root_fd = node_fd = -1
    try:
        root, node, root_fd, node_fd = oracle_module._materialize_runtime_preimage(
            invocation,
            invocation_fd,
            source,
        )
        oracle_module._verify_runtime_preimage_at(root_fd, node_fd)
        assert oracle_module._capsule_preimage_roster_at(root_fd) == (
            {"bin/node"},
            {"bin": 0o555},
        )
        assert oracle_module._directory_fd_matches_path(root_fd, root)
        assert oracle_module._file_fd_matches_path(node_fd, node)
    finally:
        for descriptor in (node_fd, root_fd, invocation_fd):
            if descriptor >= 0:
                os.close(descriptor)


def test_runtime_preimage_fd_materializer_rejects_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _tiny_registered_node(tmp_path, monkeypatch)
    invocation = tmp_path / "invocation"
    invocation.mkdir(mode=0o700)
    invocation_fd = os.open(
        invocation,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    displaced = invocation / "runtime-displaced"
    outside = tmp_path / "runtime-outside"
    outside.mkdir(mode=0o700)
    original_verify = oracle_module._verify_runtime_preimage_at

    def swap_after_verify(root_fd: int, node_fd: int) -> None:
        original_verify(root_fd, node_fd)
        runtime = invocation / "runtime"
        runtime.chmod(0o700)
        runtime.rename(displaced)
        runtime.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(oracle_module, "_verify_runtime_preimage_at", swap_after_verify)
    try:
        with pytest.raises(OracleError, match="namespace changed during materialization"):
            oracle_module._materialize_runtime_preimage(invocation, invocation_fd, source)
        assert list(outside.iterdir()) == []
    finally:
        os.close(invocation_fd)


def test_capsule_command_rejects_replaced_runtime_node_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _tiny_registered_node(tmp_path, monkeypatch)
    invocation = tmp_path / "invocation"
    invocation.mkdir(mode=0o700)
    invocation_fd = os.open(
        invocation,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    root_fd = node_fd = -1
    try:
        runtime, node, root_fd, node_fd = oracle_module._materialize_runtime_preimage(
            invocation,
            invocation_fd,
            source,
        )
        capsule = tmp_path / "capsule-runtime-node-swap"
        (capsule / "work").mkdir(parents=True)
        process = tmp_path / "process-runtime-node-swap"
        process.mkdir()
        runtime.chmod(0o700)
        (runtime / "bin").chmod(0o700)
        displaced = runtime / "bin/node.displaced"
        node.rename(displaced)
        node.write_bytes(b"node")
        node.chmod(0o555)
        runtime.chmod(0o555)
        (runtime / "bin").chmod(0o555)
        with pytest.raises(OracleError, match="opened roots differ"):
            oracle_module._run_capsule_command(
                [str(node)],
                cwd=capsule / "work",
                request_bytes=b"{}",
                stdout_path=process / "stdout",
                stderr_path=process / "stderr",
                timeout=1.0,
                node_executable=node,
                runtime_root=runtime,
                capsule_root=capsule,
                process_root=process,
                runtime_root_fd=root_fd,
                node_executable_fd=node_fd,
            )
    finally:
        for descriptor in (node_fd, root_fd, invocation_fd):
            if descriptor >= 0:
                os.close(descriptor)


@pytest.mark.parametrize("use_directory_fd", [False, True])
def test_capsule_command_stderr_open_failure_closes_stdout_and_retains_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_directory_fd: bool
) -> None:
    capsule = tmp_path / "capsule-stderr-open-failure"
    cwd = capsule / "work"
    cwd.mkdir(parents=True)
    runtime, node = _runtime_node_fixture(tmp_path, "runtime-stderr-open-failure")
    process = tmp_path / "process-stderr-open-failure"
    process.mkdir()
    stream_directory_fd = (
        os.open(process, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        if use_directory_fd
        else None
    )
    original_open = oracle_module.os.open

    def block_stderr_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(os.fspath(path)).name.startswith("stderr-"):
            raise PermissionError("stderr open blocked")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(oracle_module.os, "open", block_stderr_open)
    descriptor_snapshot = _oracle_open_fd_snapshot()
    try:
        for index in range(5):
            with pytest.raises(OracleError, match="capsule runner could not start"):
                oracle_module._run_capsule_command(
                    [str(node)],
                    cwd=cwd,
                    request_bytes=b"{}",
                    stdout_path=process / f"stdout-{index}",
                    stderr_path=process / f"stderr-{index}",
                    timeout=1.0,
                    node_executable=node,
                    runtime_root=runtime,
                    capsule_root=capsule,
                    process_root=process,
                    stream_directory_fd=stream_directory_fd,
                )
            assert _oracle_open_fd_snapshot() == descriptor_snapshot
            assert sorted(path.name for path in process.iterdir()) == [
                f"stdout-{retained}" for retained in range(index + 1)
            ]
            assert all(path.read_bytes() == b"" for path in process.iterdir())
    finally:
        if stream_directory_fd is not None:
            os.close(stream_directory_fd)


@pytest.mark.parametrize("use_directory_fd", [False, True])
def test_capsule_command_stderr_open_race_preserves_replacement_and_owned_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_directory_fd: bool
) -> None:
    capsule = tmp_path / f"capsule-stderr-race-{use_directory_fd}"
    cwd = capsule / "work"
    cwd.mkdir(parents=True)
    runtime, node = _runtime_node_fixture(
        tmp_path,
        f"runtime-stderr-race-{use_directory_fd}",
    )
    process = tmp_path / f"process-stderr-race-{use_directory_fd}"
    process.mkdir()
    stdout_path = process / "stdout-race"
    stderr_path = process / "stderr-race"
    displaced = process / "stdout-owned-displaced"
    stream_directory_fd = (
        os.open(process, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        if use_directory_fd
        else None
    )
    original_open = oracle_module.os.open
    original_rename = oracle_module.os.rename

    def race_stderr_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(os.fspath(path)).name == stderr_path.name:
            if dir_fd is None:
                original_rename(stdout_path, displaced)
                replacement_fd = original_open(
                    stdout_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                )
            else:
                original_rename(
                    stdout_path.name,
                    displaced.name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                )
                replacement_fd = original_open(
                    stdout_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=dir_fd,
                )
            os.write(replacement_fd, b"replacement-preserve-exact")
            os.close(replacement_fd)
            raise PermissionError("stderr open blocked after stdout displacement")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(oracle_module.os, "open", race_stderr_open)
    descriptor_snapshot = _oracle_open_fd_snapshot()
    try:
        with pytest.raises(OracleError, match="capsule runner could not start"):
            oracle_module._run_capsule_command(
                [str(node)],
                cwd=cwd,
                request_bytes=b"{}",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=1.0,
                node_executable=node,
                runtime_root=runtime,
                capsule_root=capsule,
                process_root=process,
                stream_directory_fd=stream_directory_fd,
            )
        assert _oracle_open_fd_snapshot() == descriptor_snapshot
        assert stdout_path.read_bytes() == b"replacement-preserve-exact"
        assert displaced.read_bytes() == b""
    finally:
        if stream_directory_fd is not None:
            os.close(stream_directory_fd)


@pytest.mark.parametrize("use_directory_fd", [False, True])
def test_capsule_command_keyboard_interrupt_reaps_group_and_retains_partial_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_directory_fd: bool
) -> None:
    capsule = tmp_path / f"capsule-interrupt-{use_directory_fd}"
    cwd = capsule / "work"
    cwd.mkdir(parents=True)
    runtime, node = _runtime_node_fixture(tmp_path, f"runtime-interrupt-{use_directory_fd}")
    process_root = tmp_path / f"process-interrupt-{use_directory_fd}"
    process_root.mkdir()
    stdout_path = process_root / "stdout-interrupt"
    stderr_path = process_root / "stderr-interrupt"
    stream_directory_fd = (
        os.open(process_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        if use_directory_fd
        else None
    )
    descriptor_snapshot = _oracle_open_fd_snapshot()
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []

    def interrupting_popen(*_args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(
            ["/bin/sleep", "30"],
            stdin=subprocess.PIPE,
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=True,
        )

        def interrupt(*_args: object, **_kwargs: object) -> tuple[bytes, bytes]:
            assert process.stdin is not None
            process.stdin.close()
            process.stdin = None
            raise KeyboardInterrupt

        process.communicate = interrupt  # type: ignore[method-assign]
        spawned.append(process)
        return process

    monkeypatch.setattr(oracle_module.subprocess, "Popen", interrupting_popen)
    try:
        with pytest.raises(KeyboardInterrupt):
            oracle_module._run_capsule_command(
                [str(node)],
                cwd=cwd,
                request_bytes=b"{}",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=5.0,
                node_executable=node,
                runtime_root=runtime,
                capsule_root=capsule,
                process_root=process_root,
                stream_directory_fd=stream_directory_fd,
            )
        assert len(spawned) == 1
        assert _oracle_open_fd_snapshot() == descriptor_snapshot
        assert stdout_path.read_bytes() == b""
        assert stderr_path.read_bytes() == b""
        pid = spawned[0].pid
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
    finally:
        for process in spawned:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, 9)
            with contextlib.suppress(ProcessLookupError, subprocess.TimeoutExpired):
                process.wait(timeout=2)
        if stream_directory_fd is not None:
            os.close(stream_directory_fd)


def test_capsule_interior_never_calls_live_checkout_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule-low-level"
    for name, raw in {
        "bin/node": b"node",
        ".metis-oracle/native_ts_loader.mjs": b"loader",
        ".metis-oracle/runner.ts": b"runner",
    }.items():
        path = capsule / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": ".metis-oracle/native_ts_loader.mjs"},
        "runner": {"path": ".metis-oracle/runner.ts"},
    }
    _complete_mock_capsule_manifest(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    monkeypatch.setattr(
        oracle_module,
        "_build_isolated_snapshot",
        lambda *args, **kwargs: pytest.fail("live snapshot builder called"),
    )
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    runtime = oracle_module._runtime_identity_policy(
        oracle_module.PINNED_METIS_REVISION,
        oracle_module.PINNED_METIS_TREE,
        execution_policy_sha256=oracle_module.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
    )
    ir_value = {"name": "play.capsule"}
    result = {
        "schema_version": 1,
        "status": "ok",
        "endpoint": {"name": "play.capsule", "count": 1},
        "diagnostics": {"parser": [], "link": [], "validation": [], "all": []},
        "ast": {"inventory": {}, "signature": oracle_module._sha({})},
        "ir": {"value": ir_value, "signature": oracle_module._sha(ir_value)},
        "toolchain": {
            "revision": oracle_module.PINNED_METIS_REVISION,
            "tree": oracle_module.PINNED_METIS_TREE,
            "language_version": "0.43",
        },
        "runtime": runtime,
        "failure": None,
    }
    completed = oracle_module.subprocess.CompletedProcess(
        args=[], returncode=0, stdout=oracle_module._canonical(result), stderr=b""
    )
    monkeypatch.setattr(oracle_module, "_run_capsule_command", lambda *args, **kwargs: completed)
    process = tmp_path / "process"
    process.mkdir()
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "request": semantic,
    }
    envelope = oracle_module.run_oracle_from_capsule(
        request,
        capsule_root=capsule,
        process_root=process,
        output_path=process / "output.json",
    )
    assert envelope["capsule_manifest_sha256"] == request["capsule_manifest_sha256"]
    assert oracle_module.normalize_capsule_oracle_envelope(envelope).get("run_nonce") is None


@pytest.mark.parametrize(
    "field",
    ["execution_id", "run_nonce", "capsule_manifest_sha256"],
)
def test_capsule_oracle_envelope_non_string_identity_is_typed_blocked(field: str) -> None:
    body = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "request_sha256": "sha256:" + "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "execution_policy": dict(oracle_module.CAPSULE_EXECUTION_POLICY),
        "oracle_envelope": {},
    }
    envelope = {
        **body,
        "run_nonce": "3" * 64,
        "manifest_sha256": oracle_module._sha(body),
    }
    envelope[field] = 7

    with pytest.raises(oracle_module.OracleError, match="envelope identity is invalid"):
        oracle_module.verify_capsule_oracle_envelope(envelope)


def test_capsule_interior_executes_captured_preimage_during_runner_swap_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "public-capsule-preimage"
    node = capsule / "bin/node"
    loader = capsule / "tooling/loader.mjs"
    runner = capsule / "runner.mjs"
    node.parent.mkdir(parents=True)
    loader.parent.mkdir(parents=True)
    shutil.copy2(PINNED_NODE, node)
    original = (
        "import fs from 'node:fs';let writeDenied=false;"
        "try{fs.writeFileSync(new URL(import.meta.url),'mutated')}"
        "catch(error){writeDenied=error.code==='EPERM'||error.code==='EACCES'};"
        "process.stdout.write(JSON.stringify({ast:{inventory:{}},diagnostics:{},"
        "ir:{value:null},marker:'original',writeDenied}));"
    )
    loader.write_text("export {};", encoding="utf-8")
    runner.write_text(original, encoding="utf-8")
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": "tooling/loader.mjs"},
        "runner": {"path": "runner.mjs"},
    }
    _complete_mock_capsule_manifest(capsule, manifest)
    measured = oracle_module._capture_runtime_capsule_contents(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    real_materialize = oracle_module._materialize_runtime_capsule_preimage
    swapped = False

    def swap_after_capture(
        invocation: Path,
        invocation_fd: int,
        supplied_manifest: dict,
        contents: dict[str, bytes],
    ) -> tuple[Path, int]:
        nonlocal swapped
        assert contents == measured
        runner.chmod(0o644)
        runner.write_text(
            "process.stdout.write(JSON.stringify({ast:{inventory:{}},diagnostics:{},"
            "ir:{value:null},marker:'swapped',writeDenied:false}));",
            encoding="utf-8",
        )
        runner.chmod(0o444)
        swapped = True
        return real_materialize(invocation, invocation_fd, supplied_manifest, contents)

    monkeypatch.setattr(
        oracle_module,
        "_materialize_runtime_capsule_preimage",
        swap_after_capture,
    )
    monkeypatch.setattr(oracle_module, "_check_response", lambda result, *args, **kwargs: result)
    monkeypatch.setattr(oracle_module, "verify_oracle_envelope", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        oracle_module,
        "verify_capsule_oracle_envelope",
        lambda *args, **kwargs: {},
    )
    process = tmp_path / "public-process-preimage"
    process.mkdir()
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": manifest["manifest_sha256"],
        "request": semantic,
    }

    envelope = oracle_module.run_oracle_from_capsule(
        request,
        capsule_root=capsule,
        process_root=process,
        output_path=process / "output.json",
        timeout=5,
    )

    runner.chmod(0o644)
    runner.write_text(original, encoding="utf-8")
    runner.chmod(0o444)
    restored = oracle_module._capture_runtime_capsule_contents(capsule, manifest)
    preimages = list((process / "invocations").glob("*/capsule-*"))
    assert len(preimages) == 1
    oracle_module._verify_runtime_capsule_preimage(preimages[0], manifest, measured)
    result = envelope["oracle_envelope"]["result"]
    assert swapped
    assert result["marker"] == "original"
    assert result["writeDenied"] is True
    assert restored == measured


def test_capsule_interior_invocation_creation_rejects_preexisting_parent_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule-invocation-symlink"
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": ".metis-oracle/native_ts_loader.mjs"},
        "runner": {"path": ".metis-oracle/runner.ts"},
    }
    for relative in (item["path"] for item in manifest.values()):
        target = capsule / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    _complete_mock_capsule_manifest(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    process = tmp_path / "process-invocation-symlink"
    process.mkdir()
    outside = tmp_path / "outside-invocation-symlink"
    outside.mkdir()
    (process / "invocations").symlink_to(outside, target_is_directory=True)
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "request": semantic,
    }

    with pytest.raises(OracleError, match="created securely"):
        oracle_module.run_oracle_from_capsule(
            request,
            capsule_root=capsule,
            process_root=process,
            output_path=process / "output.json",
        )
    assert list(outside.iterdir()) == []


def test_capsule_interior_materialization_blocks_timed_invocation_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule-invocation-timed-swap"
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": ".metis-oracle/native_ts_loader.mjs"},
        "runner": {"path": ".metis-oracle/runner.ts"},
    }
    for relative in (item["path"] for item in manifest.values()):
        target = capsule / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    _complete_mock_capsule_manifest(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    process = tmp_path / "process-invocation-timed-swap"
    process.mkdir()
    outside = tmp_path / "outside-invocation-timed-swap"
    outside.mkdir()
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": manifest["manifest_sha256"],
        "request": semantic,
    }
    invocation = process / "invocations" / "candidate-f1.author-1111111111111111"
    displaced = process / "displaced-invocation"
    real_write = oracle_module._write_capsule_preimage_file_at
    swapped = False

    def swap_then_write(directory_fd: int, name: str, raw: bytes, mode: int) -> None:
        nonlocal swapped
        if not swapped:
            invocation.rename(displaced)
            invocation.symlink_to(outside, target_is_directory=True)
            swapped = True
        real_write(directory_fd, name, raw, mode)

    monkeypatch.setattr(oracle_module, "_write_capsule_preimage_file_at", swap_then_write)

    with pytest.raises(OracleError, match="namespace changed during materialization"):
        oracle_module.run_oracle_from_capsule(
            request,
            capsule_root=capsule,
            process_root=process,
            output_path=process / "output.json",
        )
    assert swapped
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("mode", [0o777, 0o555])
def test_capsule_interior_invocation_creation_rejects_nonprivate_namespace_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
    mode: int,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule-invocation-mode"
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": ".metis-oracle/native_ts_loader.mjs"},
        "runner": {"path": ".metis-oracle/runner.ts"},
    }
    for relative in (item["path"] for item in manifest.values()):
        target = capsule / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    _complete_mock_capsule_manifest(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    process = tmp_path / "process-invocation-mode"
    process.mkdir()
    namespace = process / "invocations"
    namespace.mkdir()
    namespace.chmod(mode)
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "request": semantic,
    }

    with pytest.raises(OracleError, match="namespace is not a private directory"):
        oracle_module.run_oracle_from_capsule(
            request,
            capsule_root=capsule,
            process_root=process,
            output_path=process / "output.json",
        )


def test_capsule_interior_output_parent_timed_symlink_swap_writes_nothing_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule-output-swap"
    manifest = {
        "node": {"path": "bin/node"},
        "loader": {"path": ".metis-oracle/native_ts_loader.mjs"},
        "runner": {"path": ".metis-oracle/runner.ts"},
    }
    for relative in (item["path"] for item in manifest.values()):
        target = capsule / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    _complete_mock_capsule_manifest(capsule, manifest)
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (capsule, manifest),
    )
    process = tmp_path / "process-output-swap"
    process.mkdir()
    output_parent = process / "results"
    output_parent.mkdir(mode=0o700)
    outside = tmp_path / "outside-output-swap"
    outside.mkdir()
    displaced = process / "displaced-results"
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "request": semantic,
    }
    result = {
        "diagnostics": {},
        "ast": {"inventory": {}},
        "ir": {"value": None},
    }

    def swap_output_parent(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        output_parent.rename(displaced)
        output_parent.symlink_to(outside, target_is_directory=True)
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=oracle_module._canonical(result), stderr=b""
        )

    monkeypatch.setattr(oracle_module, "_run_capsule_command", swap_output_parent)
    monkeypatch.setattr(oracle_module, "_check_response", lambda *args, **kwargs: result)
    monkeypatch.setattr(oracle_module, "verify_oracle_envelope", lambda *args, **kwargs: {})
    monkeypatch.setattr(oracle_module, "verify_capsule_oracle_envelope", lambda *args, **kwargs: {})

    with pytest.raises(OracleError, match="opened securely"):
        oracle_module.run_oracle_from_capsule(
            request,
            capsule_root=capsule,
            process_root=process,
            output_path=output_parent / "output.json",
        )
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("field", ["process", "output"])
def test_capsule_interior_boundary_rejects_parent_symlink_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_interior_test_seam: None,
    field: str,
) -> None:
    del capsule_interior_test_seam
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    process = tmp_path / "process"
    process.mkdir()
    semantic = oracle_module.build_oracle_request(
        'metis 0.43\nendpoint play.capsule as "capsule" { variant v { empty } }\n',
        endpoint="play.capsule",
    )
    request = {
        "schema_version": 3,
        "protocol": oracle_module.CAPSULE_PROTOCOL,
        "execution_id": "candidate-f1.author",
        "run_nonce": "1" * 64,
        "capsule_manifest_sha256": "sha256:" + "2" * 64,
        "request": semantic,
    }
    monkeypatch.setattr(
        oracle_module,
        "verify_runtime_capsule",
        lambda *args, **kwargs: (
            capsule,
            {
                "node": {"path": "bin/node"},
                "loader": {"path": "tooling/loader.mjs"},
                "runner": {"path": "runner.ts"},
            },
        ),
    )
    if field == "process":
        alias = tmp_path / "process-parent-alias"
        alias.symlink_to(process.parent, target_is_directory=True)
        supplied_process = alias / process.name
        supplied_output = process / "output.json"
    else:
        output_parent = process / "real-output"
        output_parent.mkdir()
        alias = process / "output-parent-alias"
        alias.symlink_to(output_parent, target_is_directory=True)
        supplied_process = process
        supplied_output = alias / "output.json"

    with pytest.raises(OracleError, match="ancestry contains a symlink"):
        oracle_module.run_oracle_from_capsule(
            request,
            capsule_root=capsule,
            process_root=supplied_process,
            output_path=supplied_output,
        )
