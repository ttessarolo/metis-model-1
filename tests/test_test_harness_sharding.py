from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from metis_model1 import pytest_shard_ledger as ledger
from metis_model1 import test_harness


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path.resolve(strict=True)


def _outcome(nodeid: str, outcome: str = "passed", reason: str | None = None):
    return ledger.LedgerOutcome(nodeid, outcome, reason)


def _ledger(
    shard_id: str,
    nodeids: tuple[str, ...],
    *,
    outcomes: tuple[ledger.LedgerOutcome, ...] | None = None,
    exitstatus: int = 0,
) -> ledger.ShardLedger:
    return ledger.ShardLedger(
        shard_id=shard_id,
        mode="execute",
        exitstatus=exitstatus,
        collected_nodeids=nodeids,
        outcomes=outcomes if outcomes is not None else tuple(_outcome(item) for item in nodeids),
        collection_sha256="sha256:" + "1" * 64,
        ledger_sha256="sha256:" + "2" * 64,
    )


def _execution(
    shard_id: str,
    nodeids: tuple[str, ...],
    *,
    outcomes: tuple[ledger.LedgerOutcome, ...] | None = None,
    returncode: int = 0,
) -> test_harness._ShardExecution:
    return test_harness._ShardExecution(
        shard_id=shard_id,
        expected_nodeids=nodeids,
        returncode=returncode,
        ledger=_ledger(shard_id, nodeids, outcomes=outcomes, exitstatus=returncode),
    )


def test_private_ledger_round_trip_is_canonical_bounded_and_skip_exact(tmp_path: Path) -> None:
    parent = _private_directory(tmp_path / "private")
    target = parent / "ledger.json"
    value = ledger.write_private_ledger(
        target,
        shard_id="parallel-0",
        mode="execute",
        exitstatus=0,
        collected_nodeids=("tests/test_a.py::test_ok", "tests/test_a.py::test_skip"),
        outcomes=(
            _outcome("tests/test_a.py::test_ok"),
            _outcome("tests/test_a.py::test_skip", "skipped", "reason with identity"),
        ),
    )

    assert value == ledger.read_private_ledger(
        target, expected_shard_id="parallel-0", expected_mode="execute"
    )
    assert stat.S_IMODE(target.lstat().st_mode) == 0o600
    raw = target.read_bytes()
    assert raw.endswith(b"\n") and len(raw) <= ledger.MAX_LEDGER_BYTES
    assert (
        json.dumps(
            json.loads(raw), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        + b"\n"
        == raw
    )
    assert value.outcomes[-1].skip_reason == "reason with identity"
    with pytest.raises(ledger.ShardLedgerError, match="binding differs"):
        ledger.read_private_ledger(target, expected_shard_id="parallel-0", expected_mode="collect")
    with pytest.raises(ledger.ShardLedgerError, match="already exists"):
        ledger.write_private_ledger(
            target,
            shard_id="parallel-0",
            mode="collect",
            exitstatus=0,
            collected_nodeids=(),
            outcomes=(),
        )


@pytest.mark.parametrize("attack", ["truncated", "hash", "mode", "symlink", "parent-mode"])
def test_private_ledger_rejects_malformed_forged_or_nonprivate_files(
    tmp_path: Path, attack: str
) -> None:
    parent = _private_directory(tmp_path / "private")
    target = parent / "ledger.json"
    ledger.write_private_ledger(
        target,
        shard_id="parallel-0",
        mode="collect",
        exitstatus=0,
        collected_nodeids=("tests/test_a.py::test_ok",),
        outcomes=(),
    )
    if attack == "truncated":
        target.write_bytes(target.read_bytes()[:-1])
    elif attack == "hash":
        value = json.loads(target.read_text(encoding="utf-8"))
        value["ledger_sha256"] = "sha256:" + "0" * 64
        target.write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif attack == "mode":
        target.chmod(0o644)
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(parent / "missing")
    else:
        parent.chmod(0o755)
    with pytest.raises(ledger.ShardLedgerError):
        ledger.read_private_ledger(target, expected_shard_id="parallel-0", expected_mode="collect")


def test_private_ledger_rejects_oversize_and_duplicate_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _private_directory(tmp_path / "private")
    target = parent / "ledger.json"
    monkeypatch.setattr(ledger, "MAX_LEDGER_BYTES", 128)
    with pytest.raises(ledger.ShardLedgerError, match="byte bound"):
        ledger.write_private_ledger(
            target,
            shard_id="parallel-0",
            mode="execute",
            exitstatus=0,
            collected_nodeids=("tests/test_a.py::test_" + "x" * 256,),
            outcomes=(),
        )
    target.write_bytes(b"x" * 129)
    target.chmod(0o600)
    with pytest.raises(ledger.ShardLedgerError, match="stable private regular file"):
        ledger.read_private_ledger(target, expected_shard_id="parallel-0", expected_mode="execute")
    target.unlink()

    monkeypatch.setattr(ledger, "MAX_LEDGER_BYTES", 64 * 1024 * 1024)
    with pytest.raises(ledger.ShardLedgerError, match="collection order"):
        ledger.write_private_ledger(
            target,
            shard_id="parallel-0",
            mode="execute",
            exitstatus=0,
            collected_nodeids=(
                "tests/test_a.py::test_ok",
                "tests/test_a.py::test_other",
            ),
            outcomes=(
                _outcome("tests/test_a.py::test_ok"),
                _outcome("tests/test_a.py::test_ok"),
            ),
        )


def test_plugin_records_real_pytest_pass_and_skip_without_autoload(tmp_path: Path) -> None:
    project = _private_directory(tmp_path / "project")
    tests = _private_directory(project / "tests")
    tests.joinpath("test_sample.py").write_text(
        "import pytest\n"
        "def test_ok(): pass\n"
        "def test_skip(): pytest.skip('bounded skip identity')\n",
        encoding="utf-8",
    )
    private = _private_directory(project / "ledger")
    target = private / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            test_harness.SHARD_LEDGER_PLUGIN,
            "-p",
            "no:cacheprovider",
            f"--metis-shard-ledger={target}",
            "--metis-shard-id=focused",
            "tests/test_sample.py",
        ],
        cwd=project,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    value = ledger.read_private_ledger(target, expected_shard_id="focused", expected_mode="execute")
    assert [item.outcome for item in value.outcomes] == ["passed", "skipped"]
    assert value.outcomes[-1].skip_reason == "Skipped: bounded skip identity"


