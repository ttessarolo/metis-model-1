from __future__ import annotations

import contextlib
import importlib.util
import inspect
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
GATE_PATH = PROJECT_ROOT / "runtime/w3_bridge_gate.py"
QUALIFIER_PATH = PROJECT_ROOT / "runtime/w3_qualifier.py"
SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-bridge-replay.schema.json"
QUALIFICATION_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-qualification.schema.json"
SPEC = importlib.util.spec_from_file_location("w3_bridge_gate_under_test", GATE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
QUALIFIER_SPEC = importlib.util.spec_from_file_location(
    "w3_qualifier_for_bridge_test", QUALIFIER_PATH
)
assert QUALIFIER_SPEC and QUALIFIER_SPEC.loader
QUALIFIER = importlib.util.module_from_spec(QUALIFIER_SPEC)
QUALIFIER_SPEC.loader.exec_module(QUALIFIER)


def _finish_manifest(body: dict) -> dict:
    return {**body, "manifest_sha256": GATE.canonical_hash(body)}


def _file(path: str, *, size: int, mode: int, sha256: str, role: str) -> dict:
    return {"path": path, "size": size, "mode": mode, "sha256": sha256, "role": role}


def _authority(launcher: dict) -> dict:
    worker_sha = "sha256:" + "1" * 64
    source_files = [
        _file(
            "runtime/w3_production_worker.py",
            size=1,
            mode=0o444,
            sha256=worker_sha,
            role="worker",
        ),
        _file(
            "manifests/w3-candidates.json",
            size=1,
            mode=0o444,
            sha256="sha256:" + "2" * 64,
            role="manifest",
        ),
        _file(
            "manifests/w3-semantic-registry.json",
            size=1,
            mode=0o444,
            sha256="sha256:" + "3" * 64,
            role="manifest",
        ),
    ]
    source = _finish_manifest(
        {
            "schema_version": 2,
            "bundle_id": "source-fixture",
            "kind": "source",
            "counts": {"files": len(source_files), "bytes": 3},
            "files": source_files,
            "roster_sha256": GATE.canonical_hash(source_files),
        }
    )
    dependency_files = [
        _file(
            f"site-packages/fixture/{index:03}.py",
            size=1_799_002 if index == 0 else 0,
            mode=0o444,
            sha256="sha256:" + f"{index + 10:064x}",
            role="dependency",
        )
        for index in range(144)
    ]
    dependency = _finish_manifest(
        {
            "schema_version": 2,
            "bundle_id": "dependency-fixture",
            "kind": "dependency",
            "python": deepcopy(GATE.DEPENDENCY_PYTHON),
            "counts": {"files": 144, "bytes": 1_799_002},
            "files": dependency_files,
            "roster_sha256": GATE.DEPENDENCY_ROSTER_SHA256,
        }
    )
    capsule_files = [
        _file(
            "bin/node",
            size=1,
            mode=0o555,
            sha256=GATE.PINNED_NODE_SHA256,
            role="node",
        ),
        _file(
            "tooling/node_modules/tsx/dist/loader.mjs",
            size=1,
            mode=0o444,
            sha256="sha256:" + "4" * 64,
            role="tsx",
        ),
        _file(
            ".metis-oracle/runner.ts",
            size=1,
            mode=0o444,
            sha256=GATE.PINNED_RUNNER_SHA256,
            role="runner",
        ),
    ]
    capsule = _finish_manifest(
        {
            "schema_version": 2,
            "capsule_id": "capsule-fixture",
            "revision": GATE.PINNED_METIS_REVISION,
            "tree": GATE.PINNED_METIS_TREE,
            "language_version": "0.43",
            "node": {
                "path": "bin/node",
                "sha256": GATE.PINNED_NODE_SHA256,
                "mode": 0o555,
            },
            "tsx": {
                "path": "tooling/node_modules/tsx/dist/loader.mjs",
                "sha256": "sha256:" + "4" * 64,
                "mode": 0o444,
            },
            "runner": {
                "path": ".metis-oracle/runner.ts",
                "sha256": GATE.PINNED_RUNNER_SHA256,
                "mode": 0o444,
            },
            "tooling": deepcopy(GATE.PINNED_TOOLING),
            "counts": {"files": 3, "bytes": 3},
            "files": capsule_files,
            "roster_sha256": GATE.canonical_hash(capsule_files),
        }
    )
    body = {
        "schema_version": 2,
        "authority_id": GATE.AUTHORITY_ID,
        "status": "independently_ratified",
        "ratification": {
            "verdict": "RATIFIABLE",
            "scope": ["F-1", "F-2", "F-3"],
            "independent": True,
            "kimi_report_sha256": GATE.KIMI_REPORT_SHA256,
        },
        "project": {
            "revision": GATE.PROJECT_REVISION,
            "candidate_manifest": {
                "path": "manifests/w3-candidates.json",
                "manifest_sha256": GATE.CANDIDATE_MANIFEST_SHA256,
            },
            "semantic_registry": {
                "path": "manifests/w3-semantic-registry.json",
                "manifest_sha256": GATE.SEMANTIC_REGISTRY_SHA256,
            },
            "launcher": launcher,
            "worker": {
                "path": "runtime/w3_production_worker.py",
                "sha256": worker_sha,
                "protocol": "w3-production-capsule-worker-v2",
            },
        },
        "source_bundle": source,
        "dependency_bundle": dependency,
        "capsule": capsule,
        "expected": {"candidates": 3, "executions": 5, "roles": GATE.ONE_RUN_ROLES},
        "non_claims": list(GATE.NON_CLAIMS),
    }
    return _finish_manifest(body)


def _oracle_artifact(
    authority: dict,
    candidate: str,
    role: str,
    request_sha256: str,
) -> tuple[dict, dict]:
    runtime = GATE._runtime_authority(authority)
    result = {
        "schema_version": 1,
        "status": "ok" if role != "mutated" else "invalid",
        "endpoint": "fixture",
        "diagnostics": [],
        "ast": {"inventory": []},
        "ir": {"value": {}},
        "toolchain": runtime["toolchain"],
        "runtime": runtime["runtime_identity"],
        "failure": None,
    }
    evidence = {
        "input_sha256": request_sha256,
        "diagnostics_sha256": GATE.canonical_hash(result["diagnostics"]),
        "ast_sha256": GATE.canonical_hash(result["ast"]["inventory"]),
        "ir_sha256": GATE.canonical_hash(result["ir"]["value"]),
        "toolchain_revision": GATE.PINNED_METIS_REVISION,
        "toolchain_tree": GATE.PINNED_METIS_TREE,
        "runtime_sha256": GATE.canonical_hash(runtime["runtime_identity"]),
        "runtime_identity": runtime["runtime_identity"],
        **runtime["evidence_pins"],
        "metis_status": "",
    }
    oracle = {"schema_version": 1, "result": result, "evidence": evidence}
    evidence["envelope_sha256"] = GATE.canonical_hash(oracle)
    body = {
        "schema_version": 2,
        "protocol": "metis-runtime-capsule-v2",
        "execution_id": f"{candidate}.{role}",
        "request_sha256": request_sha256,
        "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
        "execution_policy": deepcopy(GATE.PINNED_CAPSULE_EXECUTION_POLICY),
        "oracle_envelope": oracle,
    }
    artifact = _finish_manifest(body)
    return artifact, result


def _qualification(authority: dict) -> tuple[dict, dict[str, bytes]]:
    roles = (
        ("candidate-f1", "F-1", "author"),
        ("candidate-f2", "F-2", "before"),
        ("candidate-f2", "F-2", "after"),
        ("candidate-f3", "F-3", "mutated"),
        ("candidate-f3", "F-3", "fixed"),
    )
    executions = []
    artifacts = {}
    for index, (candidate, family, role) in enumerate(roles):
        request_sha256 = GATE.canonical_hash({"fixture": index})
        artifact, result = _oracle_artifact(authority, candidate, role, request_sha256)
        artifact_path = f"artifacts/{candidate}/{role}.json"
        raw = GATE.canonical_json_bytes(artifact)
        artifacts[artifact_path] = raw
        executions.append(
            {
                "candidate_id": candidate,
                "family": family,
                "role": role,
                "request_sha256": request_sha256,
                "capsule_envelope_sha256": GATE.canonical_hash(artifact),
                "oracle_envelope_sha256": GATE.canonical_hash(artifact["oracle_envelope"]),
                "result_sha256": GATE.canonical_hash(result),
                "artifact_path": artifact_path,
                "artifact_sha256": GATE.bytes_hash(raw),
            }
        )

    def retained_root(kind: str, logical_root: str, locator: str, digest_character: str) -> dict:
        digest = "sha256:" + digest_character * 64
        root_body = {
            "state": "sealed",
            "kind": kind,
            "logical_root": logical_root,
            "anchor": "run-root",
            "locator": locator,
            "counts": {"files": 1, "directories": 1, "bytes": 2},
            "physical_roster_sha256": digest,
            "normalized_roster_sha256": digest,
            "snapshot_first_sha256": digest,
            "snapshot_second_sha256": digest,
            "sealed": True,
        }
        return {**root_body, "root_id": GATE.canonical_hash(root_body)}

    body = {
        "schema_version": 2,
        "qualification_id": GATE.QUALIFICATION_ID,
        "qualification_kind": "production-capsule-v2",
        "status": "qualified",
        "claim": "three_ratified_smoke_specs_production_capsule_only_no_accuracy_claim",
        "authority_manifest_sha256": authority["manifest_sha256"],
        "ratification_evidence_sha256": GATE.KIMI_REPORT_SHA256,
        "project_revision": GATE.PROJECT_REVISION,
        "source_bundle_manifest_sha256": authority["source_bundle"]["manifest_sha256"],
        "dependency_bundle_manifest_sha256": authority["dependency_bundle"]["manifest_sha256"],
        "dependency_roster_sha256": GATE.DEPENDENCY_ROSTER_SHA256,
        "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
        "candidate_manifest_sha256": GATE.CANDIDATE_MANIFEST_SHA256,
        "semantic_registry_sha256": GATE.SEMANTIC_REGISTRY_SHA256,
        "worker_input_sha256": "sha256:" + "9" * 64,
        "worker_output_sha256": "sha256:" + "a" * 64,
        "launcher": deepcopy(authority["project"]["launcher"]),
        "counts": {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "roles": deepcopy(GATE.ONE_RUN_ROLES),
        "executions": executions,
        "non_claims": list(GATE.NON_CLAIMS),
        "cleanup": {
            "status": "cleanup_deferred",
            "gc_policy": GATE.GC_POLICY,
            "delete_attempts": 0,
            "retained_roots": [
                retained_root(
                    "production-process-root",
                    "process",
                    ".w3-production-" + "a" * 24,
                    "c",
                ),
                retained_root(
                    "production-trusted-root",
                    "trusted",
                    ".w3-trusted-" + "b" * 24,
                    "d",
                ),
            ],
        },
    }
    return _finish_manifest(body), artifacts


def _physicalize_qualification(report: dict, run_index: int) -> dict:
    physical = deepcopy(report)
    for root in physical["cleanup"]["retained_roots"]:
        root["locator"] = f"{root['locator']}-run-{run_index}"
        root["root_id"] = GATE.canonical_hash(
            {key: value for key, value in root.items() if key != "root_id"}
        )
    return _finish_manifest(
        {key: value for key, value in physical.items() if key != "manifest_sha256"}
    )


def _blocked_retained_root_fixture(
    *,
    kind: str,
    logical_root: str,
    anchor: str,
    locator: str,
    digest_character: str,
    state: str = "sealed",
) -> dict:
    if state == "unmeasurable":
        body = {
            "state": "unmeasurable",
            "kind": kind,
            "logical_root": logical_root,
            "anchor": anchor,
            "locator": locator,
            "creation_observed": True,
            "reason": "injected retained-root measurement failure",
        }
    else:
        digest = "sha256:" + digest_character * 64
        body = {
            "state": "sealed",
            "kind": kind,
            "logical_root": logical_root,
            "anchor": anchor,
            "locator": locator,
            "counts": {"files": 1, "directories": 1, "bytes": 2},
            "physical_roster_sha256": digest,
            "normalized_roster_sha256": digest,
            "snapshot_first_sha256": digest,
            "snapshot_second_sha256": digest,
            "sealed": True,
        }
    return {**body, "root_id": GATE.canonical_hash(body)}


def _blocked_replay_fixture(
    *, cleanup: dict | None = None, observed_runs: list[dict] | None = None
) -> dict:
    return {
        "schema_version": 2,
        "replay_id": GATE.REPLAY_ID,
        "status": "blocked",
        "claim": "no_replay_claim",
        "reason": "injected blocked replay",
        "observed_runs": [] if observed_runs is None else observed_runs,
        "cleanup": GATE._empty_cleanup() if cleanup is None else cleanup,
    }


@pytest.mark.parametrize("target", ["top", "observed-child"])
def test_blocked_replay_rehashed_cleanup_prefixes_fail_schema_and_manual(target: str) -> None:
    process = _blocked_retained_root_fixture(
        kind="production-process-root",
        logical_root="process",
        anchor="run-root",
        locator=".w3-production-forbidden",
        digest_character="1",
    )
    trusted = _blocked_retained_root_fixture(
        kind="production-trusted-root",
        logical_root="trusted",
        anchor="run-root",
        locator=".w3-trusted-forbidden",
        digest_character="2",
    )
    cleanup = GATE._empty_cleanup()
    cleanup["retained_roots"] = [process] if target == "top" else [trusted]
    observed_runs = None
    top_cleanup = cleanup
    if target == "observed-child":
        top_cleanup = GATE._empty_cleanup()
        observed_runs = [
            {
                "run_index": 1,
                "status": "blocked",
                "qualification_manifest_sha256": None,
                "report_bytes_sha256": "sha256:" + "3" * 64,
                "cleanup": cleanup,
            }
        ]
    report = _blocked_replay_fixture(cleanup=top_cleanup, observed_runs=observed_runs)
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))
    if target == "top":
        with pytest.raises(GATE.BridgeGateBlocked, match="blocked retained root order"):
            GATE._blocked(report["reason"], report["cleanup"], report["observed_runs"])
    else:
        with pytest.raises(GATE.BridgeGateBlocked, match="blocked retained root order"):
            GATE._validate_observed_runs(report["observed_runs"])


