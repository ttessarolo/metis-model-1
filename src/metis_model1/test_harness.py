"""Isolated local authorities for the repository's integration-test gate.

The source Metis checkout is an object provider only.  Tests execute against
separate temporary clean repositories at the historical oracle pin and the
current Brain toolchain pin, so concurrent work in the source checkout cannot
weaken or spuriously fail either contract.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from metis_model1 import (
    brain_toolchain_pin,
    grammar_stdlib_oracle,
    oracles,
    pytest_shard_ledger,
)
from metis_model1 import catalog_maintenance_pin as catalog_pin

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARD_LEDGER_PLUGIN = "metis_model1.pytest_shard_ledger"
SHARDED_WORKERS = 2
SERIAL_TEST_FILES = frozenset(
    {
        "tests/test_brain_flash_runtime.py",
        "tests/test_brain_hard_qualification.py",
        "tests/test_brain_mlx_runtime.py",
        "tests/test_brain_runner_schema2.py",
        "tests/test_brain_server.py",
        "tests/test_brain_session_isolation.py",
        "tests/test_brain_structural_freeform_continuation.py",
        "tests/test_brain_structural_provisional_replay.py",
        "tests/test_brain_turns.py",
        "tests/test_catalog_retrieval_refresh.py",
        "tests/test_frontier_egress_boundary.py",
        "tests/test_grammar_stdlib_coverage.py",
        "tests/test_oracles.py",
        "tests/test_test_harness_sharding.py",
        "tests/test_video_semantics_private_runner.py",
        "tests/test_video_source_extraction.py",
        "tests/test_w3_bridge_gate.py",
        "tests/test_w3_phase_b_launcher.py",
        "tests/test_w3_phase_b_materializer.py",
        "tests/test_w3_qualifier.py",
    }
)
_SHARDED_PYTEST_ARGS = frozenset({"-q", "-qq", "-v", "-vv"})


class TestHarnessError(RuntimeError):
    """Raised when the isolated test authority cannot be trusted."""


@dataclass(frozen=True)
class _ShardPlan:
    canonical: tuple[str, ...]
    parallel_files: tuple[tuple[str, ...], ...]
    parallel_nodeids: tuple[tuple[str, ...], ...]
    serial_files: tuple[str, ...]
    serial_nodeids: tuple[str, ...]


@dataclass(frozen=True)
class _ShardExecution:
    shard_id: str
    expected_nodeids: tuple[str, ...]
    returncode: int
    ledger: pytest_shard_ledger.ShardLedger


def _git_text(root: Path, *args: str) -> str:
    value = catalog_pin._run_git(root, *args)
    if not isinstance(value, str):
        raise TestHarnessError("Git returned a non-text identity")
    return value


def _common_objects_directory(root: Path) -> Path:
    raw = _git_text(root, "rev-parse", "--git-common-dir")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    objects = (candidate.resolve(strict=True) / "objects").resolve(strict=True)
    if not objects.is_dir():
        raise TestHarnessError("Metis Git object authority is unavailable")
    return objects


def _write_alternate(path: Path, objects: Path) -> None:
    if "\n" in str(objects) or "\r" in str(objects):
        raise TestHarnessError("Metis Git object authority path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        raw = (str(objects) + "\n").encode("utf-8")
        if os.write(descriptor, raw) != len(raw):
            raise TestHarnessError("cannot bind isolated Git objects")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular_file(path: Path, *, expected_mode: int, label: str) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        raw = os.read(descriptor, 4097)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise TestHarnessError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact immutable stat identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != expected_mode
        or before.st_nlink != 1
        or before.st_size > 4096
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or len(raw) != before.st_size
    ):
        raise TestHarnessError(f"{label} is not a stable private file")
    return raw


def _isolated_authority_identity(
    root: Path,
    *,
    revision: str,
    tree: str,
    modules_sha256: str,
    objects: Path,
) -> tuple[str, str, str, str, str]:
    expected_alternate = (str(objects) + "\n").encode("utf-8")
    observed_alternate = _read_regular_file(
        root / ".git/objects/info/alternates",
        expected_mode=0o600,
        label="isolated Git alternate",
    )
    if observed_alternate != expected_alternate:
        raise TestHarnessError("isolated Metis authority changed during tests")
    observed_revision = _git_text(root, "rev-parse", "HEAD")
    observed_tree = _git_text(root, "rev-parse", "HEAD^{tree}")
    observed_branch = _git_text(root, "rev-parse", "--abbrev-ref", "HEAD")
    observed_status = _git_text(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)tooling/node_modules",
    )
    isolated_root = root.resolve(strict=True)
    modules = (root / "tooling/node_modules").resolve(strict=True)
    if not modules.is_relative_to(isolated_root):
        raise TestHarnessError("isolated tooling runtime escapes its authority")
    oracles._validate_tree_symlinks(modules, "isolated tooling runtime")
    observed_modules = catalog_pin._node_modules_sha256(modules)
    if (
        observed_revision != revision
        or observed_tree != tree
        or observed_branch != "HEAD"
        or observed_status
        or observed_modules != modules_sha256
    ):
        raise TestHarnessError("isolated Metis authority changed during tests")
    return (
        observed_revision,
        observed_tree,
        observed_branch,
        observed_modules,
        observed_alternate.decode("utf-8"),
    )


def _authority_identity(
    root: Path,
    *,
    revision: str,
    tree: str,
    modules_sha256: str,
    runtime_modules: Path | None = None,
) -> tuple[str, str, str]:
    observed_revision = _git_text(root, "rev-parse", revision)
    observed_tree = _git_text(root, "rev-parse", f"{revision}^{{tree}}")
    modules = Path(runtime_modules or root / "tooling/node_modules").resolve(strict=True)
    observed_modules = catalog_pin._node_modules_sha256(modules)
    if observed_revision != revision or observed_tree != tree or observed_modules != modules_sha256:
        raise TestHarnessError("source Git/runtime authority differs from the test pin")
    return observed_revision, observed_tree, observed_modules


def _source_worktree_status(root: Path) -> str:
    """Return Git-visible source drift; ignored caches and nested worktrees are not authority."""

    return _git_text(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)tooling/node_modules",
    )


@contextmanager
def isolated_metis_test_authority(
    source_root: Path,
    *,
    revision: str = oracles.PINNED_METIS_REVISION,
    tree: str = oracles.PINNED_METIS_TREE,
    modules_sha256: str = oracles.PINNED_NODE_MODULES_SHA256,
    runtime_modules: Path | None = None,
) -> Iterator[Path]:
    """Materialize a clean detached authority without writing the source repo."""

    try:
        root = Path(source_root).resolve(strict=True)
        if not root.is_dir():
            raise TestHarnessError("Metis source authority is not a directory")
        before = _authority_identity(
            root,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
            runtime_modules=runtime_modules,
        )
        if _source_worktree_status(root):
            raise TestHarnessError("source worktree is not clean")
        archive = catalog_pin._run_git(
            root,
            "archive",
            "--format=tar",
            revision,
            text=False,
        )
        if not isinstance(archive, bytes):
            raise TestHarnessError("pinned Git archive is unavailable")
        objects = _common_objects_directory(root)
        source_modules = Path(runtime_modules or root / "tooling/node_modules").resolve(strict=True)

        try:
            with tempfile.TemporaryDirectory(prefix="metis-model1-test-authority-") as temporary:
                isolated = Path(temporary) / "metis"
                isolated.mkdir(mode=0o700)
                catalog_pin._safe_extract_archive(archive, isolated)
                if catalog_pin._node_modules_sha256(source_modules) != modules_sha256:
                    raise TestHarnessError("tooling runtime changed before copy")
                copied_modules = isolated / "tooling/node_modules"
                if copied_modules.exists() or copied_modules.is_symlink():
                    raise TestHarnessError("pinned Git archive unexpectedly contains node_modules")
                shutil.copytree(source_modules, copied_modules, symlinks=True)
                if (
                    catalog_pin._node_modules_sha256(copied_modules) != modules_sha256
                    or catalog_pin._node_modules_sha256(source_modules) != modules_sha256
                ):
                    raise TestHarnessError("copied tooling runtime differs from the pin")

                _git_text(isolated, "init", "--quiet")
                _write_alternate(isolated / ".git/objects/info/alternates", objects)
                _git_text(isolated, "update-ref", "--no-deref", "HEAD", revision)
                _git_text(isolated, "read-tree", revision)
                isolated_before = _isolated_authority_identity(
                    isolated,
                    revision=revision,
                    tree=tree,
                    modules_sha256=modules_sha256,
                    objects=objects,
                )
                try:
                    yield isolated
                finally:
                    isolated_after = _isolated_authority_identity(
                        isolated,
                        revision=revision,
                        tree=tree,
                        modules_sha256=modules_sha256,
                        objects=objects,
                    )
                    if isolated_after != isolated_before:
                        raise TestHarnessError("isolated Metis authority changed during tests")
        finally:
            try:
                after = _authority_identity(
                    root,
                    revision=revision,
                    tree=tree,
                    modules_sha256=modules_sha256,
                    runtime_modules=runtime_modules,
                )
            except TestHarnessError as error:
                raise TestHarnessError(
                    "source Git/runtime authority changed during tests"
                ) from error
            if after != before:
                raise TestHarnessError("source Git/runtime authority changed during tests")
            if _source_worktree_status(root):
                raise TestHarnessError("source worktree became dirty during tests")
    except (catalog_pin.CatalogMaintenancePinError, OSError, shutil.Error) as error:
        raise TestHarnessError("cannot construct isolated Metis test authority") from error


def _pytest_environment(
    *,
    isolated: Path,
    brain_isolated: Path,
    node: Path,
) -> dict[str, str]:
    environment = dict(os.environ)
    for key in tuple(environment):
        if (
            key.startswith("GIT_")
            or key.startswith("PYTEST_")
            or key.startswith("METIS_MODEL1_")
            or key
            in {
                "NODE_OPTIONS",
                "PYTHONHOME",
                "PYTHONPATH",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
            }
        ):
            environment.pop(key, None)
    environment.update(
        {
            oracles.NODE_RUNTIME_ENV: str(node),
            "METIS_MODEL1_METIS_ROOT": str(isolated),
            "METIS_MODEL1_BRAIN_METIS_ROOT": str(brain_isolated),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    return environment


def _validate_sharded_pytest_args(pytest_args: Sequence[str]) -> tuple[str, ...]:
    arguments = tuple(pytest_args)
    if any(type(item) is not str or item not in _SHARDED_PYTEST_ARGS for item in arguments):
        raise TestHarnessError(
            "sharded tests accept only verbosity flags; selection must remain repository-wide"
        )
    return arguments


def _private_shard_directory(root: Path, name: str) -> Path:
    if not name or "/" in name or name in {".", ".."}:
        raise TestHarnessError("shard directory name is invalid")
    path = root / name
    try:
        path.mkdir(mode=0o700)
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise TestHarnessError("cannot create private shard directory") from error
    if (
        resolved != path
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise TestHarnessError("shard directory is not private")
    return resolved


def _test_file(nodeid: str) -> str:
    if type(nodeid) is not str or not nodeid or "\x00" in nodeid:
        raise TestHarnessError("collected pytest nodeid is invalid")
    relative = nodeid.split("::", 1)[0]
    path = Path(relative)
    if (
        path.is_absolute()
        or path.as_posix() != relative
        or len(path.parts) != 2
        or path.parts[0] != "tests"
        or path.suffix != ".py"
        or not path.name.startswith("test_")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise TestHarnessError("sharded collection contains a non-test-file nodeid")
    return relative


def _partition_collection(nodeids: Sequence[str], *, workers: int) -> _ShardPlan:
    canonical = tuple(nodeids)
    if workers != SHARDED_WORKERS or not canonical or len(set(canonical)) != len(canonical):
        raise TestHarnessError("canonical pytest collection is invalid")
    file_order: list[str] = []
    counts: Counter[str] = Counter()
    for nodeid in canonical:
        filename = _test_file(nodeid)
        if filename not in counts:
            file_order.append(filename)
        counts[filename] += 1
    missing_quarantine = SERIAL_TEST_FILES - set(file_order)
    if missing_quarantine:
        raise TestHarnessError("serial quarantine differs from the full-suite collection")

    serial_files = tuple(filename for filename in file_order if filename in SERIAL_TEST_FILES)
    safe_files = tuple(filename for filename in file_order if filename not in SERIAL_TEST_FILES)
    if len(safe_files) < workers or not serial_files:
        raise TestHarnessError("full-suite shard roster is incomplete")
    file_shards: list[list[str]] = [[] for _ in range(workers)]
    loads = [0] * workers
    for filename in safe_files:
        target = min(range(workers), key=lambda index: (loads[index], index))
        file_shards[target].append(filename)
        loads[target] += counts[filename]
    file_owner = {filename: index for index, shard in enumerate(file_shards) for filename in shard}
    parallel_nodeids = tuple(
        tuple(nodeid for nodeid in canonical if file_owner.get(_test_file(nodeid)) == index)
        for index in range(workers)
    )
    serial_nodeids = tuple(
        nodeid for nodeid in canonical if _test_file(nodeid) in SERIAL_TEST_FILES
    )
    combined = (*parallel_nodeids, serial_nodeids)
    flattened = tuple(nodeid for shard in combined for nodeid in shard)
    if len(flattened) != len(canonical) or set(flattened) != set(canonical):
        raise TestHarnessError("pytest shard partition has gaps or duplicates")
    return _ShardPlan(
        canonical=canonical,
        parallel_files=tuple(tuple(shard) for shard in file_shards),
        parallel_nodeids=parallel_nodeids,
        serial_files=serial_files,
        serial_nodeids=serial_nodeids,
    )


@contextmanager
def _isolated_authority_pair(
    *,
    source_root: Path,
    oracle_node_modules: Path | None,
    brain_receipt: dict[str, object],
) -> Iterator[tuple[Path, Path]]:
    identity = brain_receipt.get("identity")
    node_modules_sha256 = getattr(identity, "node_modules_sha256", None)
    revision = brain_receipt.get("revision")
    tree = brain_receipt.get("tree")
    if (
        type(revision) is not str
        or type(tree) is not str
        or type(node_modules_sha256) is not str
        or not node_modules_sha256.removeprefix("sha256:")
    ):
        raise TestHarnessError("Metis Brain authority identity is invalid")
    with (
        isolated_metis_test_authority(
            source_root,
            runtime_modules=oracle_node_modules,
        ) as isolated,
        isolated_metis_test_authority(
            source_root,
            revision=revision,
            tree=tree,
            modules_sha256=node_modules_sha256.removeprefix("sha256:"),
        ) as brain_isolated,
    ):
        oracles.validate_pinned_metis(isolated)
        grammar_stdlib_oracle.validate_grammar_stdlib_pin(metis_root=isolated)
        yield isolated, brain_isolated


def _pytest_ledger_command(
    *,
    shard_id: str,
    ledger_path: Path,
    basetemp: Path,
    pytest_args: Sequence[str],
    collect_only: bool,
    files: Sequence[str] = (),
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        SHARD_LEDGER_PLUGIN,
        "-p",
        "no:cacheprovider",
        f"--metis-shard-ledger={ledger_path}",
        f"--metis-shard-id={shard_id}",
        f"--basetemp={basetemp}",
        *pytest_args,
    ]
    if collect_only:
        command.append("--collect-only")
    command.extend(files)
    return command


def _execute_ledger_pytest(
    *,
    shard_id: str,
    directory: Path,
    isolated: Path,
    brain_isolated: Path,
    node: Path,
    pytest_args: Sequence[str],
    collect_only: bool,
    files: Sequence[str] = (),
) -> _ShardExecution:
    ledger_path = directory / "ledger.json"
    basetemp = _private_shard_directory(directory, "pytest-tmp")
    completed = subprocess.run(
        _pytest_ledger_command(
            shard_id=shard_id,
            ledger_path=ledger_path,
            basetemp=basetemp,
            pytest_args=pytest_args,
            collect_only=collect_only,
            files=files,
        ),
        cwd=PROJECT_ROOT,
        env=_pytest_environment(
            isolated=isolated,
            brain_isolated=brain_isolated,
            node=node,
        ),
        check=False,
    )
    try:
        ledger = pytest_shard_ledger.read_private_ledger(
            ledger_path,
            expected_shard_id=shard_id,
            expected_mode="collect" if collect_only else "execute",
        )
    except pytest_shard_ledger.ShardLedgerError as error:
        raise TestHarnessError("pytest shard ledger is unavailable or invalid") from error
    if ledger.exitstatus != completed.returncode:
        raise TestHarnessError("pytest shard process and ledger exit status differ")
    return _ShardExecution(
        shard_id=shard_id,
        expected_nodeids=ledger.collected_nodeids,
        returncode=completed.returncode,
        ledger=ledger,
    )


def _node_stat_identity(node: Path) -> tuple[int, int, int, int, int, int, int]:
    metadata = node.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _execute_test_shard(
    *,
    shard_id: str,
    directory: Path,
    files: Sequence[str],
    expected_nodeids: tuple[str, ...],
    source_root: Path,
    oracle_node_modules: Path | None,
    brain_receipt: dict[str, object],
    node: Path,
    pytest_args: Sequence[str],
) -> _ShardExecution:
    with _isolated_authority_pair(
        source_root=source_root,
        oracle_node_modules=oracle_node_modules,
        brain_receipt=brain_receipt,
    ) as (isolated, brain_isolated):
        return _execute_prepared_test_shard(
            shard_id=shard_id,
            directory=directory,
            files=files,
            expected_nodeids=expected_nodeids,
            isolated=isolated,
            brain_isolated=brain_isolated,
            node=node,
            pytest_args=pytest_args,
        )


def _execute_prepared_test_shard(
    *,
    shard_id: str,
    directory: Path,
    files: Sequence[str],
    expected_nodeids: tuple[str, ...],
    isolated: Path,
    brain_isolated: Path,
    node: Path,
    pytest_args: Sequence[str],
) -> _ShardExecution:
    execution = _execute_ledger_pytest(
        shard_id=shard_id,
        directory=directory,
        isolated=isolated,
        brain_isolated=brain_isolated,
        node=node,
        pytest_args=pytest_args,
        collect_only=False,
        files=files,
    )
    if execution.ledger.collected_nodeids != expected_nodeids:
        raise TestHarnessError("pytest shard collection drifted from the canonical roster")
    observed_nodeids = tuple(item.nodeid for item in execution.ledger.outcomes)
    if observed_nodeids != expected_nodeids:
        raise TestHarnessError("pytest shard outcomes contain gaps or differ in order")
    return _ShardExecution(
        shard_id=execution.shard_id,
        expected_nodeids=expected_nodeids,
        returncode=execution.returncode,
        ledger=execution.ledger,
    )


def _aggregate_shards(plan: _ShardPlan, executions: Sequence[_ShardExecution]) -> int:
    expected_ids = tuple(f"parallel-{index}" for index in range(len(plan.parallel_files))) + (
        "serial-quarantine",
    )
    by_id = {execution.shard_id: execution for execution in executions}
    if len(by_id) != len(executions) or tuple(sorted(by_id)) != tuple(sorted(expected_ids)):
        raise TestHarnessError("pytest shard execution roster differs")
    ordered = tuple(by_id[shard_id] for shard_id in expected_ids)
    expected_rosters = (*plan.parallel_nodeids, plan.serial_nodeids)
    if any(
        execution.expected_nodeids != expected or execution.ledger.collected_nodeids != expected
        for execution, expected in zip(ordered, expected_rosters, strict=True)
    ):
        raise TestHarnessError("pytest shard execution differs from its assigned roster")
    collected = tuple(
        nodeid for execution in ordered for nodeid in execution.ledger.collected_nodeids
    )
    outcomes = tuple(item for execution in ordered for item in execution.ledger.outcomes)
    outcome_nodeids = tuple(item.nodeid for item in outcomes)
    canonical_set = set(plan.canonical)
    if (
        len(collected) != len(plan.canonical)
        or len(set(collected)) != len(collected)
        or set(collected) != canonical_set
        or len(outcome_nodeids) != len(plan.canonical)
        or len(set(outcome_nodeids)) != len(outcome_nodeids)
        or set(outcome_nodeids) != canonical_set
    ):
        raise TestHarnessError("aggregate pytest shard ledger has gaps or duplicates")
    counts = Counter(item.outcome for item in outcomes)
    gaps = len(canonical_set - set(outcome_nodeids))
    print(
        "sharded pytest: "
        f"in={len(plan.canonical)} out={len(outcomes)} "
        f"distinct={len(set(outcome_nodeids))} gaps={gaps} "
        f"passed={counts['passed']} skipped={counts['skipped']} "
        f"failed={counts['failed']} error={counts['error']} "
        f"xfailed={counts['xfailed']} xpassed={counts['xpassed']} "
        f"workers={len(plan.parallel_files)}"
    )
    abnormal = tuple(
        execution.returncode for execution in ordered if execution.returncode not in {0, 1}
    )
    if abnormal:
        raise TestHarnessError("pytest shard exited with an infrastructure status")
    if any(execution.returncode == 1 for execution in ordered):
        return 1
    if counts["failed"] or counts["error"]:
        raise TestHarnessError("pytest outcomes disagree with successful worker exits")
    return 0


def _run_sharded_tests(
    *,
    source_root: Path,
    oracle_node_modules: Path | None,
    brain_receipt: dict[str, object],
    node: Path,
    pytest_args: Sequence[str],
    workers: int,
) -> int:
    arguments = _validate_sharded_pytest_args(pytest_args)
    with tempfile.TemporaryDirectory(prefix="metis-model1-pytest-shards-") as temporary:
        workspace = Path(temporary).resolve(strict=True)
        workspace.chmod(0o700)
        collection_directory = _private_shard_directory(workspace, "collection")
        with _isolated_authority_pair(
            source_root=source_root,
            oracle_node_modules=oracle_node_modules,
            brain_receipt=brain_receipt,
        ) as (isolated, brain_isolated):
            collection = _execute_ledger_pytest(
                shard_id="canonical-collection",
                directory=collection_directory,
                isolated=isolated,
                brain_isolated=brain_isolated,
                node=node,
                pytest_args=arguments,
                collect_only=True,
            )
        if collection.returncode != 0 or collection.ledger.outcomes:
            raise TestHarnessError("canonical pytest collection failed")
        plan = _partition_collection(collection.ledger.collected_nodeids, workers=workers)

        parallel_directories = tuple(
            _private_shard_directory(workspace, f"parallel-{index}") for index in range(workers)
        )
        parallel_executions: list[_ShardExecution] = []
        with ExitStack() as authorities:
            authority_pairs = tuple(
                authorities.enter_context(
                    _isolated_authority_pair(
                        source_root=source_root,
                        oracle_node_modules=oracle_node_modules,
                        brain_receipt=brain_receipt,
                    )
                )
                for _ in range(workers)
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="metis-pytest-shard",
            ) as executor:
                futures = tuple(
                    executor.submit(
                        _execute_prepared_test_shard,
                        shard_id=f"parallel-{index}",
                        directory=parallel_directories[index],
                        files=plan.parallel_files[index],
                        expected_nodeids=plan.parallel_nodeids[index],
                        isolated=authority_pairs[index][0],
                        brain_isolated=authority_pairs[index][1],
                        node=node,
                        pytest_args=arguments,
                    )
                    for index in range(workers)
                )
                for future in futures:
                    parallel_executions.append(future.result())

        serial_execution = _execute_test_shard(
            shard_id="serial-quarantine",
            directory=_private_shard_directory(workspace, "serial-quarantine"),
            files=plan.serial_files,
            expected_nodeids=plan.serial_nodeids,
            source_root=source_root,
            oracle_node_modules=oracle_node_modules,
            brain_receipt=brain_receipt,
            node=node,
            pytest_args=arguments,
        )
        return _aggregate_shards(plan, (*parallel_executions, serial_execution))


def run_tests(
    *,
    metis_root: Path,
    oracle_node_modules: Path | None,
    node_path: Path,
    pytest_args: Sequence[str],
    workers: int = 1,
) -> int:
    if type(workers) is not int or workers not in {1, SHARDED_WORKERS}:
        raise TestHarnessError("test worker count is invalid")
    node, digest = oracles._validate_node_binary(node_path)
    node_identity = _node_stat_identity(node)
    source_root = Path(metis_root).resolve(strict=True)
    try:
        brain_receipt = brain_toolchain_pin.verify_metis_brain_toolchain_pin(
            source_root,
            node,
            execute_probes=True,
        )
        if (
            brain_receipt.get("evidence_in") != 29
            or brain_receipt.get("evidence_out") != 29
            or brain_receipt.get("evidence_distinct") != 29
            or brain_receipt.get("evidence_gaps") != 0
            or brain_receipt.get("probes_in") != 9
            or brain_receipt.get("probes_out") != 9
            or brain_receipt.get("probes_distinct") != 9
            or brain_receipt.get("probes_gaps") != 0
            or brain_receipt.get("probes_executed") is not True
        ):
            raise TestHarnessError("Metis Brain lossless authority is incomplete")
        if workers == SHARDED_WORKERS:
            return _run_sharded_tests(
                source_root=source_root,
                oracle_node_modules=oracle_node_modules,
                brain_receipt=brain_receipt,
                node=node,
                pytest_args=pytest_args,
                workers=workers,
            )
        with _isolated_authority_pair(
            source_root=source_root,
            oracle_node_modules=oracle_node_modules,
            brain_receipt=brain_receipt,
        ) as (isolated, brain_isolated):
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", *pytest_args],
                cwd=PROJECT_ROOT,
                env=_pytest_environment(
                    isolated=isolated,
                    brain_isolated=brain_isolated,
                    node=node,
                ),
                check=False,
            )
            return completed.returncode
    finally:
        try:
            node_after, digest_after = oracles._validate_node_binary(node)
        except (OSError, oracles.OracleError) as error:
            raise TestHarnessError("Node authority changed during tests") from error
        if (
            node_after != node
            or digest_after != digest
            or _node_stat_identity(node_after) != node_identity
        ):
            raise TestHarnessError("Node authority changed during tests")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run tests against a clean pinned Metis authority")
    parser.add_argument("--metis-root", required=True, type=Path)
    parser.add_argument("--oracle-node-modules", type=Path)
    parser.add_argument("--node", required=True, type=Path)
    parser.add_argument("--workers", choices=(1, SHARDED_WORKERS), default=1, type=int)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    pytest_args = list(arguments.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    try:
        return run_tests(
            metis_root=arguments.metis_root,
            oracle_node_modules=arguments.oracle_node_modules,
            node_path=arguments.node,
            pytest_args=pytest_args,
            workers=arguments.workers,
        )
    except (
        TestHarnessError,
        brain_toolchain_pin.BrainToolchainPinError,
        oracles.OracleError,
        grammar_stdlib_oracle.GrammarStdlibOracleError,
    ):
        print("test authority validation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