def test_plugin_maps_real_expected_xfail_with_terminal_and_exitstatus_parity(
    tmp_path: Path,
) -> None:
    project = _private_directory(tmp_path / "project")
    tests = _private_directory(project / "tests")
    tests.joinpath("test_expected.py").write_text(
        "import pytest\n"
        "@pytest.mark.xfail(reason='known expected failure')\n"
        "def test_expected_failure(): assert False\n",
        encoding="utf-8",
    )
    private = _private_directory(project / "ledger")
    target = private / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-r",
            "a",
            "-p",
            test_harness.SHARD_LEDGER_PLUGIN,
            "-p",
            "no:cacheprovider",
            f"--metis-shard-ledger={target}",
            "--metis-shard-id=expected-xfail",
            "tests/test_expected.py",
        ],
        cwd=project,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    value = ledger.read_private_ledger(
        target, expected_shard_id="expected-xfail", expected_mode="execute"
    )
    assert completed.returncode == value.exitstatus == 0
    assert value.outcomes == (
        ledger.LedgerOutcome(
            "tests/test_expected.py::test_expected_failure",
            "xfailed",
            "known expected failure",
        ),
    )
    assert "1 xfailed" in completed.stdout


def test_plugin_maps_real_teardown_error_with_terminal_and_exitstatus_parity(
    tmp_path: Path,
) -> None:
    project = _private_directory(tmp_path / "project")
    tests = _private_directory(project / "tests")
    tests.joinpath("test_teardown.py").write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def broken_teardown():\n"
        "    yield\n"
        "    raise RuntimeError('bounded teardown error')\n"
        "def test_call_passes_then_teardown_errors(broken_teardown): pass\n",
        encoding="utf-8",
    )
    private = _private_directory(project / "ledger")
    target = private / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-r",
            "a",
            "-p",
            test_harness.SHARD_LEDGER_PLUGIN,
            "-p",
            "no:cacheprovider",
            f"--metis-shard-ledger={target}",
            "--metis-shard-id=teardown-error",
            "tests/test_teardown.py",
        ],
        cwd=project,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    value = ledger.read_private_ledger(
        target, expected_shard_id="teardown-error", expected_mode="execute"
    )
    assert completed.returncode == value.exitstatus == 1
    assert value.outcomes == (
        ledger.LedgerOutcome(
            "tests/test_teardown.py::test_call_passes_then_teardown_errors",
            "error",
            None,
        ),
    )
    assert "1 passed, 1 error" in completed.stdout