@pytest.mark.parametrize("state", ["sealed", "unmeasurable"])
def test_blocked_replay_allows_only_top_and_child_prefixes_in_both_root_states(
    state: str,
) -> None:
    child_definitions = (
        (
            "production-process-root",
            "process",
            "run-root",
            ".w3-production-allowed",
            "4",
        ),
        (
            "production-trusted-root",
            "trusted",
            "run-root",
            ".w3-trusted-allowed",
            "5",
        ),
        (
            "qualification-publication-partial-root",
            "qualification-publication-partial",
            "artifact-root",
            "qualifications/partial-allowed",
            "6",
        ),
    )
    child_roots = [
        _blocked_retained_root_fixture(
            kind=kind,
            logical_root=logical,
            anchor=anchor,
            locator=locator,
            digest_character=digest,
            state=state,
        )
        for kind, logical, anchor, locator, digest in child_definitions
    ]
    holder = _blocked_retained_root_fixture(
        kind="replay-holder-root",
        logical_root="replay-holder",
        anchor="replay-artifact-root",
        locator=".w3-bridge-allowed",
        digest_character="7",
        state=state,
    )
    schema = json.loads(SCHEMA_PATH.read_text())
    for top_roots in ([], [holder]):
        report = _blocked_replay_fixture(
            cleanup={**GATE._empty_cleanup(), "retained_roots": deepcopy(top_roots)}
        )
        assert list(Draft202012Validator(schema).iter_errors(report)) == []
        GATE._blocked(report["reason"], report["cleanup"], report["observed_runs"])
    for length in range(len(child_roots) + 1):
        child_cleanup = {
            **GATE._empty_cleanup(),
            "retained_roots": deepcopy(child_roots[:length]),
        }
        observed = [
            {
                "run_index": 1,
                "status": "blocked",
                "qualification_manifest_sha256": None,
                "report_bytes_sha256": "sha256:" + "8" * 64,
                "cleanup": child_cleanup,
            }
        ]
        report = _blocked_replay_fixture(observed_runs=observed)
        assert list(Draft202012Validator(schema).iter_errors(report)) == []
        GATE._validate_observed_runs(observed)


def _no_report_observed_run(run_index: int) -> dict:
    return {
        "run_index": run_index,
        "status": "no-report",
        "qualification_manifest_sha256": None,
        "report_bytes_sha256": None,
        "cleanup": None,
    }


@pytest.mark.parametrize(
    ("run_indexes", "valid"),
    [([], True), ([1], True), ([1, 2], True), ([2], False), ([2, 1], False)],
    ids=("empty", "first", "first-second", "second-only", "reversed"),
)
def test_blocked_replay_observed_run_prefix_order_schema_and_manual_agree(
    run_indexes: list[int], valid: bool
) -> None:
    observed = [_no_report_observed_run(index) for index in run_indexes]
    report = _blocked_replay_fixture(observed_runs=observed)
    schema_errors = list(
        Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).iter_errors(report)
    )
    if valid:
        assert schema_errors == []
        GATE._validate_observed_runs(observed)
    else:
        assert schema_errors
        with pytest.raises(GATE.BridgeGateBlocked, match="observed-run order"):
            GATE._validate_observed_runs(observed)


@pytest.fixture
def replay_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    qualifier = tmp_path / "qualifier.py"
    qualifier.write_text("# fixture\n")
    qualifier_sha256 = GATE.bytes_hash(qualifier.read_bytes())
    monkeypatch.setattr(GATE, "PINNED_QUALIFIER_SHA256", qualifier_sha256)
    python = Path(sys.executable).resolve(strict=True)
    launcher = GATE._measured_launcher(qualifier.resolve(), qualifier_sha256, python)
    authority_value = _authority(launcher)
    authority = tmp_path / "authority.json"
    authority.write_bytes(GATE.canonical_json_bytes(authority_value))
    roots = {}
    for name in ("source", "dependency", "capsule"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    return {
        "qualifier_path": qualifier,
        "qualifier_sha256": qualifier_sha256,
        "authority_path": authority,
        "authority_sha256": authority_value["manifest_sha256"],
        "source_bundle_root": roots["source"],
        "dependency_bundle_root": roots["dependency"],
        "capsule_root": roots["capsule"],
        "artifact_root": tmp_path / "artifacts",
        "authority_value": authority_value,
    }


def _gate_arguments(inputs: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in inputs.items() if key != "authority_value"}


def _open_fd_snapshot() -> dict[int, tuple[int, int, int, int]]:
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


def _bridge_raise_on_line_after(
    function: object,
    needle: str,
    invoke: object,
    *,
    target_needle: str | None = None,
) -> BaseException:
    source, start = inspect.getsourcelines(function)
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
            and frame.f_code.co_filename == function.__code__.co_filename
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


BRIDGE_FD_TRANSFER_CASES = (
    "secure-root-descriptor-transfer",
    "secure-root-handle-transfer",
    "child-return",
    "random-return",
    "execute-lock",
    "execute-tempfile-first",
    "execute-tempfile-second",
    "remeasure-child",
    "blocked-namespace",
    "blocked-handle-return",
    "run-once-qualifications",
    "run-once-publication",
    "replay-artifact",
)


@pytest.mark.parametrize("case", BRIDGE_FD_TRANSFER_CASES)
def test_bridge_fd_transfer_exhaustive_roster_is_baseexception_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_inputs: dict[str, object],
    case: str,
) -> None:
    resources: list[object] = []
    function: object
    needle: str | None = None
    target_needle: str | None = None
    direct = False

    def anchored(path: Path, label: str):
        handle = GATE._open_or_create_secure_root(path, label)
        resources.append(handle)
        return handle

    if case in {"secure-root-descriptor-transfer", "secure-root-handle-transfer"}:
        function = GATE._open_or_create_secure_root
        needle = "handle = _AnchoredDirectory("
        target_needle = (
            "parent_descriptor = -1"
            if case == "secure-root-descriptor-transfer"
            else "return handle"
        )

        def invoke():
            return function(tmp_path / f"{case}-root", "bridge fd secure root")
    elif case == "child-return":
        parent = anchored(tmp_path / "child-parent", "bridge child parent")
        function = GATE._open_child_directory
        needle = "handle = _AnchoredDirectory("
        target_needle = "return handle"

        def invoke():
            return function(parent, "child", "bridge fd child")
    elif case == "random-return":
        parent = anchored(tmp_path / "random-parent", "bridge random parent")
        registry = GATE._RetainedHolderRegistry()
        resources.append(registry)
        function = GATE._create_random_directory
        needle = "handle = _open_child_directory("
        target_needle = "if token is not None:"

        def invoke():
            return function(
                parent,
                ".w3-fd-transfer-",
                "bridge fd random",
                registry=registry,
            )
    elif case.startswith("execute-"):
        function = GATE._execute_qualifier_preimage
        direct = True
        monkeypatch.setattr(
            GATE,
            "PINNED_QUALIFIER_SHA256",
            GATE.bytes_hash(QUALIFIER_PATH.read_bytes()),
        )
        if case == "execute-lock":
            monkeypatch.setattr(
                GATE.threading,
                "Lock",
                lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            )
        else:
            original_temporary = GATE.tempfile.TemporaryFile
            calls = 0

            def interrupt_temporary(*args: object, **kwargs: object):
                nonlocal calls
                calls += 1
                if calls == (1 if case == "execute-tempfile-first" else 2):
                    raise KeyboardInterrupt
                return original_temporary(*args, **kwargs)

            monkeypatch.setattr(GATE.tempfile, "TemporaryFile", interrupt_temporary)

        def invoke():
            return function(
                python=Path(sys.executable),
                qualifier=QUALIFIER_PATH,
                qualifier_preimage=QUALIFIER_PATH.read_bytes(),
                arguments=[],
                timeout=1.0,
            )
    elif case == "remeasure-child":
        run = anchored(tmp_path / "remeasure-run", "bridge remeasure run")
        locator = ".w3-production-" + "a" * 24
        child = GATE._open_child_directory(run, locator, "bridge remeasure fixture")
        os.fchmod(child.descriptor, 0o555)
        child.close()
        cleanup = {
            "retained_roots": [
                {
                    "kind": "production-process-root",
                    "locator": locator,
                }
            ]
        }
        monkeypatch.setattr(GATE, "_validate_cleanup", lambda *_args, **_kwargs: cleanup)
        function = GATE._remeasure_child_retained_roots
        needle = "handle = _open_child_directory("
        target_needle = "handle.assert_path_identity()"

        def invoke():
            return function(run, cleanup)
    elif case in {"blocked-namespace", "blocked-handle-return"}:
        artifact = anchored(tmp_path / "blocked-artifact", "bridge blocked artifact")
        run = anchored(tmp_path / "blocked-run", "bridge blocked run")
        namespace = GATE._open_child_directory(
            artifact,
            "qualifications",
            "bridge blocked namespace fixture",
        )
        target_name = "b" * 64
        target = GATE._open_child_directory(
            namespace,
            target_name,
            "bridge blocked target fixture",
        )
        os.fchmod(target.descriptor, 0o555)
        target.close()
        namespace.close()
        root = _blocked_retained_root_fixture(
            kind="qualification-publication-partial-root",
            logical_root="qualification-publication-partial",
            anchor="artifact-root",
            locator=f"qualifications/{target_name}",
            digest_character="1",
        )
        locator = GATE._safe_path(root["locator"], "bridge fd blocked locator")
        function = GATE._open_blocked_child_retained_root
        needle = (
            "namespace = _open_child_directory("
            if case == "blocked-namespace"
            else 'f"blocked child publication root {index}"'
        )
        target_needle = (
            "handle = _open_child_directory("
            if case == "blocked-namespace"
            else "return handle, namespace"
        )

        def invoke():
            return function(
                artifact_root=artifact,
                run_root=run,
                root=root,
                locator=locator,
                index=0,
            )
    elif case.startswith("run-once-"):
        artifact = anchored(tmp_path / "once-artifact", "bridge once artifact")
        run = anchored(tmp_path / "once-run", "bridge once run")
        manifest = "sha256:" + "c" * 64
        namespace = GATE._open_child_directory(
            artifact,
            "qualifications",
            "bridge once namespace fixture",
        )
        publication = GATE._open_child_directory(
            namespace,
            manifest[7:],
            "bridge once publication fixture",
        )
        os.fchmod(publication.descriptor, 0o555)
        publication.close()
        namespace.close()
        report = {"manifest_sha256": manifest, "executions": [], "cleanup": {}}
        completed = subprocess.CompletedProcess([], 0, stdout=b"{}\n", stderr=b"")
        monkeypatch.setattr(GATE, "_execute_qualifier_preimage", lambda **_kwargs: completed)
        monkeypatch.setattr(GATE, "_decode_canonical", lambda *_args, **_kwargs: report)
        monkeypatch.setattr(GATE, "_validate_qualification", lambda *_args, **_kwargs: report)
        monkeypatch.setattr(GATE, "_remeasure_child_retained_roots", lambda *_args: None)
        function = GATE._run_once
        needle = (
            "qualifications = _open_child_directory("
            if case == "run-once-qualifications"
            else "publication = _open_child_directory("
        )
        target_needle = (
            "publication = _open_child_directory("
            if case == "run-once-qualifications"
            else "snapshot = _snapshot_publication_descriptor("
        )

        def invoke():
            return function(
                python=Path(sys.executable),
                qualifier=QUALIFIER_PATH,
                qualifier_preimage=QUALIFIER_PATH.read_bytes(),
                authority=Path(replay_inputs["authority_path"]),
                authority_value={},
                authority_sha256="sha256:" + "d" * 64,
                source_bundle=Path(replay_inputs["source_bundle_root"]),
                dependency_bundle=Path(replay_inputs["dependency_bundle_root"]),
                capsule=Path(replay_inputs["capsule_root"]),
                artifact_root=artifact,
                run_root=run,
                nonce="e" * 64,
                timeout=1.0,
            )
    else:
        function = GATE.run_replay_gate
        needle = "artifact_handle = _open_or_create_secure_root"
        target_needle = "holder = _create_random_directory("

        def invoke():
            return function(**_gate_arguments(replay_inputs))

    before = _open_fd_snapshot()
    retained: BaseException | None = None
    after: dict[int, tuple[int, int, int, int]] = {}
    try:
        if direct:
            caught: list[BaseException] = []
            try:
                invoke()
            except BaseException as error:
                caught.append(error)
            assert len(caught) == 1
            assert isinstance(caught[0], KeyboardInterrupt)
            assert caught[0].__traceback__ is not None
            retained = caught[0]
        else:
            assert needle is not None
            retained = _bridge_raise_on_line_after(
                function,
                needle,
                invoke,
                target_needle=target_needle,
            )
        after = _open_fd_snapshot()
        assert after == before
    finally:
        for descriptor in set(after) - set(before):
            with contextlib.suppress(OSError):
                os.close(descriptor)
        for resource in reversed(resources):
            resource.close()
        assert retained is not None


@pytest.mark.parametrize(
    "site",
    [
        "secure-root",
        "random-observe",
        "registry-dup-transfer",
        "blocked-publication",
        "run-pair-keyboard",
        "run-pair-blocked",
    ],
)
def test_bridge_sequential_fd_acquisitions_are_baseexception_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_inputs: dict[str, object],
    site: str,
) -> None:
    captured_handles: list[object] = []
    captured_fds: list[int] = []
    resources: list[object] = []

    if site == "secure-root":
        parent = tmp_path / "secure-root-parent"
        parent.mkdir(mode=0o700)
        original_assert = GATE._AnchoredDirectory.assert_path_identity

        def interrupt_identity(handle: object) -> None:
            if handle.label == "fd-census secure root":
                captured_handles.append(handle)
                raise KeyboardInterrupt
            original_assert(handle)

        monkeypatch.setattr(GATE._AnchoredDirectory, "assert_path_identity", interrupt_identity)

        def invoke() -> None:
            GATE._open_or_create_secure_root(parent / "root", "fd-census secure root")

        expected = KeyboardInterrupt
    elif site == "random-observe":
        parent = GATE._open_or_create_secure_root(tmp_path / "random-parent", "random parent")
        registry = GATE._RetainedHolderRegistry()
        resources.extend([registry, parent])

        def interrupt_observe(_token: int, handle: object) -> None:
            captured_handles.append(handle)
            raise KeyboardInterrupt

        monkeypatch.setattr(registry, "observe", interrupt_observe)

        def invoke() -> None:
            GATE._create_random_directory(
                parent, ".w3-fd-", "fd-census random root", registry=registry
            )

        expected = KeyboardInterrupt
    elif site == "registry-dup-transfer":
        parent = GATE._open_or_create_secure_root(tmp_path / "dup-parent", "dup parent")
        child = GATE._open_child_directory(parent, "child", "dup child")
        registry = GATE._RetainedHolderRegistry()
        token = registry.intent("child")
        registry.mark_created(token)
        resources.extend([registry, child, parent])

        class InterruptingEntry(dict):
            fired = False

            def __setitem__(self, key: object, value: object) -> None:
                if key == "handle" and not self.fired:
                    self.fired = True
                    captured_fds.append(self["descriptor"])
                    raise KeyboardInterrupt
                super().__setitem__(key, value)

        registry.entries[token] = InterruptingEntry(registry.entries[token])

        def invoke() -> None:
            registry.observe(token, child)

        expected = KeyboardInterrupt
    elif site == "blocked-publication":
        artifact = GATE._open_or_create_secure_root(
            tmp_path / "blocked-artifacts", "blocked artifact root"
        )
        run = GATE._open_or_create_secure_root(tmp_path / "blocked-run", "blocked run root")
        GATE._open_child_directory(
            artifact,
            "qualifications",
            "blocked fixture namespace",
        ).close()
        resources.extend([run, artifact])
        original_open = GATE._open_child_directory

        def interrupt_second_open(*args: object, **kwargs: object):
            label = args[2]
            if label == "blocked child publication root 0":
                raise KeyboardInterrupt
            handle = original_open(*args, **kwargs)
            if label == "blocked child qualification namespace":
                captured_handles.append(handle)
            return handle

        monkeypatch.setattr(GATE, "_open_child_directory", interrupt_second_open)
        root = _blocked_retained_root_fixture(
            kind="qualification-publication-partial-root",
            logical_root="qualification-publication-partial",
            anchor="artifact-root",
            locator="qualifications/" + "a" * 64,
            digest_character="1",
        )

        def invoke() -> None:
            GATE._open_blocked_child_retained_root(
                artifact_root=artifact,
                run_root=run,
                root=root,
                locator=GATE._safe_path(root["locator"], "fd-census locator"),
                index=0,
            )

        expected = KeyboardInterrupt
    else:
        original_open = GATE._open_child_directory

        def interrupt_run_open(*args: object, **kwargs: object):
            name = args[1]
            if name == "run-1":
                if site == "run-pair-keyboard":
                    raise KeyboardInterrupt
                raise GATE.BridgeGateBlocked("injected ordinary second-open failure")
            handle = original_open(*args, **kwargs)
            if name == "artifacts-1":
                captured_handles.append(handle)
            return handle

        monkeypatch.setattr(GATE, "_open_child_directory", interrupt_run_open)

        def invoke() -> None:
            GATE.run_replay_gate(**_gate_arguments(replay_inputs))

        expected = KeyboardInterrupt if site == "run-pair-keyboard" else GATE.BridgeGateBlocked

    before = _open_fd_snapshot()
    try:
        with pytest.raises(expected):
            invoke()
        assert _open_fd_snapshot() == before
    finally:
        for resource in resources:
            resource.close()
        for handle in captured_handles:
            handle.close()
        for descriptor in captured_fds:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _install_stat_to_remove_cleanup_race(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Swap the owned inode at its final removal and preserve the replacement."""

    original_remove = GATE._remove_owned_directory
    original_rename = GATE.os.rename
    original_rmdir = GATE.os.rmdir
    original_mkdir = GATE.os.mkdir
    original_open = GATE.os.open
    state: dict[str, object] = {"armed": None, "attacked": False}

    def replacement_sentinel(parent_fd: int, name: str) -> None:
        replacement_fd = original_open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        sentinel_fd = -1
        try:
            sentinel_fd = original_open(
                "replacement-sentinel",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=replacement_fd,
            )
            os.write(sentinel_fd, b"replacement-preserve-exact")
        finally:
            if sentinel_fd >= 0:
                os.close(sentinel_fd)
            os.close(replacement_fd)

    def racing_rename(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        handle = state["armed"]
        if (
            handle is not None
            and not state["attacked"]
            and source == handle.name
            and src_dir_fd == handle.parent_descriptor
            and dst_dir_fd == handle.parent_descriptor
        ):
            displaced_name = f"{handle.name}.race-owned"
            original_rename(
                source,
                displaced_name,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )
            original_mkdir(handle.name, 0o700, dir_fd=handle.parent_descriptor)
            state.update(
                {
                    "attacked": True,
                    "canonical": handle.path,
                    "displaced": handle.path.parent / displaced_name,
                }
            )
            original_rename(
                source,
                target,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )
            replacement_sentinel(handle.parent_descriptor, os.fspath(target))
            return
        original_rename(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def racing_rmdir(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> None:
        handle = state["armed"]
        if (
            handle is not None
            and not state["attacked"]
            and name == handle.name
            and dir_fd == handle.parent_descriptor
        ):
            displaced_name = f"{handle.name}.race-owned"
            original_rename(
                name,
                displaced_name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            original_mkdir(handle.name, 0o700, dir_fd=handle.parent_descriptor)
            state.update(
                {
                    "attacked": True,
                    "canonical": handle.path,
                    "displaced": handle.path.parent / displaced_name,
                }
            )
        original_rmdir(name, dir_fd=dir_fd)

    def armed_remove(handle: object) -> bool:
        state["armed"] = handle
        try:
            return original_remove(handle)
        finally:
            state["armed"] = None

    monkeypatch.setattr(GATE.os, "rename", racing_rename)
    monkeypatch.setattr(GATE.os, "rmdir", racing_rmdir)
    monkeypatch.setattr(GATE, "_remove_owned_directory", armed_remove)
    return state


def _assert_cleanup_race_preserved_replacement(state: dict[str, object]) -> None:
    assert state["attacked"] is True
    canonical = state["canonical"]
    displaced = state["displaced"]
    assert isinstance(canonical, Path)
    assert isinstance(displaced, Path)
    assert canonical.is_dir() and not canonical.is_symlink()
    assert (canonical / "replacement-sentinel").read_bytes() == (b"replacement-preserve-exact")
    assert not displaced.exists()


def test_two_fresh_runs_emit_exact_replay_denominators_and_schema(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    qualification, artifacts = _qualification(replay_inputs["authority_value"])
    calls = []

    def fake_once(**kwargs: object):
        calls.append(kwargs["nonce"])
        physical = _physicalize_qualification(qualification, len(calls))
        return GATE.canonical_json_bytes(physical) + b"\n", physical, deepcopy(artifacts)

    monkeypatch.setattr(GATE, "_run_once", fake_once)
    report = GATE.run_replay_gate(**_gate_arguments(replay_inputs))

    assert len(calls) == len(set(calls)) == 2
    assert report["counts"] == {
        "fresh_processes": 2,
        "physical_invocations": 10,
        "semantic_identities": 5,
        "candidates": 3,
        "artifacts_per_run": 5,
        "gaps": 0,
    }
    assert report["roles"] == GATE.ROLES
    assert report["nonce_model"] == GATE.NONCE_MODEL
    assert [run["run_index"] for run in report["runs"]] == [1, 2]
    assert len({run["report_bytes_sha256"] for run in report["runs"]}) == 2
    assert [root["kind"] for root in report["cleanup"]["retained_roots"]] == ["replay-holder-root"]
    assert len(list(Path(replay_inputs["artifact_root"]).iterdir())) == 1
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report)) == []


def _qualified_replay_fixture(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> dict:
    qualification, artifacts = _qualification(replay_inputs["authority_value"])
    calls = 0

    def fake_once(**_kwargs: object):
        nonlocal calls
        calls += 1
        physical = _physicalize_qualification(qualification, calls)
        return GATE.canonical_json_bytes(physical) + b"\n", physical, deepcopy(artifacts)

    monkeypatch.setattr(GATE, "_run_once", fake_once)
    return GATE.run_replay_gate(**_gate_arguments(replay_inputs))


@pytest.mark.parametrize(
    ("attack", "valid"),
    [
        ("holder-boundary", True),
        ("holder-over-cap", False),
        ("holder-kind", False),
        ("holder-anchor", False),
        ("holder-state", False),
        ("child-process-over-cap", False),
        ("child-trusted-over-cap", False),
        ("child-order", False),
        ("run-order", False),
    ],
)
def test_replay_schema_and_manual_exact_retained_rosters_agree(
    replay_inputs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    valid: bool,
) -> None:
    report = _qualified_replay_fixture(replay_inputs, monkeypatch)
    holder = report["cleanup"]["retained_roots"][0]
    if attack == "holder-boundary":
        holder["counts"]["files"] = 16384
    elif attack == "holder-over-cap":
        holder["counts"]["files"] = 16385
    elif attack == "holder-kind":
        holder["kind"] = "production-process-root"
    elif attack == "holder-anchor":
        holder["anchor"] = "artifact-root"
    elif attack == "holder-state":
        body = {
            "state": "unmeasurable",
            "kind": "replay-holder-root",
            "logical_root": "replay-holder",
            "anchor": "replay-artifact-root",
            "locator": holder["locator"],
            "creation_observed": True,
            "reason": "injected qualified holder failure",
        }
        report["cleanup"]["retained_roots"][0] = {**body, "root_id": GATE.canonical_hash(body)}
    elif attack == "child-process-over-cap":
        report["runs"][0]["cleanup"]["retained_roots"][0]["counts"]["files"] = 513
    elif attack == "child-trusted-over-cap":
        report["runs"][0]["cleanup"]["retained_roots"][1]["counts"]["files"] = 4097
    elif attack == "child-order":
        report["runs"][0]["cleanup"]["retained_roots"].reverse()
    else:
        report["runs"].reverse()
    for cleanup in [report["cleanup"], *(run["cleanup"] for run in report["runs"])]:
        for root in cleanup["retained_roots"]:
            root["root_id"] = GATE.canonical_hash(
                {key: value for key, value in root.items() if key != "root_id"}
            )
    report["manifest_sha256"] = GATE.canonical_hash(
        {key: value for key, value in report.items() if key != "manifest_sha256"}
    )
    schema = json.loads(SCHEMA_PATH.read_text())
    schema_errors = list(Draft202012Validator(schema).iter_errors(report))
    if valid:
        assert schema_errors == []
        GATE._validate_replay_result(
            report,
            authority_sha256=report["authority_manifest_sha256"],
            capsule_sha256=report["capsule_manifest_sha256"],
        )
    else:
        assert schema_errors
        with pytest.raises(GATE.BridgeGateBlocked):
            GATE._validate_replay_result(
                report,
                authority_sha256=report["authority_manifest_sha256"],
                capsule_sha256=report["capsule_manifest_sha256"],
            )


def test_replay_finalizer_never_enters_name_based_remove_race(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    qualification, artifacts = _qualification(replay_inputs["authority_value"])
    calls = 0

    def fake_once(**_kwargs: object):
        nonlocal calls
        calls += 1
        physical = _physicalize_qualification(qualification, calls)
        return GATE.canonical_json_bytes(physical) + b"\n", physical, deepcopy(artifacts)

    monkeypatch.setattr(GATE, "_run_once", fake_once)
    outside = Path(replay_inputs["artifact_root"]).parent / "bridge-cleanup-race-outside"
    outside.mkdir()
    outside_sentinel = outside / "sentinel"
    outside_sentinel.write_bytes(b"outside-preserve-exact")
    state = _install_stat_to_remove_cleanup_race(monkeypatch)
    report = GATE.run_replay_gate(**_gate_arguments(replay_inputs))
    assert state["attacked"] is False
    assert report["cleanup"]["delete_attempts"] == 0
    assert outside_sentinel.read_bytes() == b"outside-preserve-exact"


def test_recursive_cleanup_child_swap_never_deletes_nonowned_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = GATE._open_or_create_secure_root(
        tmp_path / "recursive-cleanup-root",
        "recursive cleanup root",
    )
    child = GATE._open_child_directory(
        root,
        "owned-child",
        "recursive owned child",
        mode=0o700,
        create=True,
    )
    child_file = os.open(
        "owned-sentinel",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=child.descriptor,
    )
    try:
        os.write(child_file, b"owned-preserve-exact")
    finally:
        os.close(child_file)
        child.close()
    replacement = tmp_path / "recursive-replacement"
    replacement.mkdir()
    (replacement / "replacement-sentinel").write_bytes(b"replacement-preserve-exact")
    escaped = tmp_path / "recursive-escaped-owned-child"
    original_open = GATE.os.open
    original_rename = GATE.os.rename
    attacked = False

    def racing_open(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal attacked
        if not attacked and name == "owned-child" and dir_fd == root.descriptor:
            original_rename(name, escaped, src_dir_fd=dir_fd)
            original_rename(replacement, name, dst_dir_fd=dir_fd)
            attacked = True
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(GATE.os, "open", racing_open)
    removed = GATE._remove_owned_directory(root)

    assert attacked is False
    assert removed is False
    assert (
        tmp_path / "recursive-cleanup-root/owned-child/owned-sentinel"
    ).read_bytes() == b"owned-preserve-exact"
    assert (replacement / "replacement-sentinel").read_bytes() == b"replacement-preserve-exact"


@pytest.mark.parametrize("drift", ["artifact", "role", "count"])
def test_replay_drift_fails_closed(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    qualification, artifacts = _qualification(replay_inputs["authority_value"])
    calls = 0

    def fake_once(**kwargs: object):
        nonlocal calls
        calls += 1
        result = _physicalize_qualification(qualification, calls)
        rendered = GATE.canonical_json_bytes(result) + b"\n"
        run_artifacts = deepcopy(artifacts)
        if calls == 2:
            if drift == "report":
                rendered += b" "
            elif drift == "artifact":
                run_artifacts[next(iter(run_artifacts))] += b" "
            elif drift == "role":
                result["roles"]["author"] = 0
                rendered = GATE.canonical_json_bytes(result) + b"\n"
            elif drift == "count":
                result["counts"]["executions"] = 4
                rendered = GATE.canonical_json_bytes(result) + b"\n"
            else:
                result["manifest_sha256"] = "sha256:" + "0" * 64
                rendered = GATE.canonical_json_bytes(result) + b"\n"
        return rendered, result, run_artifacts

    monkeypatch.setattr(GATE, "_run_once", fake_once)
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE.run_replay_gate(**_gate_arguments(replay_inputs))


@pytest.mark.parametrize(
    "field",
    [
        "locator",
        "physical_roster_sha256",
        "snapshot_first_sha256",
        "snapshot_second_sha256",
        "root_id",
    ],
)
def test_normalized_projection_allows_each_physical_root_substitution(field: str) -> None:
    authority = _authority({key: f"fixture-{key}" for key in GATE.LAUNCHER_KEYS})
    report, _ = _qualification(authority)
    changed = deepcopy(report)
    root = changed["cleanup"]["retained_roots"][0]
    root[field] = "changed-locator" if field == "locator" else "sha256:" + "f" * 64
    assert GATE._normalized_qualification_projection(changed) == (
        GATE._normalized_qualification_projection(report)
    )


@pytest.mark.parametrize(
    "field",
    ["kind", "counts", "normalized-roster", "semantic", "runtime", "role"],
)
def test_normalized_projection_rejects_forbidden_semantic_substitutions(field: str) -> None:
    authority = _authority({key: f"fixture-{key}" for key in GATE.LAUNCHER_KEYS})
    report, _ = _qualification(authority)
    changed = deepcopy(report)
    root = changed["cleanup"]["retained_roots"][0]
    if field == "kind":
        root["kind"] = "production-trusted-root"
    elif field == "counts":
        root["counts"]["files"] += 1
    elif field == "normalized-roster":
        root["normalized_roster_sha256"] = "sha256:" + "f" * 64
    elif field == "semantic":
        changed["claim"] = "forged"
    elif field == "runtime":
        changed["launcher"]["python_version"] = "0.0.0"
    else:
        changed["roles"]["author"] = 0
    assert GATE._normalized_qualification_projection(changed) != (
        GATE._normalized_qualification_projection(report)
    )


def test_replay_rejects_a_copied_physical_descriptor_across_runs(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    qualification, artifacts = _qualification(replay_inputs["authority_value"])
    copied = _physicalize_qualification(qualification, 1)
    monkeypatch.setattr(
        GATE,
        "_run_once",
        lambda **_: (
            GATE.canonical_json_bytes(copied) + b"\n",
            deepcopy(copied),
            deepcopy(artifacts),
        ),
    )
    with pytest.raises(GATE.BridgeGateBlocked, match="descriptors were copied"):
        GATE.run_replay_gate(**_gate_arguments(replay_inputs))


@pytest.mark.parametrize(
    "attack",
    [
        "unmeasurable-qualified",
        "snapshot-drift",
        "bool-count",
        "over-cap",
        "wrong-order",
        "anchor-swap",
        "traversal",
    ],
)
def test_bridge_child_cleanup_mutations_fail_closed(attack: str) -> None:
    authority = _authority({key: f"fixture-{key}" for key in GATE.LAUNCHER_KEYS})
    cleanup = deepcopy(_qualification(authority)[0]["cleanup"])
    roots = cleanup["retained_roots"]
    if attack == "unmeasurable-qualified":
        body = {
            "state": "unmeasurable",
            "kind": "production-process-root",
            "logical_root": "process",
            "anchor": "run-root",
            "locator": ".w3-production-a",
            "creation_observed": True,
            "reason": "failed",
        }
        roots[0] = {**body, "root_id": GATE.canonical_hash(body)}
    elif attack == "snapshot-drift":
        roots[0]["snapshot_second_sha256"] = "sha256:" + "f" * 64
    elif attack == "bool-count":
        roots[0]["counts"]["files"] = True
    elif attack == "over-cap":
        roots[0]["counts"]["bytes"] = 128 * 1024 * 1024 + 1
    elif attack == "wrong-order":
        roots.reverse()
    elif attack == "anchor-swap":
        roots[0]["anchor"] = "artifact-root"
    else:
        roots[0]["locator"] = "../escape"
    if attack != "unmeasurable-qualified":
        for root in roots:
            root["root_id"] = GATE.canonical_hash(
                {key: value for key, value in root.items() if key != "root_id"}
            )
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._validate_cleanup(
            cleanup,
            qualified=True,
            expected_kinds=("production-process-root", "production-trusted-root"),
        )


def test_stale_consistently_rehashed_qualification_missing_cleanup_is_rejected() -> None:
    authority = _authority({key: f"fixture-{key}" for key in GATE.LAUNCHER_KEYS})
    report, _ = _qualification(authority)
    stale = deepcopy(report)
    stale.pop("cleanup")
    stale = _finish_manifest(
        {key: value for key, value in stale.items() if key != "manifest_sha256"}
    )
    with pytest.raises(GATE.BridgeGateBlocked, match="fields drifted"):
        GATE._validate_qualification(stale, authority, authority["manifest_sha256"])
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_report_v2(stale, stale["launcher"])


@pytest.mark.parametrize("attack", ["split", "merged"])
def test_consistently_rehashed_split_and_merged_retained_rosters_are_rejected(
    attack: str,
) -> None:
    authority = _authority({key: f"fixture-{key}" for key in GATE.LAUNCHER_KEYS})
    report, _ = _qualification(authority)
    roots = report["cleanup"]["retained_roots"]
    if attack == "split":
        split = deepcopy(roots[0])
        split["locator"] = ".w3-production-" + "c" * 24
        split["root_id"] = GATE.canonical_hash(
            {key: value for key, value in split.items() if key != "root_id"}
        )
        roots.insert(1, split)
    else:
        trusted = roots.pop()
        roots[0]["counts"] = {
            key: roots[0]["counts"][key] + trusted["counts"][key]
            for key in ("files", "directories", "bytes")
        }
        roots[0]["root_id"] = GATE.canonical_hash(
            {key: value for key, value in roots[0].items() if key != "root_id"}
        )
    report = _finish_manifest(
        {key: value for key, value in report.items() if key != "manifest_sha256"}
    )
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._validate_qualification(report, authority, authority["manifest_sha256"])


def test_all_six_report_variants_have_schema_manual_and_bridge_key_agreement() -> None:
    qualification_schema = json.loads(QUALIFICATION_SCHEMA_PATH.read_text())
    bridge_schema = json.loads(SCHEMA_PATH.read_text())
    agreements = (
        (
            qualification_schema["$defs"]["qualified"],
            QUALIFIER.QUALIFIED_V1_REPORT_KEYS,
        ),
        (
            qualification_schema["$defs"]["blocked"],
            QUALIFIER.BLOCKED_V1_REPORT_KEYS,
        ),
        (
            qualification_schema["$defs"]["productionQualified"],
            QUALIFIER.QUALIFIED_V2_REPORT_KEYS,
        ),
        (
            qualification_schema["$defs"]["productionBlocked"],
            QUALIFIER.BLOCKED_V2_REPORT_KEYS,
        ),
        (
            bridge_schema["$defs"]["qualified"],
            GATE.QUALIFIED_REPLAY_REPORT_KEYS,
        ),
        (
            bridge_schema["$defs"]["blocked"],
            GATE.BLOCKED_REPLAY_REPORT_KEYS,
        ),
    )
    assert len(agreements) == 6
    for schema_variant, manual_keys in agreements:
        assert schema_variant["additionalProperties"] is False
        assert set(schema_variant["required"]) == set(manual_keys)
        assert set(schema_variant["properties"]) == set(manual_keys)
    assert QUALIFIER.QUALIFIED_V2_REPORT_KEYS == GATE.QUALIFIED_CHILD_REPORT_KEYS


@pytest.mark.parametrize("status", ["blocked", "no-report"])
def test_blocked_replay_carries_child_or_no_report_and_retained_holder_evidence(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    def blocked_once(**_kwargs: object):
        error = GATE.BridgeGateBlocked("injected child stop")
        if status == "blocked":
            error.child_report_bytes = b'{"status":"blocked"}'
            error.child_cleanup = GATE._empty_cleanup()
        raise error

    monkeypatch.setattr(GATE, "_run_once", blocked_once)
    with pytest.raises(GATE.BridgeGateBlocked) as captured:
        GATE.run_replay_gate(**_gate_arguments(replay_inputs))
    error = captured.value
    assert error.observed_runs[0]["status"] == status
    assert [root["kind"] for root in error.cleanup["retained_roots"]] == ["replay-holder-root"]
    blocked = GATE._blocked(str(error), error.cleanup, error.observed_runs)
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(Draft202012Validator(schema).iter_errors(blocked)) == []


@pytest.mark.parametrize("attack", ["symlink", "fifo", "socket", "device", "hardlink", "cap"])
def test_replay_holder_measurement_attacks_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    parent = tmp_path / attack
    parent.mkdir()
    root = GATE._open_or_create_secure_root(parent / "holder", "test replay holder")
    outside = tmp_path / f"outside-{attack}"
    outside.write_bytes(b"outside-preserve-exact")
    if attack == "symlink":
        (root.path / "entry").symlink_to(outside)
    elif attack == "fifo":
        os.mkfifo(root.path / "entry", 0o600)
    elif attack == "socket":
        special_socket = socket.socket(socket.AF_UNIX)
        monkeypatch.chdir(root.path)
        special_socket.bind("entry")
        special_socket.close()
    elif attack == "device":
        (root.path / "entry").write_bytes(b"device-view")
        original_stat = GATE.os.stat

        def device_stat(*args: object, **kwargs: object) -> os.stat_result:
            observed = original_stat(*args, **kwargs)
            if args and args[0] == "entry" and kwargs.get("dir_fd") == root.descriptor:
                values = list(observed)
                values[0] = stat.S_IFCHR | 0o600
                return os.stat_result(values)
            return observed

        monkeypatch.setattr(GATE.os, "stat", device_stat)
    elif attack == "hardlink":
        os.link(outside, root.path / "entry")
    else:
        (root.path / "entry").write_bytes(b"x")
        (root.path / "entry").chmod(0o600)
        monkeypatch.setattr(GATE, "REPLAY_HOLDER_CAPS", (0, 1, 0, 0))
    try:
        with pytest.raises(GATE.BridgeGateBlocked):
            GATE._holder_descriptor(root.descriptor, root, "holder")
        assert outside.read_bytes() == b"outside-preserve-exact"
    finally:
        root.close()


def test_replay_holder_double_snapshot_blocks_rewrite_and_mode_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "holder-snapshot-restore"
    parent.mkdir()
    root = GATE._open_or_create_secure_root(parent / "holder", "holder snapshot root")
    path = root.path / "entry"
    path.write_bytes(b"original")
    path.chmod(0o600)
    original_snapshot = GATE._snapshot_holder_tree
    calls = 0

    def rewrite_after_first(*args: object, **kwargs: object):
        nonlocal calls
        result = original_snapshot(*args, **kwargs)
        calls += 1
        if calls == 1:
            path.chmod(0o644)
            path.write_bytes(b"mutated!")
            path.write_bytes(b"original")
            path.chmod(0o444)
        return result

    monkeypatch.setattr(GATE, "_snapshot_holder_tree", rewrite_after_first)
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="between retained snapshots"):
            GATE._holder_descriptor(root.descriptor, root, "holder")
        assert path.read_bytes() == b"original"
        assert stat.S_IMODE(path.stat().st_mode) == 0o444
    finally:
        root.close()


def test_replay_holder_creation_intent_survives_descriptor_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = GATE._open_or_create_secure_root(tmp_path / "parent", "holder intent parent")
    registry = GATE._RetainedHolderRegistry()

    def fail_observe(*_args: object) -> None:
        raise GATE.BridgeGateBlocked("injected holder descriptor failure")

    monkeypatch.setattr(registry, "observe", fail_observe)
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="injected"):
            GATE._create_random_directory(
                parent,
                ".w3-replay-",
                "holder intent root",
                registry=registry,
            )
        cleanup = registry.cleanup(qualified=False)
        assert len(cleanup["retained_roots"]) == 1
        assert cleanup["retained_roots"][0]["state"] == "unmeasurable"
        assert cleanup["retained_roots"][0]["creation_observed"] is True
        assert list(parent.path.glob(".w3-replay-*"))
    finally:
        registry.close()
        parent.close()


def test_replay_holder_normalized_roster_is_derived_from_snapshot_bytes(
    tmp_path: Path,
) -> None:
    roots = []
    descriptors = []
    try:
        for index, raw in enumerate((b"first", b"second")):
            root = GATE._open_or_create_secure_root(
                tmp_path / f"holder-snapshot-{index}", "holder snapshot root"
            )
            roots.append(root)
            entry = root.path / "entry"
            entry.write_bytes(raw)
            entry.chmod(0o600)
            descriptor = GATE._holder_descriptor(root.descriptor, root, f"holder-{index}")
            assert descriptor["normalized_roster_sha256"] == descriptor["physical_roster_sha256"]
            descriptors.append(descriptor)
        assert (
            descriptors[0]["normalized_roster_sha256"] != descriptors[1]["normalized_roster_sha256"]
        )
    finally:
        for root in roots:
            root.close()


def test_replay_holder_precreation_failure_does_not_claim_an_observed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = GATE._open_or_create_secure_root(tmp_path / "holder-precreate-parent", "parent")
    registry = GATE._RetainedHolderRegistry()

    def fail_before_creation(*_args: object, **_kwargs: object) -> None:
        raise GATE.BridgeGateBlocked("injected holder pre-creation failure")

    monkeypatch.setattr(GATE, "_open_child_directory", fail_before_creation)
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="pre-creation"):
            GATE._create_random_directory(
                parent,
                ".w3-replay-",
                "holder precreate root",
                registry=registry,
            )
        assert registry.cleanup(qualified=False)["retained_roots"] == []
        assert list(parent.path.iterdir()) == []
    finally:
        registry.close()
        parent.close()


def _materialize_reported_child_root(
    run_root: object,
    *,
    kind: str,
    logical_root: str,
    locator: str,
    file_size: int = 2,
) -> dict:
    child = GATE._open_child_directory(
        run_root,
        locator,
        f"fixture {kind}",
        mode=0o700,
        create=True,
    )
    try:
        descriptor = os.open(
            "entry",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=child.descriptor,
        )
        try:
            os.ftruncate(descriptor, file_size)
        finally:
            os.close(descriptor)
        GATE._seal_holder_tree(child.descriptor)
        child.mode = 0o555
        roster, counts = GATE._snapshot_holder_tree(child.descriptor)
        digest = GATE.bytes_hash(roster)
        body = {
            "state": "sealed",
            "kind": kind,
            "logical_root": logical_root,
            "anchor": "run-root",
            "locator": locator,
            "counts": counts,
            "physical_roster_sha256": digest,
            "normalized_roster_sha256": digest,
            "snapshot_first_sha256": digest,
            "snapshot_second_sha256": digest,
            "sealed": True,
        }
        return {**body, "root_id": GATE.canonical_hash(body)}
    finally:
        child.close()


@pytest.mark.parametrize(
    ("target_kind", "file_size", "valid"),
    [
        ("production-process-root", 8 * 1024 * 1024, True),
        ("production-process-root", 8 * 1024 * 1024 + 1, False),
        ("production-trusted-root", 8 * 1024 * 1024, True),
        ("production-trusted-root", 8 * 1024 * 1024 + 1, False),
    ],
    ids=("process-boundary", "process-over", "trusted-boundary", "trusted-over"),
)
def test_child_retained_root_remeasurement_enforces_per_file_cap(
    tmp_path: Path, target_kind: str, file_size: int, valid: bool
) -> None:
    run_root = GATE._open_or_create_secure_root(tmp_path / "run", "child cap run root")
    try:
        cleanup = GATE._empty_cleanup()
        cleanup["retained_roots"] = [
            _materialize_reported_child_root(
                run_root,
                kind="production-process-root",
                logical_root="process",
                locator=".w3-production-" + "a" * 24,
                file_size=file_size if target_kind == "production-process-root" else 2,
            ),
            _materialize_reported_child_root(
                run_root,
                kind="production-trusted-root",
                logical_root="trusted",
                locator=".w3-trusted-" + "b" * 24,
                file_size=file_size if target_kind == "production-trusted-root" else 2,
            ),
        ]
        if valid:
            GATE._remeasure_child_retained_roots(run_root, cleanup)
        else:
            with pytest.raises(GATE.BridgeGateBlocked, match="file or aggregate exceeds"):
                GATE._remeasure_child_retained_roots(run_root, cleanup)
    finally:
        run_root.close()


@pytest.mark.parametrize("attack", ["path", "roster"])
def test_child_retained_root_locator_and_physical_roster_are_remeasured(
    tmp_path: Path, attack: str
) -> None:
    run_root = GATE._open_or_create_secure_root(tmp_path / "run", "child run root")
    cleanup = GATE._empty_cleanup()
    try:
        cleanup["retained_roots"] = [
            _materialize_reported_child_root(
                run_root,
                kind="production-process-root",
                logical_root="process",
                locator=".w3-production-" + "a" * 24,
            ),
            _materialize_reported_child_root(
                run_root,
                kind="production-trusted-root",
                logical_root="trusted",
                locator=".w3-trusted-" + "b" * 24,
            ),
        ]
        GATE._remeasure_child_retained_roots(run_root, cleanup)
        changed = deepcopy(cleanup)
        if attack == "path":
            changed["retained_roots"][0]["locator"] = "nested/escape"
        else:
            changed["retained_roots"][0]["physical_roster_sha256"] = "sha256:" + "f" * 64
        root = changed["retained_roots"][0]
        root["root_id"] = GATE.canonical_hash(
            {key: value for key, value in root.items() if key != "root_id"}
        )
        with pytest.raises(GATE.BridgeGateBlocked):
            GATE._remeasure_child_retained_roots(run_root, changed)
    finally:
        run_root.close()


def _run_once_blocked_fixture(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup: dict,
) -> None:
    report = {
        "schema_version": 2,
        "qualification_id": GATE.QUALIFICATION_ID,
        "qualification_kind": "production-capsule-v2",
        "status": "blocked",
        "claim": "no_qualification_claim",
        "reason": "injected blocked child",
        "cleanup": cleanup,
    }
    monkeypatch.setattr(
        GATE,
        "_execute_qualifier_preimage",
        lambda **_kwargs: SimpleNamespace(
            stdout=GATE.canonical_json_bytes(report) + b"\n",
            stderr=b"",
            returncode=1,
        ),
    )
    artifact_root = GATE._open_or_create_secure_root(
        tmp_path / "artifacts", "blocked child artifact root"
    )
    run_root = GATE._open_or_create_secure_root(tmp_path / "run", "blocked child run root")
    try:
        GATE._run_once(
            python=Path(sys.executable).resolve(strict=True),
            qualifier=tmp_path / "qualifier.py",
            qualifier_preimage=b"# injected blocked child",
            authority=tmp_path / "authority.json",
            authority_value={},
            authority_sha256="sha256:" + "9" * 64,
            source_bundle=tmp_path / "source",
            dependency_bundle=tmp_path / "dependency",
            capsule=tmp_path / "capsule",
            artifact_root=artifact_root,
            run_root=run_root,
            nonce="0" * 64,
            timeout=1.0,
        )
    finally:
        run_root.close()
        artifact_root.close()


def test_run_once_blocked_child_parser_rejects_forbidden_cleanup_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = _blocked_retained_root_fixture(
        kind="production-trusted-root",
        logical_root="trusted",
        anchor="run-root",
        locator=".w3-trusted-" + "b" * 24,
        digest_character="9",
    )
    cleanup = {**GATE._empty_cleanup(), "retained_roots": [trusted]}
    with pytest.raises(GATE.BridgeGateBlocked, match="blocked retained root order") as captured:
        _run_once_blocked_fixture(tmp_path=tmp_path, monkeypatch=monkeypatch, cleanup=cleanup)
    assert not hasattr(captured.value, "child_cleanup")


@pytest.mark.parametrize("target", ["process", "publication"])
def test_run_once_blocked_child_remeasures_sealed_roots_before_recording_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    process_locator = ".w3-production-" + "a" * 24
    trusted_locator = ".w3-trusted-" + "b" * 24
    publication_locator = "qualifications/" + "c" * 64
    physical = (
        tmp_path / "run" / process_locator
        if target == "process"
        else tmp_path / "artifacts" / publication_locator
    )
    physical.mkdir(parents=True, mode=0o700)
    (tmp_path / "run").mkdir(mode=0o700, exist_ok=True)
    (tmp_path / "run").chmod(0o700)
    (tmp_path / "artifacts").mkdir(mode=0o700, exist_ok=True)
    (tmp_path / "artifacts").chmod(0o700)
    qualifications = tmp_path / "artifacts" / "qualifications"
    if qualifications.exists():
        qualifications.chmod(0o700)
    rogue = physical / "rogue"
    rogue.write_bytes(b"rogue-bytes")
    rogue.chmod(0o444)
    physical.chmod(0o555)
    forged = _blocked_retained_root_fixture(
        kind=(
            "production-process-root"
            if target == "process"
            else "qualification-publication-partial-root"
        ),
        logical_root=("process" if target == "process" else "qualification-publication-partial"),
        anchor=("run-root" if target == "process" else "artifact-root"),
        locator=(process_locator if target == "process" else publication_locator),
        digest_character="0",
    )
    forged["counts"] = {"files": 0, "directories": 1, "bytes": 0}
    forged["root_id"] = GATE.canonical_hash(
        {key: value for key, value in forged.items() if key != "root_id"}
    )
    if target == "process":
        roots = [forged]
    else:
        roots = [
            _blocked_retained_root_fixture(
                kind="production-process-root",
                logical_root="process",
                anchor="run-root",
                locator=process_locator,
                digest_character="1",
                state="unmeasurable",
            ),
            _blocked_retained_root_fixture(
                kind="production-trusted-root",
                logical_root="trusted",
                anchor="run-root",
                locator=trusted_locator,
                digest_character="2",
                state="unmeasurable",
            ),
            forged,
        ]
    cleanup = {**GATE._empty_cleanup(), "retained_roots": roots}
    with pytest.raises(GATE.BridgeGateBlocked, match="remeasurement differs") as captured:
        _run_once_blocked_fixture(tmp_path=tmp_path, monkeypatch=monkeypatch, cleanup=cleanup)
    assert not hasattr(captured.value, "child_cleanup")


def test_run_once_cross_binds_published_report_and_artifacts(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authority = replay_inputs["authority_value"]
    qualification, artifacts = _qualification(authority)
    stdout = GATE.canonical_json_bytes(qualification) + b"\n"
    artifact_root = tmp_path / "one-run-artifacts"
    artifact_root.mkdir(mode=0o700)
    publication = artifact_root / "qualifications" / qualification["manifest_sha256"][7:]
    publication.mkdir(parents=True)
    for name, raw in artifacts.items():
        target = publication / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o444)
    (publication / "qualification.json").write_bytes(stdout[:-1])
    (publication / "qualification.json").chmod(0o444)
    for directory in sorted(publication.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.chmod(0o555)
    publication.chmod(0o555)
    publication.parent.chmod(0o700)
    observed: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(stdout=stdout, stderr=b"", returncode=0)

    monkeypatch.setattr(GATE, "_execute_qualifier_preimage", fake_execute)
    monkeypatch.setattr(GATE, "_remeasure_child_retained_roots", lambda *_: None)
    artifact_handle = GATE._open_or_create_secure_root(artifact_root, "test artifact root")
    run_handle = GATE._open_or_create_secure_root(tmp_path / "run", "test run root")
    try:
        _, measured, measured_artifacts = GATE._run_once(
            python=Path(sys.executable).resolve(),
            qualifier=Path(replay_inputs["qualifier_path"]).resolve(),
            qualifier_preimage=Path(replay_inputs["qualifier_path"]).read_bytes(),
            authority=Path(replay_inputs["authority_path"]).resolve(),
            authority_value=authority,
            authority_sha256=authority["manifest_sha256"],
            source_bundle=Path(replay_inputs["source_bundle_root"]),
            dependency_bundle=Path(replay_inputs["dependency_bundle_root"]),
            capsule=Path(replay_inputs["capsule_root"]),
            artifact_root=artifact_handle,
            run_root=run_handle,
            nonce="0" * 64,
            timeout=1.0,
        )
    finally:
        run_handle.close()
        artifact_handle.close()
    assert measured == qualification
    assert measured_artifacts == artifacts
    assert observed["expected_child_roles"] == GATE.BRIDGE_CHILD_ROLES
    assert observed["timeout"] == 6.0 + GATE.BRIDGE_SUPERVISION_OVERHEAD_SECONDS


def test_run_once_publication_parent_swap_reads_fd_tree_and_fails_closed(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authority = replay_inputs["authority_value"]
    qualification, artifacts = _qualification(authority)
    stdout = GATE.canonical_json_bytes(qualification) + b"\n"
    artifact_parent = tmp_path / "publication-parent"
    artifact_parent.mkdir(mode=0o700)
    artifact_root = artifact_parent / "artifacts"
    artifact_root.mkdir(mode=0o700)
    publication = artifact_root / "qualifications" / qualification["manifest_sha256"][7:]
    publication.mkdir(parents=True)
    for name, raw in artifacts.items():
        target = publication / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o444)
    report_path = publication / "qualification.json"
    report_path.write_bytes(stdout[:-1])
    report_path.chmod(0o444)
    for directory in sorted(publication.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.chmod(0o555)
    publication.chmod(0o555)
    publication.parent.chmod(0o700)
    displaced = tmp_path / "publication-parent-displaced"
    outside = tmp_path / "publication-outside"
    outside.mkdir(mode=0o700)
    artifact_handle = GATE._open_or_create_secure_root(artifact_root, "test artifact root")
    run_handle = GATE._open_or_create_secure_root(tmp_path / "run", "test run root")
    original_open = GATE._open_child_directory
    swapped = False

    def racing_open(
        parent: object,
        name: str,
        label: str,
        *,
        mode: int = 0o700,
        create: bool = True,
        exist_ok: bool = False,
    ) -> object:
        nonlocal swapped
        if not swapped and parent is artifact_handle and name == "qualifications":
            artifact_parent.rename(displaced)
            artifact_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(
            parent,
            name,
            label,
            mode=mode,
            create=create,
            exist_ok=exist_ok,
        )

    monkeypatch.setattr(
        GATE,
        "_execute_qualifier_preimage",
        lambda **_kwargs: SimpleNamespace(stdout=stdout, stderr=b"", returncode=0),
    )
    monkeypatch.setattr(GATE, "_remeasure_child_retained_roots", lambda *_: None)
    monkeypatch.setattr(GATE, "_open_child_directory", racing_open)
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="pathname was replaced"):
            GATE._run_once(
                python=Path(sys.executable).resolve(),
                qualifier=Path(replay_inputs["qualifier_path"]).resolve(),
                qualifier_preimage=Path(replay_inputs["qualifier_path"]).read_bytes(),
                authority=Path(replay_inputs["authority_path"]).resolve(),
                authority_value=authority,
                authority_sha256=authority["manifest_sha256"],
                source_bundle=Path(replay_inputs["source_bundle_root"]),
                dependency_bundle=Path(replay_inputs["dependency_bundle_root"]),
                capsule=Path(replay_inputs["capsule_root"]),
                artifact_root=artifact_handle,
                run_root=run_handle,
                nonce="0" * 64,
                timeout=1.0,
            )
        assert swapped
        assert list(outside.iterdir()) == []
    finally:
        run_handle.close()
        artifact_handle.close()
        if artifact_parent.is_symlink():
            artifact_parent.unlink()
        if displaced.exists():
            displaced.rename(artifact_parent)


def test_run_once_reasserts_publication_identity_after_fd_snapshot(
    replay_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authority = replay_inputs["authority_value"]
    qualification, artifacts = _qualification(authority)
    stdout = GATE.canonical_json_bytes(qualification) + b"\n"
    artifact_root = tmp_path / "publication-identity-artifacts"
    artifact_root.mkdir(mode=0o700)
    namespace = artifact_root / "qualifications"
    publication = namespace / qualification["manifest_sha256"][7:]
    publication.mkdir(parents=True)
    for name, raw in artifacts.items():
        target = publication / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o444)
    report_path = publication / "qualification.json"
    report_path.write_bytes(stdout[:-1])
    report_path.chmod(0o444)
    for directory in sorted(publication.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.chmod(0o555)
    publication.chmod(0o555)
    namespace.chmod(0o700)
    displaced = namespace / "publication-displaced"
    outside = tmp_path / "publication-identity-outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve-exact")
    artifact_handle = GATE._open_or_create_secure_root(artifact_root, "test artifact root")
    run_handle = GATE._open_or_create_secure_root(tmp_path / "run", "test run root")
    original_snapshot = GATE._snapshot_publication_descriptor
    swapped = False

    def racing_snapshot(
        descriptor: int,
        expected_files: set[str],
    ) -> dict[str, bytes]:
        nonlocal swapped
        snapshot = original_snapshot(descriptor, expected_files)
        if not swapped:
            publication.chmod(0o700)
            publication.rename(displaced)
            displaced.chmod(0o555)
            publication.symlink_to(outside, target_is_directory=True)
            swapped = True
        return snapshot

    monkeypatch.setattr(
        GATE,
        "_execute_qualifier_preimage",
        lambda **_kwargs: SimpleNamespace(stdout=stdout, stderr=b"", returncode=0),
    )
    monkeypatch.setattr(GATE, "_remeasure_child_retained_roots", lambda *_: None)
    monkeypatch.setattr(GATE, "_snapshot_publication_descriptor", racing_snapshot)
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="pathname was replaced"):
            GATE._run_once(
                python=Path(sys.executable).resolve(),
                qualifier=Path(replay_inputs["qualifier_path"]).resolve(),
                qualifier_preimage=Path(replay_inputs["qualifier_path"]).read_bytes(),
                authority=Path(replay_inputs["authority_path"]).resolve(),
                authority_value=authority,
                authority_sha256=authority["manifest_sha256"],
                source_bundle=Path(replay_inputs["source_bundle_root"]),
                dependency_bundle=Path(replay_inputs["dependency_bundle_root"]),
                capsule=Path(replay_inputs["capsule_root"]),
                artifact_root=artifact_handle,
                run_root=run_handle,
                nonce="0" * 64,
                timeout=1.0,
            )
        assert swapped
        assert publication.is_symlink()
        assert displaced.is_dir()
        assert sentinel.read_bytes() == b"preserve-exact"
        assert sorted(item.name for item in outside.iterdir()) == ["sentinel"]
    finally:
        run_handle.close()
        artifact_handle.close()
        if publication.is_symlink():
            publication.unlink()
        if displaced.exists():
            displaced.chmod(0o700)
            displaced.rename(publication)
            publication.chmod(0o555)


def test_qualification_and_artifact_cross_binding_fail_closed(
    replay_inputs: dict[str, object],
) -> None:
    authority = replay_inputs["authority_value"]
    qualification, artifacts = _qualification(authority)
    qualification["authority_manifest_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._validate_qualification(qualification, authority, authority["manifest_sha256"])

    qualification, artifacts = _qualification(authority)
    row = qualification["executions"][0]
    raw = artifacts[row["artifact_path"]]
    drifted = deepcopy(row)
    drifted["request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._validate_artifact(raw, drifted, authority)


def test_authority_duplicate_key_and_noncanonical_bytes_fail_closed(
    replay_inputs: dict[str, object], tmp_path: Path
) -> None:
    authority = replay_inputs["authority_value"]
    launcher = authority["project"]["launcher"]
    raw = GATE.canonical_json_bytes(authority)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema_version":2,' + raw[1:])
    with pytest.raises(GATE.BridgeGateBlocked, match="duplicate key"):
        GATE._load_authority(duplicate, authority["manifest_sha256"], launcher)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(authority, indent=2))
    with pytest.raises(GATE.BridgeGateBlocked, match="not canonical"):
        GATE._load_authority(noncanonical, authority["manifest_sha256"], launcher)


@pytest.mark.parametrize("mutation", ["boolean-role", "noncanonical-path"])
def test_authority_rejects_boolean_counts_and_noncanonical_lexical_paths(
    replay_inputs: dict[str, object], tmp_path: Path, mutation: str
) -> None:
    authority = deepcopy(replay_inputs["authority_value"])
    if mutation == "boolean-role":
        authority["expected"]["roles"]["author"] = True
    else:
        source = authority["source_bundle"]
        source["files"][0]["path"] = "runtime//w3_production_worker.py"
        source["roster_sha256"] = GATE.canonical_hash(source["files"])
        source_body = {key: item for key, item in source.items() if key != "manifest_sha256"}
        source["manifest_sha256"] = GATE.canonical_hash(source_body)
    authority_body = {key: item for key, item in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = GATE.canonical_hash(authority_body)
    path = tmp_path / f"authority-{mutation}.json"
    path.write_bytes(GATE.canonical_json_bytes(authority))
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._load_authority(
            path,
            authority["manifest_sha256"],
            replay_inputs["authority_value"]["project"]["launcher"],
        )


def test_authority_rejects_integer_ratification_independent_after_rehash(
    replay_inputs: dict[str, object], tmp_path: Path
) -> None:
    authority = deepcopy(replay_inputs["authority_value"])
    authority["ratification"]["independent"] = 1
    authority_body = {key: item for key, item in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = GATE.canonical_hash(authority_body)
    path = tmp_path / "authority-integer-independent.json"
    path.write_bytes(GATE.canonical_json_bytes(authority))

    with pytest.raises(GATE.BridgeGateBlocked, match="Kimi report"):
        GATE._load_authority(
            path,
            authority["manifest_sha256"],
            replay_inputs["authority_value"]["project"]["launcher"],
        )


def test_qualification_rejects_boolean_role_count(replay_inputs: dict[str, object]) -> None:
    authority = replay_inputs["authority_value"]
    qualification, _ = _qualification(authority)
    qualification["roles"]["author"] = True
    body = {key: item for key, item in qualification.items() if key != "manifest_sha256"}
    qualification["manifest_sha256"] = GATE.canonical_hash(body)
    with pytest.raises(GATE.BridgeGateBlocked, match="roles drifted"):
        GATE._validate_qualification(qualification, authority, authority["manifest_sha256"])


def test_forged_qualifier_and_empty_authority_are_blocked_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualifier = tmp_path / "forged.py"
    qualifier.write_text("print('forged')\n")
    authority = tmp_path / "authority.json"
    authority.write_text("{}")
    roots = []
    for name in ("source", "dependency", "capsule"):
        root = tmp_path / name
        root.mkdir()
        roots.append(root)
    called = False

    def forbidden(**kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("forged qualifier reached execution")

    monkeypatch.setattr(GATE, "_run_once", forbidden)
    with pytest.raises(GATE.BridgeGateBlocked, match="trust root"):
        GATE.run_replay_gate(
            qualifier_path=qualifier,
            qualifier_sha256=GATE.bytes_hash(qualifier.read_bytes()),
            authority_path=authority,
            authority_sha256="sha256:" + "0" * 64,
            source_bundle_root=roots[0],
            dependency_bundle_root=roots[1],
            capsule_root=roots[2],
            artifact_root=tmp_path / "artifacts",
        )
    assert called is False


def test_one_byte_qualifier_drift_fails_even_with_matching_caller_digest(tmp_path: Path) -> None:
    qualifier = tmp_path / "w3_qualifier.py"
    qualifier.write_bytes(QUALIFIER_PATH.read_bytes() + b"\n")
    authority = tmp_path / "authority.json"
    authority.write_text("{}")
    roots = []
    for name in ("source", "dependency", "capsule"):
        root = tmp_path / name
        root.mkdir()
        roots.append(root)
    with pytest.raises(GATE.BridgeGateBlocked, match="trust root"):
        GATE.run_replay_gate(
            qualifier_path=qualifier,
            qualifier_sha256=GATE.bytes_hash(qualifier.read_bytes()),
            authority_path=authority,
            authority_sha256="sha256:" + "0" * 64,
            source_bundle_root=roots[0],
            dependency_bundle_root=roots[1],
            capsule_root=roots[2],
            artifact_root=tmp_path / "artifacts",
        )


def test_qualification_validation_rejects_fixture_v1_and_nonce_field(
    replay_inputs: dict[str, object],
) -> None:
    authority = replay_inputs["authority_value"]
    fixture, _ = _qualification(authority)
    fixture["qualification_kind"] = "fixture-v1"
    with pytest.raises(GATE.BridgeGateBlocked):
        GATE._validate_qualification(fixture, authority, authority["manifest_sha256"])

    report, _ = _qualification(authority)
    report["run_nonce"] = "0" * 64
    with pytest.raises(GATE.BridgeGateBlocked, match="fields drifted"):
        GATE._validate_qualification(report, authority, authority["manifest_sha256"])


def test_timed_swap_after_measurement_executes_only_the_pinned_preimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualifier = tmp_path / "timed-swap-qualifier.py"
    marker = tmp_path / "executed-marker"
    measured = (
        b'import pathlib,sys\npathlib.Path(sys.argv[1]).write_text("measured",encoding="ascii")\n'
    )
    swapped = (
        b'import pathlib,sys\npathlib.Path(sys.argv[1]).write_text("swapped",encoding="ascii")\n'
    )
    qualifier.write_bytes(measured)
    preimage = GATE._read_regular(qualifier, GATE.MAX_REPORT_BYTES, "timed qualifier")
    monkeypatch.setattr(GATE, "PINNED_QUALIFIER_SHA256", GATE.bytes_hash(preimage))

    qualifier.write_bytes(swapped)
    completed = GATE._execute_qualifier_preimage(
        python=Path(sys.executable).resolve(strict=True),
        qualifier=qualifier,
        qualifier_preimage=preimage,
        arguments=[str(marker)],
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout == completed.stderr == b""
    assert marker.read_text(encoding="ascii") == "measured"
    assert qualifier.read_bytes() == swapped


def test_bridge_timeout_reaps_every_registered_separate_session_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualifier = tmp_path / "registered-children-qualifier.py"
    markers = [tmp_path / "node-child.pid", tmp_path / "worker-child.pid"]
    source = b"""import os
import subprocess
import sys

control_fd = __bridge_control_fd__
control_nonce = __bridge_control_nonce__
with open(sys.argv[3], "w", encoding="ascii") as stream:
    stream.write(str(os.getpid()))

def supervision(role):
    def register():
        os.setsid()
        pid = os.getpid()
        record = f"REGISTER {control_nonce} {role} {pid} {pid} {pid}\\n".encode("ascii")
        os.write(control_fd, record)
        acknowledgement = b""
        while not acknowledgement.endswith(b"\\n"):
            chunk = os.read(control_fd, 512)
            if not chunk:
                os._exit(125)
            acknowledgement += chunk
        if acknowledgement != f"ACK {control_nonce} {pid}\\n".encode("ascii"):
            os._exit(125)
        os.close(control_fd)
    return register

script = (
    "import os,pathlib,sys,time;"
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii');"
    "time.sleep(60)"
)
children = []
for role, marker in (("node:test", sys.argv[1]), ("worker", sys.argv[2])):
    children.append(subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", "-c", script, marker],
        pass_fds=(control_fd,),
        preexec_fn=supervision(role),
    ))