def test_partition_is_deterministic_whole_file_and_quarantines_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_harness, "SERIAL_TEST_FILES", frozenset({"tests/test_s.py"}))
    roster = (
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two[x]",
        "tests/test_b.py::test_three",
        "tests/test_c.py::test_four",
        "tests/test_s.py::test_serial_one",
        "tests/test_s.py::test_serial_two",
    )
    first = test_harness._partition_collection(roster, workers=2)
    second = test_harness._partition_collection(roster, workers=2)

    assert first == second
    assert first.serial_files == ("tests/test_s.py",)
    assert first.serial_nodeids == roster[-2:]
    owners = {
        filename: index
        for index, filenames in enumerate(first.parallel_files)
        for filename in filenames
    }
    assert owners["tests/test_a.py"] in {0, 1}
    assert all(
        test_harness._test_file(nodeid) in first.parallel_files[index]
        for index, nodeids in enumerate(first.parallel_nodeids)
        for nodeid in nodeids
    )


@pytest.mark.parametrize(
    "roster",
    [
        ("tests/test_a.py::test_one", "tests/test_a.py::test_one"),
        ("outside.py::test_one",),
        ("tests/nested/test_a.py::test_one",),
    ],
)
def test_partition_rejects_duplicates_noncanonical_paths_and_missing_quarantine(
    monkeypatch: pytest.MonkeyPatch, roster: tuple[str, ...]
) -> None:
    monkeypatch.setattr(test_harness, "SERIAL_TEST_FILES", frozenset({"tests/test_s.py"}))
    with pytest.raises(test_harness.TestHarnessError):
        test_harness._partition_collection(roster, workers=2)


def test_aggregate_requires_exact_union_and_preserves_worker_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = test_harness._ShardPlan(
        canonical=("tests/test_a.py::test_a", "tests/test_b.py::test_b", "tests/test_s.py::test_s"),
        parallel_files=(("tests/test_a.py",), ("tests/test_b.py",)),
        parallel_nodeids=(("tests/test_a.py::test_a",), ("tests/test_b.py::test_b",)),
        serial_files=("tests/test_s.py",),
        serial_nodeids=("tests/test_s.py::test_s",),
    )
    executions = (
        _execution("parallel-0", plan.parallel_nodeids[0]),
        _execution(
            "parallel-1",
            plan.parallel_nodeids[1],
            outcomes=(_outcome("tests/test_b.py::test_b", "failed"),),
            returncode=1,
        ),
        _execution("serial-quarantine", plan.serial_nodeids),
    )
    assert test_harness._aggregate_shards(plan, executions) == 1
    assert "in=3 out=3 distinct=3 gaps=0" in capsys.readouterr().out

    duplicate = (
        executions[0],
        _execution("parallel-1", ("tests/test_a.py::test_a",)),
        executions[2],
    )
    with pytest.raises(test_harness.TestHarnessError, match="assigned roster"):
        test_harness._aggregate_shards(plan, duplicate)


@contextmanager
def _fake_authorities(**_kwargs: object) -> Iterator[tuple[Path, Path]]:
    yield Path("/isolated"), Path("/brain-isolated")