for child in children:
    child.wait()
"""
    qualifier.write_bytes(source)
    monkeypatch.setattr(GATE, "PINNED_QUALIFIER_SHA256", GATE.bytes_hash(source))
    qualifier_marker = tmp_path / "qualifier.pid"

    with pytest.raises(GATE.BridgeGateBlocked, match="supervised timeout"):
        GATE._execute_qualifier_preimage(
            python=Path(sys.executable).resolve(strict=True),
            qualifier=qualifier,
            qualifier_preimage=source,
            arguments=[str(markers[0]), str(markers[1]), str(qualifier_marker)],
            timeout=1.5,
            expected_child_roles=frozenset({"node:test", "worker"}),
        )

    assert all(marker.is_file() for marker in markers)
    for marker in markers:
        pid = int(marker.read_text(encoding="ascii"))
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
    qualifier_pid = int(qualifier_marker.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(qualifier_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(qualifier_pid, 0)


@pytest.mark.parametrize("late_first_snapshot", [False, True], ids=("normal", "late-first"))
def test_bridge_keyboard_interrupt_reaps_qualifier_and_registered_child_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_first_snapshot: bool
) -> None:
    qualifier = tmp_path / "interrupt-registered-child-qualifier.py"
    qualifier_marker = tmp_path / "interrupt-qualifier.pid"
    child_marker = tmp_path / "interrupt-child.pid"
    source = b"""import os
import subprocess
import sys

control_fd = __bridge_control_fd__
control_nonce = __bridge_control_nonce__
with open(sys.argv[1], "w", encoding="ascii") as stream:
    stream.write(str(os.getpid()))

def register():
    os.setsid()
    pid = os.getpid()
    record = f"REGISTER {control_nonce} worker {pid} {pid} {pid}\\n".encode("ascii")
    os.write(control_fd, record)
    acknowledgement = b""
    while not acknowledgement.endswith(b"\\n"):
        chunk = os.read(control_fd, 512)
        if not chunk:
            os._exit(125)
        acknowledgement += chunk
    if acknowledgement != f"ACK {control_nonce} {pid}\\n".encode("ascii"):
        os._exit(125)
    os.close(control_fd)

script = (
    "import os,pathlib,sys,time;"
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii');"
    "time.sleep(60)"
)
child = subprocess.Popen(
    [sys.executable, "-I", "-S", "-B", "-c", script, sys.argv[2]],
    pass_fds=(control_fd,),
    preexec_fn=register,
)
child.wait()
"""
    qualifier.write_bytes(source)
    monkeypatch.setattr(GATE, "PINNED_QUALIFIER_SHA256", GATE.bytes_hash(source))
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []

    def interrupting_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        spawned.append(process)

        def interrupt(*, input: bytes | None = None, timeout: float | None = None):
            del timeout
            assert process.stdin is not None
            assert input is not None
            process.stdin.write(input)
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if qualifier_marker.is_file() and child_marker.is_file():
                    raise KeyboardInterrupt
                time.sleep(0.01)
            pytest.fail("registered child did not start before injected interrupt")

        process.communicate = interrupt  # type: ignore[method-assign]
        return process

    monkeypatch.setattr(GATE.subprocess, "Popen", interrupting_popen)
    if late_first_snapshot:
        real_registered_groups = GATE._registered_groups
        real_killpg = os.killpg
        snapshot_calls = 0
        permission_injected = False

        def delayed_first_snapshot(registered: dict[str, int], lock: threading.Lock) -> set[int]:
            nonlocal snapshot_calls
            snapshot_calls += 1
            groups = real_registered_groups(registered, lock)
            return set() if snapshot_calls == 1 else groups

        def transient_permission_error(group: int, sig: int) -> None:
            nonlocal permission_injected
            child_pid = int(child_marker.read_text(encoding="ascii"))
            if group == child_pid and sig == signal.SIGKILL and not permission_injected:
                permission_injected = True
                raise PermissionError("injected transient late child kill denial")
            real_killpg(group, sig)

        monkeypatch.setattr(GATE, "_registered_groups", delayed_first_snapshot)
        monkeypatch.setattr(GATE.os, "killpg", transient_permission_error)
    observed_pids: list[int] = []
    try:
        arguments = {
            "python": Path(sys.executable).resolve(strict=True),
            "qualifier": qualifier,
            "qualifier_preimage": source,
            "arguments": [str(qualifier_marker), str(child_marker)],
            "timeout": 10.0,
            "expected_child_roles": frozenset({"worker"}),
        }
        if late_first_snapshot:
            with pytest.raises(
                GATE.BridgeGateBlocked, match="registered child group cleanup failed"
            ):
                GATE._execute_qualifier_preimage(**arguments)
        else:
            with pytest.raises(KeyboardInterrupt):
                GATE._execute_qualifier_preimage(**arguments)
        assert len(spawned) == 1
        observed_pids = [
            int(child_marker.read_text(encoding="ascii")),
            int(qualifier_marker.read_text(encoding="ascii")),
        ]
        for pid in observed_pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            with pytest.raises(ProcessLookupError):
                os.killpg(pid, 0)
        if late_first_snapshot:
            assert snapshot_calls >= 2
            assert permission_injected is True
    finally:
        for marker in (child_marker, qualifier_marker):
            if marker.is_file():
                pid = int(marker.read_text(encoding="ascii"))
                if pid not in observed_pids:
                    observed_pids.append(pid)
        for pid in observed_pids:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, 9)
        for process in spawned:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, 9)
            with contextlib.suppress(ProcessLookupError, subprocess.TimeoutExpired):
                process.wait(timeout=2)


def test_bridge_accepts_exact_six_role_registration_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualifier = tmp_path / "six-role-qualifier.py"
    source = b"""import os