def test_workers_two_executes_real_parallel_and_serial_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _private_directory(tmp_path / "project")
    tests = _private_directory(project / "tests")
    tests.joinpath("test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    tests.joinpath("test_b.py").write_text(
        "import pytest\n@pytest.mark.xfail(reason='known', strict=False)\ndef test_b(): pass\n",
        encoding="utf-8",
    )
    tests.joinpath("test_serial.py").write_text(
        "import pytest\ndef test_serial(): pass\ndef test_skip(): pytest.skip('serial reason')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(test_harness, "PROJECT_ROOT", project)
    monkeypatch.setattr(test_harness, "SERIAL_TEST_FILES", frozenset({"tests/test_serial.py"}))
    monkeypatch.setattr(test_harness, "_isolated_authority_pair", _fake_authorities)
    reference = test_harness._execute_ledger_pytest(
        shard_id="serial-reference",
        directory=_private_directory(tmp_path / "serial-reference"),
        isolated=Path("/isolated"),
        brain_isolated=Path("/brain-isolated"),
        node=tmp_path / "node",
        pytest_args=("-q",),
        collect_only=False,
        files=("tests/test_a.py", "tests/test_b.py", "tests/test_serial.py"),
    )
    aggregate = test_harness._aggregate_shards
    captured: dict[str, object] = {}

    def capture_aggregate(
        plan: test_harness._ShardPlan,
        executions: tuple[test_harness._ShardExecution, ...],
    ) -> int:
        captured.update(plan=plan, executions=executions)
        return aggregate(plan, executions)

    monkeypatch.setattr(test_harness, "_aggregate_shards", capture_aggregate)

    result = test_harness._run_sharded_tests(
        source_root=tmp_path / "source",
        oracle_node_modules=None,
        brain_receipt={},
        node=tmp_path / "node",
        pytest_args=("-q",),
        workers=2,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "in=4 out=4 distinct=4 gaps=0 passed=2 skipped=1" in output
    assert "xpassed=1" in output
    plan = captured["plan"]
    executions = captured["executions"]
    assert isinstance(plan, test_harness._ShardPlan)
    assert isinstance(executions, tuple)
    observed = {
        item.nodeid: (item.outcome, item.skip_reason)
        for execution in executions
        for item in execution.ledger.outcomes
    }
    expected = {item.nodeid: (item.outcome, item.skip_reason) for item in reference.ledger.outcomes}
    assert plan.canonical == reference.ledger.collected_nodeids
    assert observed == expected


def test_parallel_authorities_are_materialized_sequentially_before_worker_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roster = (
        "tests/test_a.py::test_a",
        "tests/test_b.py::test_b",
        "tests/test_serial.py::test_serial",
    )
    monkeypatch.setattr(test_harness, "SERIAL_TEST_FILES", frozenset({"tests/test_serial.py"}))
    main_thread = threading.get_ident()
    events: list[tuple[str, int, int]] = []
    active: set[int] = set()
    next_pair = 0

    @contextmanager
    def authorities(**_kwargs: object) -> Iterator[tuple[Path, Path]]:
        nonlocal next_pair
        pair_id = next_pair
        next_pair += 1
        assert threading.get_ident() == main_thread
        active.add(pair_id)
        events.append(("enter", pair_id, threading.get_ident()))
        try:
            yield Path(f"/isolated-{pair_id}"), Path(f"/brain-isolated-{pair_id}")
        finally:
            assert threading.get_ident() == main_thread
            active.remove(pair_id)
            events.append(("exit", pair_id, threading.get_ident()))

    def collect(**kwargs: object) -> test_harness._ShardExecution:
        assert kwargs["collect_only"] is True
        assert active == {0}
        return _execution("canonical-collection", roster, outcomes=())

    def execute(**kwargs: object) -> test_harness._ShardExecution:
        shard_id = str(kwargs["shard_id"])
        pair_id = int(Path(kwargs["isolated"]).name.rsplit("-", 1)[1])
        assert pair_id in active
        events.append(("execute", pair_id, threading.get_ident()))
        return _execution(shard_id, kwargs["expected_nodeids"])

    monkeypatch.setattr(test_harness, "_isolated_authority_pair", authorities)
    monkeypatch.setattr(test_harness, "_execute_ledger_pytest", collect)
    monkeypatch.setattr(test_harness, "_execute_prepared_test_shard", execute)

    assert (
        test_harness._run_sharded_tests(
            source_root=tmp_path / "source",
            oracle_node_modules=None,
            brain_receipt={},
            node=tmp_path / "node",
            pytest_args=("-q",),
            workers=2,
        )
        == 0
    )
    parallel_enters = [events.index(("enter", pair_id, main_thread)) for pair_id in (1, 2)]
    parallel_executes = [
        index
        for index, (name, pair_id, _thread) in enumerate(events)
        if name == "execute" and pair_id in {1, 2}
    ]
    assert max(parallel_enters) < min(parallel_executes)
    assert all(
        thread != main_thread
        for name, pair_id, thread in events
        if name == "execute" and pair_id in {1, 2}
    )
    assert [pair_id for name, pair_id, _thread in events if name == "enter"] == [0, 1, 2, 3]


def test_worker_crash_without_ledger_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private_directory(tmp_path / "worker")
    monkeypatch.setattr(
        test_harness.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )
    with pytest.raises(test_harness.TestHarnessError, match="ledger is unavailable"):
        test_harness._execute_ledger_pytest(
            shard_id="parallel-0",
            directory=directory,
            isolated=tmp_path / "isolated",
            brain_isolated=tmp_path / "brain",
            node=tmp_path / "node",
            pytest_args=(),
            collect_only=False,
            files=("tests/test_a.py",),
        )


def test_worker_collection_drift_and_authority_mutation_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _private_directory(tmp_path / "worker")
    expected = ("tests/test_a.py::test_expected",)
    drifted = ("tests/test_a.py::test_drifted",)
    monkeypatch.setattr(
        test_harness,
        "_execute_ledger_pytest",
        lambda **_kwargs: _execution("parallel-0", drifted),
    )
    monkeypatch.setattr(test_harness, "_isolated_authority_pair", _fake_authorities)
    with pytest.raises(test_harness.TestHarnessError, match="collection drifted"):
        test_harness._execute_test_shard(
            shard_id="parallel-0",
            directory=directory,
            files=("tests/test_a.py",),
            expected_nodeids=expected,
            source_root=tmp_path / "source",
            oracle_node_modules=None,
            brain_receipt={},
            node=tmp_path / "node",
            pytest_args=(),
        )

    @contextmanager
    def mutating_authorities(**_kwargs: object) -> Iterator[tuple[Path, Path]]:
        yield Path("/isolated"), Path("/brain-isolated")
        raise test_harness.TestHarnessError("isolated Metis authority changed during tests")

    monkeypatch.setattr(test_harness, "_isolated_authority_pair", mutating_authorities)
    monkeypatch.setattr(
        test_harness,
        "_execute_ledger_pytest",
        lambda **_kwargs: _execution("parallel-0", expected),
    )
    with pytest.raises(test_harness.TestHarnessError, match="authority changed"):
        test_harness._execute_test_shard(
            shard_id="parallel-0",
            directory=directory,
            files=("tests/test_a.py",),
            expected_nodeids=expected,
            source_root=tmp_path / "source",
            oracle_node_modules=None,
            brain_receipt={},
            node=tmp_path / "node",
            pytest_args=(),
        )


def test_run_tests_workers_two_verifies_brain_pin_once_and_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"node")
    calls = {"brain": 0, "sharded": 0}

    monkeypatch.setattr(
        test_harness.oracles,
        "_validate_node_binary",
        lambda path: (Path(path), "digest"),
    )

    def verify(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["brain"] += 1
        return {
            "evidence_in": 29,
            "evidence_out": 29,
            "evidence_distinct": 29,
            "evidence_gaps": 0,
            "probes_in": 9,
            "probes_out": 9,
            "probes_distinct": 9,
            "probes_gaps": 0,
            "probes_executed": True,
            "revision": "brain-revision",
            "tree": "brain-tree",
            "identity": SimpleNamespace(node_modules_sha256="sha256:" + "1" * 64),
        }

    def sharded(**kwargs: object) -> int:
        calls["sharded"] += 1
        assert kwargs["workers"] == 2
        return 0

    monkeypatch.setattr(
        test_harness.brain_toolchain_pin, "verify_metis_brain_toolchain_pin", verify
    )
    monkeypatch.setattr(test_harness, "_run_sharded_tests", sharded)

    assert (
        test_harness.run_tests(
            metis_root=source,
            oracle_node_modules=None,
            node_path=node,
            pytest_args=("-q",),
            workers=2,
        )
        == 0
    )
    assert calls == {"brain": 1, "sharded": 1}