import subprocess

control_fd = __bridge_control_fd__
control_nonce = __bridge_control_nonce__

def supervision(role):
    def register():
        os.setsid()
        pid = os.getpid()
        os.write(
            control_fd,
            f"REGISTER {control_nonce} {role} {pid} {pid} {pid}\\n".encode("ascii"),
        )
        acknowledgement = b""
        while not acknowledgement.endswith(b"\\n"):
            chunk = os.read(control_fd, 512)
            if not chunk:
                os._exit(125)
            acknowledgement += chunk
        if acknowledgement != f"ACK {control_nonce} {pid}\\n".encode("ascii"):
            os._exit(125)
        os.close(control_fd)
    return register

roles = (
    "node:candidate-f1.author",
    "node:candidate-f2.before",
    "node:candidate-f2.after",
    "node:candidate-f3.mutated",
    "node:candidate-f3.fixed",
    "worker",
)
for role in roles:
    child = subprocess.Popen(
        ["/usr/bin/true"],
        pass_fds=(control_fd,),
        preexec_fn=supervision(role),
    )
    if child.wait() != 0:
        raise SystemExit(124)
"""
    qualifier.write_bytes(source)
    monkeypatch.setattr(GATE, "PINNED_QUALIFIER_SHA256", GATE.bytes_hash(source))

    completed = GATE._execute_qualifier_preimage(
        python=Path(sys.executable).resolve(strict=True),
        qualifier=qualifier,
        qualifier_preimage=source,
        arguments=[],
        timeout=5,
        expected_child_roles=GATE.BRIDGE_CHILD_ROLES,
    )

    assert completed.returncode == 0
    assert completed.stdout == completed.stderr == b""


@pytest.mark.parametrize("delivery", ["fragmented", "coalesced"])
def test_bridge_registration_parser_handles_bounded_stream_frames(
    delivery: str,
) -> None:
    nonce = "b" * 64
    roles = ("node:a", "worker")
    children = [
        subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "-c", "import time;time.sleep(60)"],
            start_new_session=True,
        )
        for _ in roles
    ]
    parent, child = socket.socketpair()
    registered: dict[str, int] = {}
    errors: list[str] = []
    lock = threading.Lock()
    receiver = threading.Thread(
        target=GATE._receive_child_registrations,
        kwargs={
            "control": parent,
            "nonce": nonce,
            "expected_roles": frozenset(roles),
            "registered": registered,
            "errors": errors,
            "lock": lock,
        },
    )
    receiver.start()
    try:
        frames = b"".join(
            f"REGISTER {nonce} {role} {process.pid} {process.pid} {process.pid}\n".encode("ascii")
            for role, process in zip(roles, children, strict=True)
        )
        if delivery == "fragmented":
            for byte in frames:
                child.sendall(bytes([byte]))
        else:
            child.sendall(frames)
        acknowledgements = b""
        while acknowledgements.count(b"\n") < len(roles):
            acknowledgements += child.recv(512)
        child.shutdown(socket.SHUT_WR)
        receiver.join(timeout=3)
        assert not receiver.is_alive()
        assert errors == []
        assert registered == {
            role: process.pid for role, process in zip(roles, children, strict=True)
        }
        assert acknowledgements.count(b"ACK ") == len(roles)
    finally:
        child.close()
        parent.close()
        GATE._kill_registered_groups({process.pid for process in children})
        for process in children:
            process.wait(timeout=3)


@pytest.mark.parametrize("mutation", ["unexpected", "duplicate"])
def test_bridge_rejects_unexpected_or_duplicate_child_registration(mutation: str) -> None:
    nonce = "c" * 64
    children = [
        subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "-c", "import time;time.sleep(60)"],
            start_new_session=True,
        )
        for _ in range(2)
    ]
    parent, child = socket.socketpair()
    registered: dict[str, int] = {}
    errors: list[str] = []
    lock = threading.Lock()
    receiver = threading.Thread(
        target=GATE._receive_child_registrations,
        kwargs={
            "control": parent,
            "nonce": nonce,
            "expected_roles": frozenset({"node:a", "worker"}),
            "registered": registered,
            "errors": errors,
            "lock": lock,
        },
    )
    receiver.start()
    try:
        first_role = "unexpected" if mutation == "unexpected" else "node:a"
        first = children[0].pid
        child.sendall(f"REGISTER {nonce} {first_role} {first} {first} {first}\n".encode("ascii"))
        if mutation == "duplicate":
            acknowledgement = b""
            while not acknowledgement.endswith(b"\n"):
                acknowledgement += child.recv(512)
            second = children[1].pid
            child.sendall(f"REGISTER {nonce} node:a {second} {second} {second}\n".encode("ascii"))
        receiver.join(timeout=3)
        assert not receiver.is_alive()
        assert errors
        assert (
            "role is invalid" in errors[0]
            if mutation == "unexpected"
            else "duplicated" in errors[0]
        )
    finally:
        child.close()
        parent.close()
        GATE._kill_registered_groups({process.pid for process in children})
        for process in children:
            process.wait(timeout=3)


def test_bridge_bootstrap_and_execution_policy_pins_match_qualifier_bytes() -> None:
    assert GATE.QUALIFIER_BOOTSTRAP_SHA256 == QUALIFIER.V2_QUALIFIER_BOOTSTRAP_SHA256
    assert (
        GATE.PINNED_CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"]
        == QUALIFIER.V2_NODE_SANDBOX_POLICY_TEMPLATE_SHA256
    )
    assert (
        GATE.PINNED_CAPSULE_EXECUTION_POLICY["capsule_ancestor_slots"]
        == QUALIFIER.V2_CAPSULE_ANCESTOR_SLOTS
    )


@pytest.mark.parametrize(
    "field",
    [
        "qualifier_path",
        "authority_path",
        "source_bundle_root",
        "dependency_bundle_root",
        "capsule_root",
        "artifact_root",
    ],
)
def test_bridge_rejects_symlink_in_every_external_input_parent(
    replay_inputs: dict[str, object], tmp_path: Path, field: str
) -> None:
    arguments = _gate_arguments(replay_inputs)
    original = Path(arguments[field])
    alias = tmp_path / f"{field}-parent-alias"
    alias.symlink_to(original.parent, target_is_directory=True)
    arguments[field] = alias / original.name

    with pytest.raises(GATE.BridgeGateBlocked, match="ancestry contains a symlink"):
        GATE.run_replay_gate(**arguments)


def test_bridge_missing_artifact_root_parent_swap_writes_nothing_outside(
    replay_inputs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _gate_arguments(replay_inputs)
    parent = tmp_path / "bridge-artifact-parent"
    parent.mkdir(mode=0o700)
    displaced = tmp_path / "bridge-artifact-parent-displaced"
    outside = tmp_path / "bridge-artifact-outside"
    outside.mkdir(mode=0o700)
    arguments["artifact_root"] = parent / "artifacts"
    original_mkdir = GATE.os.mkdir
    swapped = False

    def racing_mkdir(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped and name == "artifacts" and dir_fd is not None:
            parent.rename(displaced)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(GATE.os, "mkdir", racing_mkdir)
    monkeypatch.setattr(
        GATE,
        "_run_once",
        lambda **_: pytest.fail("qualifier must not start after artifact root swap"),
    )
    try:
        with pytest.raises(GATE.BridgeGateBlocked, match="pathname was replaced"):
            GATE.run_replay_gate(**arguments)
        assert swapped
        assert list(outside.iterdir()) == []
    finally:
        if parent.is_symlink():
            parent.unlink()
        if displaced.exists():
            displaced.rename(parent)


@pytest.mark.parametrize("mode", [0o777, 0o555])
def test_bridge_existing_artifact_root_requires_exact_private_mode(
    tmp_path: Path,
    mode: int,
) -> None:
    artifact = tmp_path / "bridge-artifact-mode"
    artifact.mkdir(mode=mode)
    artifact.chmod(mode)
    with pytest.raises(GATE.BridgeGateBlocked, match="exact mode 700"):
        GATE._open_or_create_secure_root(artifact, "replay artifact root")


def test_bridge_pin_matches_final_qualifier_bytes() -> None:
    assert GATE.bytes_hash(QUALIFIER_PATH.read_bytes()) == GATE.PINNED_QUALIFIER_SHA256


def test_replay_blocked_report_is_schema_valid() -> None:
    blocked = GATE._blocked("typed failure")
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(Draft202012Validator(schema).iter_errors(blocked)) == []
