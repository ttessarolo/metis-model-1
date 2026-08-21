from __future__ import annotations

import contextlib
import importlib.util
import inspect
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path, PurePosixPath

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
QUALIFIER_PATH = PROJECT_ROOT / "runtime/w3_qualifier.py"
QUALIFICATION_SCHEMA = PROJECT_ROOT / "schemas/w3-qualification.schema.json"
SOURCE_CHECKPOINT_REVISION = "5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7"
FORMER_HANDOFF_REVISION = "4ec625fcec8a9c41423bc048688d17775e57353c"

SPEC = importlib.util.spec_from_file_location("w3_qualifier_under_test", QUALIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
QUALIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALIFIER
SPEC.loader.exec_module(QUALIFIER)

WORKER_PATH = PROJECT_ROOT / "runtime/w3_production_worker.py"
WORKER_SPEC = importlib.util.spec_from_file_location("w3_matrix_worker", WORKER_PATH)
assert WORKER_SPEC is not None and WORKER_SPEC.loader is not None
WORKER = importlib.util.module_from_spec(WORKER_SPEC)
WORKER_SPEC.loader.exec_module(WORKER)

BRIDGE_PATH = PROJECT_ROOT / "runtime/w3_bridge_gate.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("w3_matrix_bridge", BRIDGE_PATH)
assert BRIDGE_SPEC is not None and BRIDGE_SPEC.loader is not None
BRIDGE = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(BRIDGE)

BRIDGE_TEST_PATH = PROJECT_ROOT / "tests/test_w3_bridge_gate.py"
BRIDGE_TEST_SPEC = importlib.util.spec_from_file_location(
    "w3_matrix_bridge_fixtures", BRIDGE_TEST_PATH
)
assert BRIDGE_TEST_SPEC is not None and BRIDGE_TEST_SPEC.loader is not None
BRIDGE_FIXTURES = importlib.util.module_from_spec(BRIDGE_TEST_SPEC)
BRIDGE_TEST_SPEC.loader.exec_module(BRIDGE_FIXTURES)


WORKER_TEMPLATE = r"""
import copy
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

MODE = __MODE__
PREFIX = "sha256:"


def canonical(value):
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value):
    return PREFIX + hashlib.sha256(canonical(value)).hexdigest()


def bytes_digest(value):
    return PREFIX + hashlib.sha256(value).hexdigest()


if (
    "CALLER_POISON" in os.environ
    or not sys.flags.isolated
    or not sys.flags.no_site
    or not sys.flags.dont_write_bytecode
):
    raise SystemExit(41)
if any("site-packages" in item for item in sys.path):
    raise SystemExit(42)
if MODE == "timeout":
    time.sleep(5)
if MODE == "oversize_stdout":
    sys.stdout.buffer.write(b"x" * (8 * 1024 * 1024 + 1))
    raise SystemExit(43)
if MODE == "external_read":
    Path("/etc/hosts").read_bytes()

raw_input = sys.stdin.buffer.read()
request = json.loads(raw_input)
bundle = Path(os.environ["W3_QUALIFIER_BUNDLE"])
output_root = Path(os.environ["W3_QUALIFIER_OUTPUT_ROOT"])
registry = json.loads((bundle / "manifests/registry.json").read_text(encoding="utf-8"))
specs = {item["candidate_id"]: item for item in registry["specs"]}
executions = []

for expected in request["executions"]:
    candidate_id = expected["candidate_id"]
    family = expected["family"]
    role = expected["role"]
    truth = specs[candidate_id]["semantic_spec"]["truth"]
    diagnostics = {"parser": [], "link": [], "validation": [], "all": []}
    failure = None
    ir_value = None
    endpoint = {"name": None, "count": 0}
    if family == "F-1":
        ir_value = copy.deepcopy(truth["expected_ir"])
        endpoint = {"name": truth["expected_endpoint"], "count": 1}
    elif family == "F-2":
        key = "expected_before_ir" if role == "before" else "expected_after_ir"
        ir_value = copy.deepcopy(truth[key])
        endpoint = {"name": truth["expected_endpoint"], "count": 1}
    elif role == "mutated":
        diagnostics = copy.deepcopy(truth["expected_diagnostics"])
        failure = copy.deepcopy(truth["expected_failure"])
        if MODE == "f3_invalid_endpoint":
            endpoint = {"name": "forged.endpoint", "count": 999}
    else:
        ir_value = copy.deepcopy(truth["expected_fixed_ir"])
        endpoint = {"name": truth["expected_endpoint"], "count": 1}

    if MODE == "truth_f1" and family == "F-1":
        ir_value["variants"][0]["name"] = "forged"
    if MODE == "truth_f2" and family == "F-2" and role == "after":
        ir_value["variants"][0]["takes"][0]["count"]["take"] = 99
    if MODE == "truth_f3" and family == "F-3" and role == "mutated":
        diagnostics["parser"][0]["message"] += " forged"
    if MODE == "malformed_diagnostic" and family == "F-1":
        diagnostics["validation"] = ["not-a-diagnostic"]
        diagnostics["all"] = ["not-a-diagnostic"]

    ast_inventory = {"candidate_id": candidate_id, "family": family, "role": role}
    result = {
        "schema_version": 1,
        "status": expected["expected_status"],
        "endpoint": endpoint,
        "diagnostics": diagnostics,
        "ast": {"inventory": ast_inventory, "signature": digest(ast_inventory)},
        "ir": {"value": ir_value, "signature": None if ir_value is None else digest(ir_value)},
        "toolchain": request["toolchain"],
        "runtime": request["runtime_identity"],
        "failure": failure,
    }
    if MODE == "bool_schema_count" and family == "F-1":
        result["schema_version"] = True
        result["endpoint"]["count"] = True
    evidence = {
        "input_sha256": digest(expected["request"]),
        "diagnostics_sha256": digest(diagnostics),
        "ast_sha256": digest(ast_inventory),
        "ir_sha256": None if ir_value is None else digest(ir_value),
        "toolchain_revision": request["toolchain"]["revision"],
        "toolchain_tree": request["toolchain"]["tree"],
        "runtime_sha256": digest(request["runtime_identity"]),
        "runtime_identity": request["runtime_identity"],
        "runner_sha256": request["evidence_pins"]["runner_sha256"],
        "tooling_package_sha256": request["evidence_pins"]["tooling_package_sha256"],
        "tooling_lock_sha256": request["evidence_pins"]["tooling_lock_sha256"],
        "node_modules_sha256": request["evidence_pins"]["node_modules_sha256"],
        "node_binary_sha256": request["evidence_pins"]["node_binary_sha256"],
        "sandbox_policy_sha256": request["evidence_pins"]["sandbox_policy_sha256"],
        "metis_status_sha256": request["evidence_pins"]["metis_status_sha256"],
        "metis_status": "fixture-clean",
    }
    envelope = {"schema_version": 1, "result": result, "evidence": evidence}
    if MODE == "bool_schema_count" and family == "F-1":
        envelope["schema_version"] = True
    evidence["envelope_sha256"] = digest(envelope)
    artifact_path = f"artifacts/{candidate_id}-{role}.json"
    artifact = output_root / artifact_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact_bytes = canonical(envelope)
    if MODE == "artifact_tamper" and not executions:
        artifact_bytes = b"tampered"
    artifact.write_bytes(artifact_bytes)
    if MODE == "artifact_mode_tamper" and not executions:
        artifact.chmod(0o644)
    if MODE == "oversize_artifact" and not executions:
        artifact.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    if MODE == "artifact_symlink" and not executions:
        artifact.unlink()
        artifact.symlink_to("/etc/hosts")
    executions.append(
        {
            "candidate_id": candidate_id,
            "family": family,
            "role": role,
            "request": expected["request"],
            "request_sha256": digest(expected["request"]),
            "envelope": envelope,
            "envelope_sha256": digest(envelope),
            "result_sha256": digest(result),
            "artifact_path": artifact_path,
            "artifact_sha256": bytes_digest(artifact_bytes),
        }
    )

if MODE == "request_hash_tamper":
    executions[0]["request_sha256"] = digest("forged")
if MODE == "mixed_role":
    executions[1]["role"] = executions[0]["role"]
if MODE == "artifact_path_bad":
    executions[0]["artifact_path"] = "artifacts/bad id.json"

roles = dict(sorted(Counter(item["role"] for item in executions).items()))
counts = {
    "candidates": len({item["candidate_id"] for item in executions}),
    "executions": len(executions),
    "distinct": len({(item["candidate_id"], item["role"]) for item in executions}),
    "gaps": 0,
}
if MODE == "count_tamper":
    counts["executions"] = 4
output = {
    "schema_version": 1,
    "protocol": request["protocol"],
    "authority_manifest_sha256": request["authority_manifest_sha256"],
    "bundle_sha256": request["bundle_sha256"],
    "input_sha256": bytes_digest(raw_input),
    "status": "completed",
    "matched": MODE != "matched_false",
    "executions": executions,
    "counts": counts,
    "roles": roles,
}
output["run_sha256"] = digest(output)
if MODE == "run_hash_tamper":
    output["run_sha256"] = digest("forged")
if MODE == "bundle_tamper":
    target = bundle / "src/metis_model1/w3_builder.py"
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
if MODE == "fork_delayed_corruption":
    child = os.fork()
    if child == 0:
        for descriptor in (0, 1, 2):
            try:
                os.close(descriptor)
            except OSError:
                pass
        time.sleep(0.4)
        first = output_root / executions[0]["artifact_path"]
        first.chmod(0o600)
        first.write_bytes(b"delayed corruption")
        os._exit(0)
if MODE == "noncanonical_stdout":
    sys.stdout.write(json.dumps(output, indent=2))
else:
    sys.stdout.buffer.write(canonical(output))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + __import__("hashlib").sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def _manifest_hash(value: dict) -> str:
    return _hash({key: item for key, item in value.items() if key != "manifest_sha256"})


def _normalized_retained_report(value: dict) -> dict:
    normalized = deepcopy(value)
    normalized.pop("manifest_sha256", None)
    for root in normalized["cleanup"]["retained_roots"]:
        root["locator"] = ""
        for field in (
            "physical_roster_sha256",
            "snapshot_first_sha256",
            "snapshot_second_sha256",
            "root_id",
        ):
            if field in root:
                root[field] = "sha256:" + ("0" * 64)
    return normalized


def _copy(path: str, source: Path) -> None:
    destination = source / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / path, destination)


def _fixture(tmp_path: Path, mode: str = "good") -> dict[str, object]:
    source = tmp_path / "source"
    source.mkdir()
    copied = {
        "src/metis_model1/w3_builder.py": "w3",
        "src/metis_model1/w3_oracles.py": "w3",
        "src/metis_model1/w3_production_adapter.py": "w3",
        "src/metis_model1/oracles.py": "w3",
        "src/metis_model1/provenance.py": "w3",
        "schemas/oracle-result.schema.json": "schema",
        "schemas/w3-run.schema.json": "schema",
        "schemas/w3-source-register.schema.json": "schema",
        "schemas/w3-semantic-spec.schema.json": "schema",
        "schemas/w3-qualification.schema.json": "schema",
        "runtime/metis_oracle/runner.ts": "runner",
    }
    for path in copied:
        _copy(path, source)
    candidate_path = "manifests/candidates.json"
    registry_path = "manifests/registry.json"
    (source / "manifests").mkdir()
    shutil.copy2(PROJECT_ROOT / "manifests/w3-f1-f3-smoke-candidates.json", source / candidate_path)
    shutil.copy2(
        PROJECT_ROOT / "manifests/w3-f1-f3-smoke-semantic-specs.json",
        source / registry_path,
    )
    copied[candidate_path] = "manifest"
    copied[registry_path] = "manifest"
    worker_path = "worker/fixture_worker.py"
    (source / "worker").mkdir()
    (source / worker_path).write_text(WORKER_TEMPLATE.replace("__MODE__", repr(mode)))
    copied[worker_path] = "worker"

    candidates = json.loads((source / candidate_path).read_text())
    registry = json.loads((source / registry_path).read_text())
    assert candidates["manifest_sha256"] == _manifest_hash(candidates)
    assert registry["manifest_sha256"] == _manifest_hash(registry)
    evidence_pins = {
        "runner_sha256": _file_hash(source / "runtime/metis_oracle/runner.ts"),
        "tooling_package_sha256": _hash("fixture-tooling-package"),
        "tooling_lock_sha256": _hash("fixture-tooling-lock"),
        "node_modules_sha256": _hash("fixture-node-modules"),
        "node_binary_sha256": _hash("fixture-node"),
        "sandbox_policy_sha256": _hash("fixture-policy"),
        "metis_status_sha256": _hash("fixture-clean"),
    }
    snapshot = (
        "snapshot://a2dde2b191f6b78c2003d74875560da782470968/"
        "75473e26deff4084a0eb077a4c3e27d52dc07998"
    )
    runtime_identity = {
        "node": "v22.22.3",
        "node_path": "node://v22.22.3",
        "tsx_path": f"{snapshot}/tooling/node_modules/tsx/dist/loader.mjs",
        "runner_path": f"{snapshot}/.metis-oracle/runner.ts",
        "snapshot_revision": "a2dde2b191f6b78c2003d74875560da782470968",
        "snapshot_tree": "75473e26deff4084a0eb077a4c3e27d52dc07998",
        "tooling_package_sha256": evidence_pins["tooling_package_sha256"],
        "tooling_lock_sha256": evidence_pins["tooling_lock_sha256"],
        "node_modules_sha256": evidence_pins["node_modules_sha256"],
        "node_binary_sha256": evidence_pins["node_binary_sha256"],
        "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
        "sandbox_policy_version": "2",
        "sandbox_policy_sha256": evidence_pins["sandbox_policy_sha256"],
    }
    body = {
        "schema_version": 1,
        "authority_id": "fixture-independent-authority-v1",
        "status": "independently_ratified",
        "semantic_registry": {
            "path": registry_path,
            "manifest_sha256": registry["manifest_sha256"],
            "ratification": {
                "status": "independently_ratified",
                "author_id": "fixture-author",
                "ratifier_id": "fixture-independent-reviewer",
                "independent": True,
                "evidence_sha256": _hash("fixture-review-evidence"),
            },
        },
        "candidate_manifest": {
            "path": candidate_path,
            "manifest_sha256": candidates["manifest_sha256"],
        },
        "worker": {"path": worker_path, "protocol": "w3-clean-process-v1"},
        "launcher": QUALIFIER._launcher_identity(),
        "toolchain": {
            "revision": "a2dde2b191f6b78c2003d74875560da782470968",
            "tree": "75473e26deff4084a0eb077a4c3e27d52dc07998",
            "language_version": "0.43",
        },
        "runtime_identity": runtime_identity,
        "evidence_pins": evidence_pins,
        "bundle_files": [
            {"path": path, "kind": kind, "file_sha256": _file_hash(source / path)}
            for path, kind in sorted(copied.items())
        ],
        "expected": {
            "candidates": 3,
            "executions": 5,
            "roles": {"author": 1, "before": 1, "after": 1, "mutated": 1, "fixed": 1},
        },
    }
    authority = {**body, "manifest_sha256": _hash(body)}
    authority_path = tmp_path / "authority.json"
    authority_path.write_bytes(_canonical(authority))
    return {
        "source": source,
        "artifact": tmp_path / "artifact",
        "authority": authority,
        "authority_path": authority_path,
        "authority_sha256": authority["manifest_sha256"],
    }


def _refresh_fixture_manifests(fixture: dict[str, object]) -> None:
    source = Path(fixture["source"])
    candidate_path = source / "manifests/candidates.json"
    registry_path = source / "manifests/registry.json"
    candidates = json.loads(candidate_path.read_text())
    registry = json.loads(registry_path.read_text())
    for candidate, spec in zip(candidates["candidates"], registry["specs"], strict=True):
        semantic_hash = _hash(spec["semantic_spec"])
        spec["semantic_spec_sha256"] = semantic_hash
        candidate["root_evidence"]["semantic_spec_sha256"] = semantic_hash
        content_hash = _hash(QUALIFIER._candidate_content(candidate))
        spec["content_sha256"] = content_hash
        candidate["root_evidence"]["content_sha256"] = content_hash
        spec["spec_sha256"] = _hash(
            {key: value for key, value in spec.items() if key != "spec_sha256"}
        )
    candidates["manifest_sha256"] = _manifest_hash(candidates)
    registry["manifest_sha256"] = _manifest_hash(registry)
    candidate_path.write_bytes(_canonical(candidates))
    registry_path.write_bytes(_canonical(registry))
    authority = fixture["authority"]
    authority["candidate_manifest"]["manifest_sha256"] = candidates["manifest_sha256"]
    authority["semantic_registry"]["manifest_sha256"] = registry["manifest_sha256"]
    for record in authority["bundle_files"]:
        record["file_sha256"] = _file_hash(source / record["path"])
    authority["manifest_sha256"] = _manifest_hash(authority)
    fixture["authority_path"].write_bytes(_canonical(authority))
    fixture["authority_sha256"] = authority["manifest_sha256"]


def _run_cli(
    fixture: dict[str, object],
    *,
    timeout_seconds: float = 2,
    flags: tuple[str, ...] = ("-I", "-S", "-B"),
) -> subprocess.CompletedProcess[bytes]:
    command = [
        sys.executable,
        *flags,
        str(QUALIFIER_PATH),
        "--authority",
        str(fixture["authority_path"]),
        "--authority-sha256",
        str(fixture["authority_sha256"]),
        "--source-root",
        str(fixture["source"]),
        "--artifact-root",
        str(fixture["artifact"]),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    return subprocess.run(command, capture_output=True, check=False)


def _qualify(fixture: dict[str, object], *, timeout_seconds: float = 2) -> dict:
    completed = _run_cli(fixture, timeout_seconds=timeout_seconds)
    assert completed.stderr == b""
    report = json.loads(completed.stdout)
    if completed.returncode != 0:
        raise QUALIFIER.QualificationBlocked(report["reason"])
    assert completed.returncode == 0
    return report


def test_clean_child_ignores_caller_monkeypatch_and_hostile_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    import metis_model1.w3_production_adapter as production_module

    monkeypatch.setattr(
        production_module,
        "run_oracle",
        lambda *_args, **_kwargs: {"forged": True},
    )
    monkeypatch.setenv("CALLER_POISON", "must-not-reach-child")
    report = _qualify(fixture)
    assert report["status"] == "qualified"
    assert report["counts"] == {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0}
    assert report["roles"] == {
        "author": 1,
        "before": 1,
        "after": 1,
        "mutated": 1,
        "fixed": 1,
    }
    assert report["claim"] == "three_candidate_infrastructure_only_no_accuracy_claim"
    assert report["launcher"]["required_flags"] == ["-I", "-S", "-B"]
    assert not any(Path(fixture["artifact"]).glob(".w3-denied-*"))


def test_ambient_public_and_cli_paths_reject_without_required_flags(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="-I -S -B"):
        QUALIFIER.qualify(
            authority_path=fixture["authority_path"],
            authority_sha256=fixture["authority_sha256"],
            source_root=fixture["source"],
            artifact_root=fixture["artifact"],
        )
    completed = _run_cli(fixture, flags=())
    assert completed.returncode == 2
    assert completed.stderr == b""
    blocked = json.loads(completed.stdout)
    assert "-I -S -B" in blocked["reason"]


def test_reviewer_endpoint_registry_substitution_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidates = json.loads((source / "manifests/candidates.json").read_text())
    registry = json.loads((source / "manifests/registry.json").read_text())
    candidates["candidates"][0]["semantic_spec"]["endpoint"] = "play.wrong_subject"
    registry["specs"][0]["semantic_spec"]["endpoint"] = "play.wrong_subject"
    (source / "manifests/candidates.json").write_bytes(_canonical(candidates))
    (source / "manifests/registry.json").write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="semantic endpoint"):
        _qualify(fixture)


def test_reviewer_invalid_candidate_id_blocks_before_worker(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidates = json.loads((source / "manifests/candidates.json").read_text())
    registry = json.loads((source / "manifests/registry.json").read_text())
    candidates["candidates"][0]["candidate_id"] = "bridge f1 author 001"
    registry["specs"][0]["candidate_id"] = "bridge f1 author 001"
    (source / "manifests/candidates.json").write_bytes(_canonical(candidates))
    (source / "manifests/registry.json").write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="invalid row"):
        _qualify(fixture)


@pytest.mark.parametrize(
    "filename",
    ["../outside.metis", "dir/../outside.metis", "/outside.metis", "dir\\outside.metis"],
)
def test_semantic_filename_must_be_a_safe_relative_schema_path(
    tmp_path: Path, filename: str
) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidate_path = source / "manifests/candidates.json"
    registry_path = source / "manifests/registry.json"
    candidates = json.loads(candidate_path.read_text())
    registry = json.loads(registry_path.read_text())
    candidates["candidates"][0]["semantic_spec"]["filename"] = filename
    registry["specs"][0]["semantic_spec"]["filename"] = filename
    candidate_path.write_bytes(_canonical(candidates))
    registry_path.write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="semantic execution contract"):
        _qualify(fixture)


def test_semantic_integer_does_not_accept_boolean(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidate_path = source / "manifests/candidates.json"
    registry_path = source / "manifests/registry.json"
    candidates = json.loads(candidate_path.read_text())
    registry = json.loads(registry_path.read_text())
    candidates["candidates"][1]["semantic_spec"]["truth"]["occurrences"] = True
    registry["specs"][1]["semantic_spec"]["truth"]["occurrences"] = True
    candidate_path.write_bytes(_canonical(candidates))
    registry_path.write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="occurrence count"):
        _qualify(fixture)


@pytest.mark.parametrize("manifest_name", ["candidates.json", "registry.json"])
def test_manifest_schema_version_does_not_accept_boolean(
    tmp_path: Path, manifest_name: str
) -> None:
    fixture = _fixture(tmp_path)
    path = Path(fixture["source"]) / "manifests" / manifest_name
    manifest = json.loads(path.read_text())
    manifest["schema_version"] = True
    path.write_bytes(_canonical(manifest))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="schema version"):
        _qualify(fixture)


def test_f3_failure_kind_must_match_registered_failure(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidate_path = source / "manifests/candidates.json"
    registry_path = source / "manifests/registry.json"
    candidates = json.loads(candidate_path.read_text())
    registry = json.loads(registry_path.read_text())
    candidates["candidates"][2]["semantic_spec"]["truth"]["expected_failure_kind"] = "link"
    candidates["candidates"][2]["expected_diagnostic"]["failure_kind"] = "link"
    registry["specs"][2]["semantic_spec"]["truth"]["expected_failure_kind"] = "link"
    candidate_path.write_bytes(_canonical(candidates))
    registry_path.write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="F-3 semantic truth"):
        _qualify(fixture)


def test_f3_declared_diagnostic_presence_requires_evidence(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = Path(fixture["source"])
    candidate_path = source / "manifests/candidates.json"
    registry_path = source / "manifests/registry.json"
    candidates = json.loads(candidate_path.read_text())
    registry = json.loads(registry_path.read_text())
    empty = {"parser": [], "link": [], "validation": [], "all": []}
    candidates["candidates"][2]["semantic_spec"]["truth"]["expected_diagnostics"] = empty
    registry["specs"][2]["semantic_spec"]["truth"]["expected_diagnostics"] = empty
    candidate_path.write_bytes(_canonical(candidates))
    registry_path.write_bytes(_canonical(registry))
    _refresh_fixture_manifests(fixture)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="F-3 semantic truth"):
        _qualify(fixture)


def test_launcher_recomputes_truth_and_ignores_worker_matched_false(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "matched_false")
    report = _qualify(fixture)
    assert report["status"] == "qualified"
    assert report["counts"]["executions"] == 5


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_unratified_authority_blocks_before_worker(
    tmp_path: Path, missing: bool
) -> None:
    fixture = _fixture(tmp_path)
    artifact = fixture["artifact"]
    if missing:
        fixture["authority_path"] = tmp_path / "missing-authority.json"
    else:
        authority = fixture["authority"]
        authority["semantic_registry"]["ratification"]["status"] = "candidate_for_review"
        authority["manifest_sha256"] = _manifest_hash(authority)
        fixture["authority_path"].write_bytes(_canonical(authority))
        fixture["authority_sha256"] = authority["manifest_sha256"]
    with pytest.raises(QUALIFIER.QualificationBlocked):
        _qualify(fixture)
    assert not Path(artifact).exists()


def test_source_bundle_hash_tamper_blocks_before_worker(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = fixture["source"] / "src/metis_model1/w3_builder.py"
    target.write_bytes(target.read_bytes() + b"\n# source tamper\n")
    with pytest.raises(QUALIFIER.QualificationBlocked, match="differs from its authority"):
        _qualify(fixture)
    assert not Path(fixture["artifact"]).exists()


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("request_hash_tamper", "request hash"),
        ("mixed_role", "duplicate or mixed-role"),
        ("count_tamper", "worker counts"),
        ("run_hash_tamper", "run hash"),
        ("artifact_tamper", "artifact bytes"),
        ("noncanonical_stdout", "not canonical JSON"),
        ("truth_f1", "exact registered truth"),
        ("truth_f2", "exact registered truth"),
        ("truth_f3", "exact registered truth"),
        ("f3_invalid_endpoint", "invalid endpoint count"),
        ("bool_schema_count", "schema version"),
        ("malformed_diagnostic", "diagnostic"),
    ],
)
def test_worker_output_mutations_fail_closed(tmp_path: Path, mode: str, message: str) -> None:
    fixture = _fixture(tmp_path, mode)
    with pytest.raises(QUALIFIER.QualificationBlocked, match=message):
        _qualify(fixture)


def test_live_bundle_tamper_fails_post_worker_remeasurement(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "bundle_tamper")
    with pytest.raises(
        QUALIFIER.QualificationBlocked, match="worker failed|bundled file .* changed"
    ):
        _qualify(fixture)


def test_worker_timeout_is_capped_and_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "timeout")
    with pytest.raises(QUALIFIER.QualificationBlocked, match="timeout cap"):
        _qualify(fixture, timeout_seconds=0.05)


def test_worker_stdout_size_is_capped_and_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "oversize_stdout")
    with pytest.raises(QUALIFIER.QualificationBlocked, match="worker failed|size cap"):
        _qualify(fixture)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("artifact_mode_tamper", "file mode"),
        ("artifact_symlink", "symlink"),
        ("oversize_artifact", "size cap"),
        ("artifact_path_bad", "artifact path"),
    ],
)
def test_publication_symlink_mode_cap_and_path_drift_fail_closed(
    tmp_path: Path, mode: str, message: str
) -> None:
    fixture = _fixture(tmp_path, mode)
    with pytest.raises(QUALIFIER.QualificationBlocked, match=message):
        _qualify(fixture)


def test_sandbox_denies_descendant_fork_before_publication(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "fork_delayed_corruption")
    with pytest.raises(QUALIFIER.QualificationBlocked, match="worker failed"):
        _qualify(fixture)
    assert not (Path(fixture["artifact"]) / "qualifications").exists()


def test_sandbox_denies_external_file_read_before_worker_output(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "external_read")
    with pytest.raises(QUALIFIER.QualificationBlocked, match="worker failed"):
        _qualify(fixture)
    assert not (Path(fixture["artifact"]) / "qualifications").exists()


def test_bundle_namespace_symlink_blocks_without_external_write(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifact = Path(fixture["artifact"])
    outside = tmp_path / "outside"
    artifact.mkdir(mode=0o700)
    outside.mkdir()
    (artifact / "bundles").symlink_to(outside, target_is_directory=True)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="bundle namespace"):
        _qualify(fixture)
    assert list(outside.iterdir()) == []


def test_existing_bundle_mode_tamper_blocks_replay(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _qualify(fixture)
    bundle = next((Path(fixture["artifact"]) / "bundles").iterdir())
    target = bundle / "worker/fixture_worker.py"
    target.chmod(0o644)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="file mode"):
        _qualify(fixture)


def test_authority_input_size_is_capped_before_artifact_creation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["authority_path"].write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(QUALIFIER.QualificationBlocked, match="size cap"):
        _qualify(fixture)
    assert not Path(fixture["artifact"]).exists()


def test_two_fresh_launchers_have_identical_normalized_reports_and_valid_physical_cleanup(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    outputs: list[bytes] = []
    for index in range(2):
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(QUALIFIER_PATH),
            "--authority",
            str(fixture["authority_path"]),
            "--authority-sha256",
            str(fixture["authority_sha256"]),
            "--source-root",
            str(fixture["source"]),
            "--artifact-root",
            str(tmp_path / f"fresh-artifact-{index}"),
            "--timeout-seconds",
            "2",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env={"CALLER_POISON": "x"},
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert completed.stderr == b""
        outputs.append(completed.stdout)
    assert all(output.endswith(b"\n") for output in outputs)
    reports = [json.loads(output) for output in outputs]
    assert _normalized_retained_report(reports[0]) == _normalized_retained_report(reports[1])
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    for report in reports:
        assert list(Draft202012Validator(schema).iter_errors(report)) == []
        assert report["manifest_sha256"] == _manifest_hash(report)
        assert [root["kind"] for root in report["cleanup"]["retained_roots"]] == [
            "worker-process-root"
        ]
        assert report["cleanup"]["delete_attempts"] == 0


def test_report_schema_rejects_lexical_artifact_traversal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _qualify(fixture)
    report["executions"][0]["artifact_path"] = "artifacts/a/../b.json"
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))


def test_qualifier_does_not_register_source_authorities(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _qualify(fixture)
    import metis_model1.w3_builder as builder_module
    import metis_model1.w3_oracles as oracle_module
    import metis_model1.w3_production_adapter as production_module

    assert builder_module.REGISTERED_W3_BENCHMARK_MANIFEST_SHA256 is None
    assert builder_module.REGISTERED_W3_SOURCE_REGISTER_SHA256 is None
    assert oracle_module.REGISTERED_W3_ORACLE_ADAPTER is None
    assert oracle_module.REGISTERED_W3_ORACLE_IDENTITY_SHA256 is None
    assert production_module.REGISTERED_W3_SEMANTIC_REGISTRY_SHA256 is None


def test_blocked_cli_stdout_is_canonical_and_schema_valid(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(QUALIFIER_PATH),
        "--authority",
        str(tmp_path / "missing.json"),
        "--authority-sha256",
        _hash("missing"),
        "--source-root",
        str(PROJECT_ROOT),
        "--artifact-root",
        str(tmp_path / "artifact"),
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    assert completed.returncode == 2
    assert completed.stderr == b""
    assert completed.stdout.endswith(b"\n")
    report = json.loads(completed.stdout)
    assert completed.stdout == _canonical(report) + b"\n"
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report)) == []


def test_missing_cli_arguments_emit_canonical_blocked_report() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(QUALIFIER_PATH)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == b""
    report = json.loads(completed.stdout)
    assert report["status"] == "blocked"
    assert report["reason"].startswith("invalid command line:")
    assert completed.stdout == _canonical(report) + b"\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--mode", "production-capsule-v2", "--timeout-seconds", "not-a-number"],
        ["--mode=production-capsule-v2", "--mode"],
    ],
)
def test_explicit_v2_malformed_cli_always_emits_canonical_v2_blocked(
    arguments: list[str],
) -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(QUALIFIER_PATH), *arguments],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr == b""
    report = json.loads(completed.stdout)
    assert report == QUALIFIER._blocked_v2(report["reason"])
    assert report["qualification_kind"] == "production-capsule-v2"
    assert report["status"] == "blocked"
    assert completed.stdout == _canonical(report) + b"\n"


@pytest.mark.parametrize("abbreviation", ["--mo", "--m"])
def test_cli_abbreviations_are_not_valid_production_mode_selectors(
    tmp_path: Path,
    abbreviation: str,
) -> None:
    missing_authority = tmp_path / "missing-authority.json"
    arguments = [
        f"{abbreviation}=production-capsule-v2" if abbreviation == "--m" else abbreviation,
    ]
    if abbreviation == "--mo":
        arguments.append("production-capsule-v2")
    arguments.extend(
        [
            "--authority",
            str(missing_authority),
            "--authority-sha256",
            _hash("missing-authority"),
            "--source-bundle-root",
            str(tmp_path / "source"),
            "--dependency-bundle-root",
            str(tmp_path / "dependency"),
            "--capsule-root",
            str(tmp_path / "capsule"),
            "--artifact-root",
            str(tmp_path / "artifact"),
            "--run-root",
            str(tmp_path / "run"),
            "--run-nonce",
            "7" * 64,
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(QUALIFIER_PATH), *arguments],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == b""
    report = json.loads(completed.stdout)
    assert report == QUALIFIER._blocked(report["reason"])
    assert "unrecognized arguments" in report["reason"]
    assert completed.stdout == _canonical(report) + b"\n"


V2_MUTATION_MATRIX = {
    "A-authority-kimi": (
        "authority-digest",
        "authority-id",
        "authority-status",
        "kimi-report",
        "kimi-verdict",
        "kimi-scope",
        "kimi-independent",
        "project-revision",
        "candidate-digest",
        "registry-digest",
        "worker-identity",
    ),
    "B-dependency-closure": (
        "dependency-missing",
        "dependency-extra",
        "dependency-symlink",
        "dependency-path",
        "dependency-mode",
        "dependency-size",
        "dependency-hash",
        "dependency-count",
        "dependency-bytes",
        "dependency-roster",
        "dependency-abi",
        "dependency-machine",
    ),
    "C-capsule": (
        "capsule-missing",
        "capsule-extra",
        "capsule-symlink",
        "capsule-path",
        "capsule-mode",
        "capsule-hash",
        "capsule-revision",
        "capsule-tree",
        "capsule-node",
        "capsule-runner",
        "capsule-tooling",
        "capsule-roster",
    ),
    "D-process-policy": (
        "exec-unregistered",
        "exec-node-drift",
        "network-connect",
        "network-bind",
        "read-external",
        "read-source-checkout",
        "write-external",
        "write-source",
        "registered-node-direct-supervised-no-fork",
        "timeout",
        "stdout-cap",
        "stderr-cap",
    ),
    "E-request-envelope-artifact": (
        "request-schema",
        "request-protocol",
        "request-id",
        "request-role",
        "request-family",
        "request-capsule",
        "request-hash",
        "envelope-nonce",
        "envelope-request",
        "envelope-capsule",
        "envelope-result",
        "envelope-manifest",
        "artifact-path",
        "artifact-bytes",
        "artifact-hash",
        "artifact-roster",
    ),
    "F-replay-v1": (
        "replay-report",
        "replay-artifact",
        "replay-role",
        "replay-count",
        "replay-manifest",
        "replay-nonce-scope",
        "fixture-v1-downgrade",
        "v1-regression",
    ),
}


def _descriptor(kind: str) -> dict:
    if kind == "dependency":
        sizes = [1] * 143 + [QUALIFIER.V2_DEPENDENCY_BYTES - 143]
        files = [
            {
                "path": f"pkg/file-{index:03}.py",
                "size": size,
                "mode": 0o444,
                "sha256": "sha256:" + f"{index:064x}",
                "role": "dependency",
            }
            for index, size in enumerate(sizes)
        ]
        body = {
            "schema_version": 2,
            "bundle_id": "pytest-dependency-v2",
            "kind": "dependency",
            "python": dict(QUALIFIER.V2_PYTHON),
            "counts": {"files": 144, "bytes": QUALIFIER.V2_DEPENDENCY_BYTES},
            "files": files,
            "roster_sha256": QUALIFIER.V2_DEPENDENCY_ROSTER_SHA256,
        }
    else:
        files = [
            {
                "path": "runtime/w3_production_worker.py",
                "size": 10,
                "mode": 0o444,
                "sha256": "sha256:" + "1" * 64,
                "role": "worker",
            },
            {
                "path": "manifests/candidates.json",
                "size": 10,
                "mode": 0o444,
                "sha256": "sha256:" + "2" * 64,
                "role": "manifest",
            },
            {
                "path": "manifests/registry.json",
                "size": 10,
                "mode": 0o444,
                "sha256": "sha256:" + "3" * 64,
                "role": "manifest",
            },
        ]
        body = {
            "schema_version": 2,
            "bundle_id": "pytest-source-v2",
            "kind": "source",
            "counts": {"files": 3, "bytes": 30},
            "files": files,
            "roster_sha256": QUALIFIER.canonical_hash(files),
        }
    return {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}


def _capsule_descriptor(monkeypatch: pytest.MonkeyPatch) -> dict:
    files = [
        {
            "path": "bin/node",
            "size": 4,
            "mode": 0o555,
            "sha256": "sha256:" + "a" * 64,
            "role": "node",
        },
        {
            "path": ".metis-oracle/runner.ts",
            "size": 6,
            "mode": 0o444,
            "sha256": "sha256:" + "b" * 64,
            "role": "runner",
        },
        {
            "path": "tooling/node_modules/tsx/dist/loader.mjs",
            "size": 3,
            "mode": 0o444,
            "sha256": "sha256:" + "c" * 64,
            "role": "tsx",
        },
    ]
    monkeypatch.setattr(QUALIFIER, "V2_NODE_BINARY_SHA256", files[0]["sha256"])
    monkeypatch.setattr(QUALIFIER, "V2_RUNNER_SHA256", files[1]["sha256"])
    body = {
        "schema_version": 2,
        "capsule_id": "pytest-capsule-v2",
        "revision": QUALIFIER.PINNED_METIS_REVISION,
        "tree": QUALIFIER.PINNED_METIS_TREE,
        "language_version": "0.43",
        "node": {key: files[0][key] for key in ("path", "sha256", "mode")},
        "runner": {key: files[1][key] for key in ("path", "sha256", "mode")},
        "tsx": {key: files[2][key] for key in ("path", "sha256", "mode")},
        "tooling": {
            "package_sha256": "sha256:f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80",  # noqa: E501
            "lock_sha256": "sha256:fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb",  # noqa: E501
            "node_modules_sha256": "sha256:1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463",  # noqa: E501
        },
        "counts": {"files": 3, "bytes": 13},
        "files": files,
        "roster_sha256": QUALIFIER.canonical_hash(files),
    }
    return {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}


def test_v2_mutation_matrix_is_exact_and_has_no_cosmetic_duplicates() -> None:
    expected = {
        "A-authority-kimi": 11,
        "B-dependency-closure": 12,
        "C-capsule": 12,
        "D-process-policy": 12,
        "E-request-envelope-artifact": 16,
        "F-replay-v1": 8,
    }
    assert {group: len(cases) for group, cases in V2_MUTATION_MATRIX.items()} == expected
    flattened = [case for cases in V2_MUTATION_MATRIX.values() for case in cases]
    assert len(flattened) == len(set(flattened)) == 71
    assert len(V2_EXECUTABLE_MUTATIONS) == len(set(V2_EXECUTABLE_MUTATIONS)) == 71


def _registered_node() -> Path:
    configured = os.environ.get(
        "METIS_MODEL1_NODE", "/Users/tommasotessarolo/.hermes/node/bin/node"
    )
    node = Path(configured).resolve(strict=True)
    assert node.is_file()
    return node


def _v2_live_probe(
    tmp_path: Path,
    worker_source: str,
) -> tuple[list[str], dict[str, str], Path]:
    source = tmp_path / "source"
    dependency = tmp_path / "dependency"
    process_root = tmp_path / "process"
    output_root = process_root / "output"
    worker = source / "src/probe_worker.py"
    for directory in (worker.parent, dependency, output_root):
        directory.mkdir(parents=True, exist_ok=True)
    worker.write_text(worker_source, encoding="utf-8")
    source_manifest = source / "bundle.json"
    dependency_manifest = dependency / "bundle.json"
    source_manifest.write_text("{}", encoding="ascii")
    dependency_manifest.write_text("{}", encoding="ascii")
    denied_read = tmp_path / "denied-read"
    denied_read.write_text("denied", encoding="utf-8")
    denied_write = tmp_path / "denied-write"
    launcher = QUALIFIER._launcher_identity_v2()
    python_root = Path(launcher["python_executable"]).parent.parent.resolve(strict=True)
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "W3_PRODUCTION_SOURCE_BUNDLE": str(source),
        "W3_PRODUCTION_DEPENDENCY_BUNDLE": str(dependency),
        "W3_PRODUCTION_WORKER": str(worker),
        "W3_PRODUCTION_PROCESS_ROOT": str(process_root),
        "W3_PRODUCTION_OUTPUT_ROOT": str(output_root),
        "W3_PRODUCTION_DENIED_WRITE": str(denied_write),
        "W3_PRODUCTION_DENIED_READ": str(denied_read),
        "W3_PRODUCTION_DENIED_SOURCE_WRITE": str(source_manifest),
        "W3_PRODUCTION_DENIED_DEPENDENCY_WRITE": str(dependency_manifest),
        "W3_PRODUCTION_FILE_LIMIT": str(QUALIFIER.MAX_WORKER_STDOUT_BYTES),
        "W3_PROBE_RESULT_PATH": str(process_root / "probe-result"),
    }
    command = [
        launcher["sandbox_exec_path"],
        "-p",
        QUALIFIER.V2_OUTER_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root}",
        "-D",
        f"PYTHON_EXECUTABLE={launcher['python_executable']}",
        "-D",
        f"PYTHON_ROOT={python_root}",
        "-D",
        f"SOURCE_BUNDLE_ROOT={source}",
        "-D",
        f"DEPENDENCY_BUNDLE_ROOT={dependency}",
        launcher["python_executable"],
        "-I",
        "-S",
        "-B",
        "-c",
        QUALIFIER._V2_CHILD_BOOTSTRAP,
    ]
    return command, environment, process_root


def test_v2_live_pure_worker_denies_fork_posix_spawn_and_unregistered_exec(
    tmp_path: Path,
) -> None:
    command, environment, process_root = _v2_live_probe(
        tmp_path,
        """
import errno
import os

blocked = []
try:
    pid = os.fork()
except OSError as error:
    blocked.append(error.errno in {errno.EPERM, errno.EACCES})
else:
    if pid == 0:
        os._exit(93)
    os.waitpid(pid, 0)
    blocked.append(False)
try:
    os.posix_spawn("/usr/bin/true", ["/usr/bin/true"], {})
except OSError as error:
    blocked.append(error.errno in {errno.EPERM, errno.EACCES})
else:
    blocked.append(False)
if blocked != [True, True]:
    raise SystemExit(94)
with open(os.environ["W3_PROBE_RESULT_PATH"], "w", encoding="ascii") as handle:
    handle.write("fork-and-posix-spawn-blocked")
""".strip(),
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=environment,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == completed.stderr == b""
    assert (process_root / "probe-result").read_text() == "fork-and-posix-spawn-blocked"
    # Reaching the worker also proves the bootstrap's /usr/bin/true subprocess
    # canary was denied before any worker code ran.


def _tmp_node_capsule(tmp_path: Path) -> tuple[Path, Path, Path]:
    capsule = tmp_path / "capsule"
    node = capsule / "bin/node"
    process_root = tmp_path / "node-process"
    node.parent.mkdir(parents=True)
    process_root.mkdir(mode=0o700)
    shutil.copy2(_registered_node(), node)
    node.chmod(0o555)
    return capsule, node, process_root


def _node_policy_command(
    capsule: Path,
    node: Path,
    process_root: Path,
    script: str,
    *,
    policy: str | None = None,
) -> list[str]:
    ancestors = QUALIFIER._capsule_ancestor_definitions(capsule)
    ancestor_arguments = [
        argument for name, value in ancestors.items() for argument in ("-D", f"{name}={value}")
    ]
    return [
        str(QUALIFIER.SANDBOX_EXEC_PATH),
        "-p",
        policy or QUALIFIER.V2_NODE_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root}",
        "-D",
        f"NODE_EXECUTABLE={node}",
        "-D",
        f"CAPSULE_ROOT={capsule}",
        *ancestor_arguments,
        str(node),
        "-e",
        script,
    ]


def _assert_pid_absent(pid: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    pytest.fail(f"process {pid} survived supervised cleanup")


def test_v2_live_registered_node_is_exact_supervised_session_leader(tmp_path: Path) -> None:
    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    command = _node_policy_command(
        capsule,
        node,
        process_root,
        "require('fs').writeFileSync(process.argv[1], String(process.pid))",
    ) + [str(process_root / "node.pid")]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        start_new_session=True,
    )
    assert os.getpgid(process.pid) == process.pid
    assert os.getsid(process.pid) == process.pid
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert stdout == stderr == b""
    assert int((process_root / "node.pid").read_text()) == process.pid
    _assert_pid_absent(process.pid)


@pytest.mark.parametrize("detached", [False, True])
def test_v2_live_node_cannot_spawn_unregistered_or_detached_registered_child(
    tmp_path: Path, detached: bool
) -> None:
    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    marker = process_root / "child.pid"
    if detached:
        target = "process.execPath"
        options = "{detached:true,stdio:'ignore'}"
        child_script = (
            f"require('fs').writeFileSync({json.dumps(str(marker))},String(process.pid));"
            "setInterval(()=>{},1000)"
        )
        arguments = f"['-e',{json.dumps(child_script)}]"
    else:
        target = "'/usr/bin/true'"
        options = "{stdio:'ignore'}"
        arguments = "[]"
    script = (
        "const cp=require('child_process');"
        "let child;try{"
        f"child=cp.spawn({target},{arguments},{options});"
        "}catch(error){if(error.code==='EPERM'||error.code==='EACCES'){process.exit(0)}"
        "process.exit(90)}"
        "child.once('error',(error)=>{"
        "if(error.code==='EPERM'||error.code==='EACCES'){process.exit(0)}process.exit(91)});"
        "child.once('spawn',()=>process.exit(92));"
        "setTimeout(()=>process.exit(93),2000);"
    )
    completed = subprocess.run(
        _node_policy_command(capsule, node, process_root, script),
        capture_output=True,
        check=False,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == completed.stderr == b""
    assert not marker.exists()


def test_v2_exact_root_bootstrap_exception_is_necessary_and_root_only(
    tmp_path: Path,
) -> None:
    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    sibling = capsule.parent / "sibling-secret"
    sibling.write_text("denied")
    metadata_only = QUALIFIER.V2_NODE_SANDBOX_POLICY_TEMPLATE.replace(
        '(allow file-read-data (literal "/"))\n', "", 1
    )
    necessity = subprocess.run(
        _node_policy_command(
            capsule,
            node,
            process_root,
            "process.exit(0)",
            policy=metadata_only,
        ),
        capture_output=True,
        check=False,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
    )
    assert necessity.returncode != 0

    script = (
        "const fs=require('fs');"
        "function denied(operation){try{operation();return false}catch(error){"
        "return error.code==='EPERM'||error.code==='EACCES'}}"
        "const rootListed=Array.isArray(fs.readdirSync('/'));"
        f"const read=denied(()=>fs.readFileSync({json.dumps(str(sibling))}));"
        f"const list=denied(()=>fs.readdirSync({json.dumps(str(capsule.parent))}));"
        "const users=denied(()=>fs.readdirSync('/Users'));"
        "const privateList=denied(()=>fs.readdirSync('/private'));"
        "const privateData=denied(()=>fs.readFileSync('/private/etc/hosts'));"
        "process.exit(rootListed&&read&&list&&users&&privateList&&privateData?0:91);"
    )
    completed = subprocess.run(
        _node_policy_command(capsule, node, process_root, script),
        capture_output=True,
        check=False,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == completed.stderr == b""


def test_v2_capsule_ancestor_depth_and_parameter_drift_fail_closed(tmp_path: Path) -> None:
    deep = tmp_path
    for index in range(QUALIFIER.V2_CAPSULE_ANCESTOR_SLOTS + 1):
        deep = deep / f"d{index:02d}"
    deep.mkdir(parents=True)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="slot cap"):
        QUALIFIER._capsule_ancestor_definitions(deep.resolve())

    capsule = tmp_path / "canonical-capsule"
    capsule.mkdir()
    definitions = QUALIFIER._capsule_ancestor_definitions(capsule.resolve())
    definitions["CAPSULE_ANCESTOR_00"] = str(capsule)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="parameters drifted"):
        QUALIFIER._validate_capsule_ancestor_definitions(capsule.resolve(), definitions)


def test_v2_live_outer_timeout_reaps_exact_node_session(tmp_path: Path) -> None:
    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    pid_path = process_root / "node.pid"
    script = (
        "require('fs').writeFileSync(process.argv[1],String(process.pid));setInterval(()=>{},1000)"
    )
    process = subprocess.Popen(
        _node_policy_command(capsule, node, process_root, script) + [str(pid_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        start_new_session=True,
    )
    pid_path = process_root / "node.pid"
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_path.exists(), (process.poll(), process.stderr.read() if process.poll() else b"")
        node_pid = int(pid_path.read_text(encoding="ascii"))
        assert node_pid == process.pid
        QUALIFIER._kill_and_reap_process_group(process)
        _assert_pid_absent(node_pid)
        with pytest.raises(ProcessLookupError):
            os.killpg(node_pid, 0)
    finally:
        if process.poll() is None:
            QUALIFIER._kill_and_reap_process_group(process)


def test_v2_inner_timeout_kills_exact_registered_node_pid(tmp_path: Path) -> None:
    import metis_model1.oracles as oracles

    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    pid_path = process_root / "inner-node.pid"
    command = [
        str(node),
        "-e",
        "require('fs').writeFileSync(process.argv[1], String(process.pid));"
        "setInterval(() => {}, 1000)",
        str(pid_path),
    ]
    with pytest.raises(oracles.OracleError, match="timeout cap"):
        oracles._run_capsule_command(
            command,
            cwd=capsule,
            request_bytes=b"",
            stdout_path=process_root / "inner-stdout",
            stderr_path=process_root / "inner-stderr",
            timeout=4.0,
            node_executable=node,
            capsule_root=capsule,
            process_root=process_root,
        )
    child_pid = int(pid_path.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(child_pid, 0)


def test_bridge_registered_child_exits_before_exec_when_ack_channel_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, child = socket.socketpair()
    nonce = "a" * 64
    monkeypatch.setattr(QUALIFIER, "__bridge_control_fd__", child.fileno(), raising=False)
    monkeypatch.setattr(QUALIFIER, "__bridge_control_nonce__", nonce, raising=False)
    supervision = QUALIFIER._bridge_child_supervision("node:test")
    bridge.close()
    marker = tmp_path / "must-not-exec"
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('executed')",
            str(marker),
        ],
        **supervision,
    )
    child.close()

    assert process.wait(timeout=3) == 125
    assert not marker.exists()
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)


def test_public_capsule_boundary_denies_child_process_and_leaves_no_residual(
    tmp_path: Path,
) -> None:
    import metis_model1.oracles as oracles

    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    child_marker = process_root / "forbidden-child.pid"
    script = (
        "const cp=require('child_process');let child;try{"
        "child=cp.spawn(process.execPath,['-e',"
        + json.dumps(
            "require('fs').writeFileSync("
            + json.dumps(str(child_marker))
            + ",String(process.pid));setInterval(()=>{},1000)"
        )
        + "],{detached:true,stdio:'ignore'});"
        "}catch(error){if(error.code==='EPERM'||error.code==='EACCES')process.exit(0);"
        "process.exit(90)}"
        "child.once('error',(error)=>{if(error.code==='EPERM'||error.code==='EACCES')"
        "process.exit(0);process.exit(91)});child.once('spawn',()=>process.exit(92));"
        "setTimeout(()=>process.exit(93),2000);"
    )
    completed = oracles._run_capsule_command(
        [str(node), "-e", script],
        cwd=capsule,
        request_bytes=b"",
        stdout_path=process_root / "child-stdout",
        stderr_path=process_root / "child-stderr",
        timeout=5,
        node_executable=node,
        capsule_root=capsule,
        process_root=process_root,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == completed.stderr == b""
    assert not child_marker.exists()


def test_public_capsule_supervisor_rejects_unregistered_cwd_and_stream_paths(
    tmp_path: Path,
) -> None:
    import metis_model1.oracles as oracles

    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    baseline = {
        "cwd": capsule,
        "stdout_path": process_root / "stdout",
        "stderr_path": process_root / "stderr",
    }
    for field, forged in (
        ("cwd", outside),
        ("stdout_path", outside / "stdout"),
        ("stderr_path", outside / "stderr"),
    ):
        arguments = {**baseline, field: forged}
        with pytest.raises(oracles.OracleError, match="registered roots"):
            oracles._run_capsule_command(
                [str(node), "-e", "process.exit(0)"],
                request_bytes=b"",
                timeout=5,
                node_executable=node,
                capsule_root=capsule,
                process_root=process_root,
                **arguments,
            )


def test_v2_authority_binds_worker_and_policy_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mutation, message in (("worker", "worker bytes"), ("policy", "launcher identity")):
        authority = _authority_v2(monkeypatch)
        if mutation == "worker":
            authority["project"]["worker"]["sha256"] = "sha256:" + "0" * 64
        else:
            authority["project"]["launcher"]["sandbox_policy_template_sha256"] = (
                "sha256:" + "0" * 64
            )
        body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
        authority["manifest_sha256"] = QUALIFIER.canonical_hash(body)
        path = tmp_path / f"authority-{mutation}.json"
        path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
        with pytest.raises(QUALIFIER.QualificationBlocked, match=message):
            QUALIFIER._load_authority_v2(path, authority["manifest_sha256"])


@pytest.mark.parametrize(
    "mutation",
    [
        "abi",
        "machine",
        "count",
        "bytes",
        "roster",
        "missing",
        "extra",
        "path",
        "mode",
        "size",
        "hash",
        "bool-size",
    ],
)
def test_dependency_descriptor_mutations_fail_closed(mutation: str) -> None:
    descriptor = _descriptor("dependency")
    if mutation in {"abi", "machine"}:
        descriptor["python"][mutation] = "forged"
    elif mutation == "count":
        descriptor["counts"]["files"] = 143
    elif mutation == "bytes":
        descriptor["counts"]["bytes"] -= 1
    elif mutation == "roster":
        descriptor["roster_sha256"] = "0" * 64
    elif mutation == "missing":
        descriptor["files"].pop()
    elif mutation == "extra":
        descriptor["files"].append(dict(descriptor["files"][0], path="pkg/extra.py"))
    elif mutation == "path":
        descriptor["files"][0]["path"] = "../escape.py"
    elif mutation == "mode":
        descriptor["files"][0]["mode"] = 0o644
    elif mutation == "size":
        descriptor["files"][0]["size"] = -1
    elif mutation == "hash":
        descriptor["files"][0]["sha256"] = "bad"
    else:
        descriptor["files"][0]["size"] = True
    body = {key: value for key, value in descriptor.items() if key != "manifest_sha256"}
    descriptor["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_tree_descriptor(
            descriptor, kind="dependency", label="dependency bundle authority"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "revision",
        "tree",
        "node",
        "runner",
        "tooling",
        "roster",
        "count",
        "bytes",
        "path",
        "mode",
        "hash",
        "extra-field",
    ],
)
def test_capsule_descriptor_mutations_fail_closed(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor = _capsule_descriptor(monkeypatch)
    if mutation in {"revision", "tree"}:
        descriptor[mutation] = "0" * 40
    elif mutation == "node":
        descriptor["node"]["sha256"] = "sha256:" + "0" * 64
    elif mutation == "runner":
        descriptor["runner"]["mode"] = 0o555
    elif mutation == "tooling":
        descriptor["tooling"]["lock_sha256"] = "sha256:" + "0" * 64
    elif mutation == "roster":
        descriptor["roster_sha256"] = "sha256:" + "0" * 64
    elif mutation == "count":
        descriptor["counts"]["files"] = 2
    elif mutation == "bytes":
        descriptor["counts"]["bytes"] = 12
    elif mutation == "path":
        descriptor["files"][0]["path"] = ".git/config"
    elif mutation == "mode":
        descriptor["files"][0]["mode"] = 0o644
    elif mutation == "hash":
        descriptor["files"][0]["sha256"] = "invalid"
    else:
        descriptor["unexpected"] = True
    body = {key: value for key, value in descriptor.items() if key != "manifest_sha256"}
    descriptor["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_capsule_descriptor(descriptor)


def _authority_v2(monkeypatch: pytest.MonkeyPatch) -> dict:
    source = _descriptor("source")
    dependency = _descriptor("dependency")
    capsule = _capsule_descriptor(monkeypatch)
    body = {
        "schema_version": 2,
        "authority_id": QUALIFIER.V2_AUTHORITY_ID,
        "status": "independently_ratified",
        "ratification": {
            "verdict": "RATIFIABLE",
            "scope": ["F-1", "F-2", "F-3"],
            "independent": True,
            "kimi_report_sha256": QUALIFIER.V2_KIMI_REPORT_SHA256,
        },
        "project": {
            "revision": QUALIFIER.V2_PROJECT_SHA,
            "candidate_manifest": {
                "path": "manifests/candidates.json",
                "manifest_sha256": QUALIFIER.V2_CANDIDATE_MANIFEST_SHA256,
            },
            "semantic_registry": {
                "path": "manifests/registry.json",
                "manifest_sha256": QUALIFIER.V2_SEMANTIC_REGISTRY_SHA256,
            },
            "launcher": QUALIFIER._launcher_identity_v2(),
            "worker": {
                "path": "runtime/w3_production_worker.py",
                "sha256": "sha256:" + "1" * 64,
                "protocol": QUALIFIER.V2_PROTOCOL,
            },
        },
        "source_bundle": source,
        "dependency_bundle": dependency,
        "capsule": capsule,
        "expected": {
            "candidates": 3,
            "executions": 5,
            "roles": dict(QUALIFIER.EXPECTED_ROLE_COUNTS),
        },
        "non_claims": list(QUALIFIER.V2_NON_CLAIMS),
    }
    return {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}


@pytest.mark.parametrize(
    "mutation",
    [
        "authority-digest",
        "authority-id",
        "authority-status",
        "kimi-report",
        "kimi-verdict",
        "kimi-scope",
        "kimi-independent",
        "project-revision",
        "candidate-digest",
        "registry-digest",
        "worker-identity",
    ],
)
def test_authority_and_kimi_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    authority = _authority_v2(monkeypatch)
    expected = authority["manifest_sha256"]
    if mutation == "authority-digest":
        expected = "sha256:" + "0" * 64
    elif mutation == "authority-id":
        authority["authority_id"] = "forged"
    elif mutation == "authority-status":
        authority["status"] = "self_ratified"
    elif mutation == "kimi-report":
        authority["ratification"]["kimi_report_sha256"] = "sha256:" + "0" * 64
    elif mutation == "kimi-verdict":
        authority["ratification"]["verdict"] = "ACCEPT"
    elif mutation == "kimi-scope":
        authority["ratification"]["scope"] = ["F-1", "F-2", "F-3", "F-4"]
    elif mutation == "kimi-independent":
        authority["ratification"]["independent"] = False
    elif mutation == "project-revision":
        authority["project"]["revision"] = "0" * 40
    elif mutation == "candidate-digest":
        authority["project"]["candidate_manifest"]["manifest_sha256"] = "sha256:" + "0" * 64
    elif mutation == "registry-digest":
        authority["project"]["semantic_registry"]["manifest_sha256"] = "sha256:" + "0" * 64
    else:
        authority["project"]["worker"]["sha256"] = "sha256:" + "0" * 64
    if mutation != "authority-digest":
        body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
        authority["manifest_sha256"] = QUALIFIER.canonical_hash(body)
        expected = authority["manifest_sha256"]
    path = tmp_path / "authority.json"
    path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._load_authority_v2(path, expected)


def test_v2_authority_rejects_integer_ratification_independent_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _authority_v2(monkeypatch)
    authority["ratification"]["independent"] = 1
    body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    path = tmp_path / "authority-integer-independent.json"
    path.write_bytes(QUALIFIER.canonical_json_bytes(authority))

    with pytest.raises(QUALIFIER.QualificationBlocked, match="Kimi ratification"):
        QUALIFIER._load_authority_v2(path, authority["manifest_sha256"])


def test_v2_authority_rejects_former_handoff_revision_after_canonical_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        QUALIFIER.V2_PYTHON,
        "version",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    authority = _authority_v2(monkeypatch)
    authority["project"]["revision"] = FORMER_HANDOFF_REVISION
    body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    path = tmp_path / "former-revision-authority.json"
    path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
    with pytest.raises(QUALIFIER.QualificationBlocked, match="project revision"):
        QUALIFIER._load_authority_v2(path, authority["manifest_sha256"])


def test_v2_report_requires_source_checkpoint_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        QUALIFIER.V2_PYTHON,
        "version",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    report = _v2_report()
    report["project_revision"] = FORMER_HANDOFF_REVISION
    body = {key: value for key, value in report.items() if key != "manifest_sha256"}
    report["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_report_v2(report, report["launcher"])


def test_source_checkpoint_revision_is_exact_in_qualification_schema() -> None:
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert schema["$defs"]["productionQualified"]["properties"]["project_revision"]["const"] == (
        SOURCE_CHECKPOINT_REVISION
    )
    assert schema["$defs"]["productionQualified"]["properties"]["project_revision"]["const"] != (
        FORMER_HANDOFF_REVISION
    )


@pytest.mark.parametrize(
    "noncanonical_path",
    ["runtime//w3_production_worker.py", "runtime/./w3_production_worker.py"],
)
def test_v2_authority_rejects_consistently_rehashed_noncanonical_worker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    noncanonical_path: str,
) -> None:
    authority = _authority_v2(monkeypatch)
    canonical_path = authority["project"]["worker"]["path"]
    authority["project"]["worker"]["path"] = noncanonical_path
    source = authority["source_bundle"]
    worker = next(row for row in source["files"] if row["path"] == canonical_path)
    worker["path"] = noncanonical_path
    source["roster_sha256"] = QUALIFIER.canonical_hash(source["files"])
    source_body = {key: value for key, value in source.items() if key != "manifest_sha256"}
    source["manifest_sha256"] = QUALIFIER.canonical_hash(source_body)
    authority_body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = QUALIFIER.canonical_hash(authority_body)
    path = tmp_path / f"authority-noncanonical-{len(noncanonical_path)}.json"
    path.write_bytes(QUALIFIER.canonical_json_bytes(authority))

    with pytest.raises(QUALIFIER.QualificationBlocked, match="safe relative POSIX path"):
        QUALIFIER._load_authority_v2(path, authority["manifest_sha256"])


def test_v2_authority_rejects_boolean_role_count_after_canonical_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _authority_v2(monkeypatch)
    authority["expected"]["roles"]["author"] = True
    body = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    path = tmp_path / "authority-boolean-role.json"
    path.write_bytes(QUALIFIER.canonical_json_bytes(authority))

    with pytest.raises(QUALIFIER.QualificationBlocked, match="exact integer 1"):
        QUALIFIER._load_authority_v2(path, authority["manifest_sha256"])


@pytest.mark.parametrize(
    "field",
    ["authority", "source", "dependency", "capsule", "artifact", "run"],
)
def test_v2_rejects_symlink_in_every_external_input_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    real_parent = tmp_path / f"real-{field}"
    real_parent.mkdir()
    target = real_parent / ("authority.json" if field == "authority" else "root")
    if field == "authority":
        authority = _authority_v2(monkeypatch)
        target.write_bytes(QUALIFIER.canonical_json_bytes(authority))
    elif field not in {"artifact", "run"}:
        target.mkdir()
    alias = tmp_path / f"alias-{field}"
    alias.symlink_to(real_parent, target_is_directory=True)
    supplied = alias / target.name

    with pytest.raises(QUALIFIER.QualificationBlocked, match="ancestry contains a symlink"):
        if field == "authority":
            QUALIFIER._load_authority_v2(supplied, authority["manifest_sha256"])
        elif field in {"source", "dependency", "capsule"}:
            QUALIFIER._resolve_external_root(supplied, f"{field} bundle root")
        else:
            QUALIFIER._strict_canonical_path(
                supplied,
                f"{field} root",
                must_exist=False,
                directory=True,
            )


@pytest.mark.parametrize("field", ["artifact", "run"])
def test_v2_missing_output_root_parent_swap_writes_nothing_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    authority = _authority_v2(monkeypatch)
    authority_path = tmp_path / "authority-root-race.json"
    authority_path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
    roots: dict[str, Path] = {}
    for name in ("source", "dependency", "capsule"):
        roots[name] = tmp_path / f"root-race-{name}"
        roots[name].mkdir(mode=0o700)
    stable_artifact_parent = tmp_path / "stable-artifact-parent"
    stable_run_parent = tmp_path / "stable-run-parent"
    stable_artifact_parent.mkdir(mode=0o700)
    stable_run_parent.mkdir(mode=0o700)
    attacked_parent = tmp_path / f"attacked-{field}-parent"
    attacked_parent.mkdir(mode=0o700)
    displaced = tmp_path / f"attacked-{field}-parent-displaced"
    outside = tmp_path / f"attacked-{field}-outside"
    outside.mkdir(mode=0o700)
    artifact = (
        attacked_parent / "artifact" if field == "artifact" else stable_artifact_parent / "artifact"
    )
    run = attacked_parent / "run" if field == "run" else stable_run_parent / "run"
    target_name = field
    original_mkdir = QUALIFIER.os.mkdir
    swapped = False

    def racing_mkdir(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped and name == target_name and dir_fd is not None:
            attacked_parent.rename(displaced)
            attacked_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(QUALIFIER, "_load_authority_v2", lambda *_: authority)
    monkeypatch.setattr(
        QUALIFIER,
        "_verify_external_tree",
        lambda root, *_args, **_kwargs: (Path(root), {}),
    )
    monkeypatch.setattr(QUALIFIER, "_load_gate_inputs", lambda *_: ({}, {}, []))
    monkeypatch.setattr(QUALIFIER.os, "mkdir", racing_mkdir)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._qualify_v2_impl(
                authority_path=authority_path,
                authority_sha256=authority["manifest_sha256"],
                source_bundle_root=roots["source"],
                dependency_bundle_root=roots["dependency"],
                capsule_root=roots["capsule"],
                artifact_root=artifact,
                run_root=run,
                run_nonce="8" * 64,
                timeout_seconds=1.0,
            )
        assert swapped
        assert list(outside.iterdir()) == []
    finally:
        if attacked_parent.is_symlink():
            attacked_parent.unlink()
        if displaced.exists():
            displaced.rename(attacked_parent)


@pytest.mark.parametrize("label", ["artifact root", "run root"])
@pytest.mark.parametrize("mode", [0o777, 0o555])
def test_qualifier_existing_output_roots_require_exact_private_mode(
    tmp_path: Path,
    label: str,
    mode: int,
) -> None:
    root = tmp_path / label.replace(" ", "-")
    root.mkdir(mode=mode)
    root.chmod(mode)
    with pytest.raises(QUALIFIER.QualificationBlocked, match="exact mode 700"):
        QUALIFIER._open_or_create_secure_root(root, label)


def _publisher_fixture(
    tmp_path: Path,
    name: str,
) -> tuple[object, object, dict]:
    artifact_parent = tmp_path / f"{name}-artifact-parent"
    process_parent = tmp_path / f"{name}-process-parent"
    artifact_parent.mkdir(mode=0o700)
    process_parent.mkdir(mode=0o700)
    artifact = QUALIFIER._open_or_create_secure_root(
        artifact_parent / "artifacts",
        "test artifact root",
    )
    process = QUALIFIER._open_or_create_secure_root(
        process_parent / "process",
        "test process root",
    )
    output = QUALIFIER._open_child_directory(
        process,
        "output",
        "test output",
        mode=0o700,
        create=True,
    )
    paths = [f"artifacts/candidate-{index}.json" for index in range(5)]
    try:
        for index, path in enumerate(paths):
            QUALIFIER._write_regular_relative(
                output.descriptor,
                PurePosixPath(path),
                f'{{"index":{index}}}'.encode(),
                f"test artifact {index}",
            )
    finally:
        output.close()
    body = {
        "schema_version": 2,
        "executions": [{"artifact_path": path} for path in paths],
    }
    return artifact, process, {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}


def _qualifier_open_fd_snapshot() -> dict[int, tuple[int, int, int, int]]:
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


def _raise_on_line_after(
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


QUALIFIER_FD_TRANSFER_LOW_LEVEL_CASES = (
    "snapshot-child",
    "write-dup",
    "write-child",
    "open-parent-dup",
    "open-parent-child",
    "read-parent",
    "replace-parent",
    "seal-directory-child",
    "seal-file-child",
    "seal-ancestry-child",
    "verify-preimage-child",
    "verify-bundle-child",
    "secure-root-descriptor-transfer",
    "secure-root-handle-transfer",
    "child-return",
    "random-return",
    "materialize-preimage-namespace",
    "verify-tree-namespace",
    "verify-tree-target",
    "seal-preimage-namespace",
    "materialize-bundle-namespace",
)


@pytest.mark.parametrize("case", QUALIFIER_FD_TRANSFER_LOW_LEVEL_CASES)
def test_qualifier_fd_transfer_low_level_roster_is_baseexception_safe(
    tmp_path: Path,
    case: str,
) -> None:
    resources: list[object] = []
    root: object | None = None

    def anchored(label: str = "fd transfer root"):
        handle = QUALIFIER._open_or_create_secure_root(
            tmp_path / f"{case}-root",
            label,
        )
        resources.append(handle)
        return handle

    function: object
    needle: str
    target_needle: str | None = None

    if case == "snapshot-child":
        root = anchored()
        (root.path / "artifacts").mkdir(mode=0o700)
        function = QUALIFIER._snapshot_qualification_descriptor
        needle = "child = os.open(name, _DIRECTORY_OPEN_FLAGS"
        target_needle = "visit(child"

        def invoke():
            return function(root.descriptor, set(), immutable=False)
    elif case in {"write-dup", "write-child"}:
        root = anchored()
        relative = (
            PurePosixPath("nested/value") if case == "write-child" else PurePosixPath("value")
        )
        if case == "write-child":
            (root.path / "nested").mkdir(mode=0o700)
        function = QUALIFIER._write_regular_relative
        needle = (
            "descriptor = os.dup(root_descriptor)"
            if case == "write-dup"
            else "child = os.open(part, _DIRECTORY_OPEN_FLAGS"
        )
        target_needle = "for part" if case == "write-dup" else "metadata = os.fstat(child)"

        def invoke():
            return function(root.descriptor, relative, b"value", "fd transfer write")
    elif case in {"open-parent-dup", "open-parent-child"}:
        root = anchored()
        relative = PurePosixPath("nested/value")
        (root.path / "nested").mkdir(mode=0o700)
        function = QUALIFIER._open_relative_parent_descriptor
        needle = (
            "descriptor = os.dup(root_descriptor)"
            if case == "open-parent-dup"
            else "child = os.open(part, _DIRECTORY_OPEN_FLAGS"
        )
        target_needle = "for part" if case == "open-parent-dup" else "metadata = os.fstat(child)"

        def invoke():
            return function(root.descriptor, relative, "fd transfer parent")
    elif case in {"read-parent", "replace-parent"}:
        root = anchored()
        path = root.path / "value"
        path.write_bytes(b"old")
        path.chmod(0o600)
        function = (
            QUALIFIER._read_regular_relative
            if case == "read-parent"
            else QUALIFIER._replace_regular_relative
        )
        needle = "parent = _open_relative_parent_descriptor"
        target_needle = "metadata = os.stat" if case == "read-parent" else "descriptor = os.open("
        if case == "read-parent":

            def invoke():
                return function(root.descriptor, PurePosixPath("value"), 16, "fd read")
        else:

            def invoke():
                return function(
                    root.descriptor,
                    PurePosixPath("value"),
                    b"new",
                    "fd replace",
                )
    elif case in {"seal-directory-child", "seal-file-child", "seal-ancestry-child"}:
        root = anchored()
        if case == "seal-file-child":
            (root.path / "value").write_bytes(b"value")
            function = QUALIFIER._seal_directory_descriptor
            needle = "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC"
            target_needle = "os.fchmod(child"
        else:
            (root.path / "nested").mkdir(mode=0o700)
            function = (
                QUALIFIER._seal_directory_descriptor
                if case == "seal-directory-child"
                else QUALIFIER._seal_directory_ancestry_descriptor
            )
            needle = "child = os.open(name, _DIRECTORY_OPEN_FLAGS"
            target_needle = (
                "_seal_directory_descriptor(child)"
                if case == "seal-directory-child"
                else "_seal_directory_ancestry_descriptor(child)"
            )

        def invoke():
            return function(root.descriptor)
    elif case in {"verify-preimage-child", "verify-bundle-child"}:
        root = anchored()
        (root.path / "nested").mkdir(mode=0o555)
        os.fchmod(root.descriptor, 0o555)
        root.mode = 0o555
        if case == "verify-preimage-child":
            function = QUALIFIER._verify_materialized_tree_preimage_v2
            needle = "child = os.open(name, _DIRECTORY_OPEN_FLAGS"
            target_needle = "visit(child"
            descriptor = {"files": [], "manifest_sha256": "sha256:" + "1" * 64}

            def invoke():
                return function(
                    root,
                    descriptor,
                    {},
                    manifest_name="bundle.json",
                    label="fd preimage",
                )
        else:
            function = QUALIFIER._verify_materialized_bundle
            needle = "child = os.open(name, _DIRECTORY_OPEN_FLAGS"
            target_needle = "visit(child"

            def invoke():
                return function(root, {}, {}, immutable=True)
    elif case in {"secure-root-descriptor-transfer", "secure-root-handle-transfer"}:
        function = QUALIFIER._open_or_create_secure_root
        needle = "handle = _AnchoredDirectory("
        target_needle = (
            "parent_descriptor = -1"
            if case == "secure-root-descriptor-transfer"
            else "return handle"
        )

        def invoke():
            return function(tmp_path / f"{case}-target", "fd secure root")
    elif case == "child-return":
        root = anchored()
        function = QUALIFIER._open_child_directory
        needle = "handle = _AnchoredDirectory("
        target_needle = "return handle"

        def invoke():
            return function(
                root,
                "child",
                "fd child",
                mode=0o700,
                create=True,
            )
    elif case == "random-return":
        root = anchored()
        registry = QUALIFIER._RetainedRootRegistry()
        resources.append(registry)
        function = QUALIFIER._create_random_directory
        needle = "handle = _open_child_directory("
        target_needle = "if token is not None:"

        def invoke():
            return function(
                root,
                ".w3-fd-transfer-",
                "fd random",
                registry=registry,
                kind="production-process-root",
                logical_root="process",
                anchor="run-root",
            )
    elif case == "materialize-preimage-namespace":
        root = anchored()
        function = QUALIFIER._materialize_tree_preimage_v2
        needle = "namespace = _open_child_directory("
        target_needle = "target = _open_child_directory("
        descriptor = {"files": [], "manifest_sha256": "sha256:" + "2" * 64}

        def invoke():
            return function(
                root,
                kind="source",
                descriptor=descriptor,
                contents={},
                manifest_name="bundle.json",
                label="fd materialize",
            )
    elif case in {"verify-tree-namespace", "verify-tree-target"}:
        root = anchored()
        namespace_path = root.path / "preimages"
        namespace_path.mkdir(mode=0o700)
        digest = "sha256:" + "3" * 64
        if case == "verify-tree-target":
            (namespace_path / f"source-{digest[7:]}").mkdir(mode=0o555)
        namespace_path.chmod(0o555)
        function = QUALIFIER._verify_tree_preimage_at_v2
        needle = (
            "namespace = _open_child_directory("
            if case == "verify-tree-namespace"
            else "target = _open_child_directory("
        )
        target_needle = (
            "target = _open_child_directory("
            if case == "verify-tree-namespace"
            else "_verify_materialized_tree_preimage_v2("
        )
        descriptor = {"files": [], "manifest_sha256": digest}

        def invoke():
            return function(
                root,
                kind="source",
                descriptor=descriptor,
                contents={},
                manifest_name="bundle.json",
                label="fd verify tree",
            )
    elif case == "seal-preimage-namespace":
        root = anchored()
        (root.path / "preimages").mkdir(mode=0o700)
        function = QUALIFIER._seal_preimage_namespace_v2
        needle = "namespace = _open_child_directory("
        target_needle = "os.fchmod(namespace.descriptor"

        def invoke():
            return function(root)
    else:
        root = anchored()
        function = QUALIFIER._materialize_bundle
        needle = "bundles = _open_child_directory("
        target_needle = "target = _open_existing_materialized_bundle("

        def invoke():
            return function(root, "sha256:" + "4" * 64, [], {})

    before = _qualifier_open_fd_snapshot()
    retained: BaseException | None = None
    after: dict[int, tuple[int, int, int, int]] = {}
    try:
        retained = _raise_on_line_after(
            function,
            needle,
            invoke,
            target_needle=target_needle,
        )
        after = _qualifier_open_fd_snapshot()
        assert after == before
    finally:
        for descriptor in set(after) - set(before):
            with contextlib.suppress(OSError):
                os.close(descriptor)
        for resource in reversed(resources):
            resource.close()
        assert retained is not None


QUALIFIER_FD_TRANSFER_HIGH_LEVEL_CASES = (
    "run-worker-process",
    "run-worker-output",
    "run-worker-v2-output",
    "run-capsule-namespace",
    "qualify-artifact",
    "qualify-output",
    "qualify-bundles",
    "qualify-bundle",
    "v2-root-success",
    "v2-output-create",
    "v2-output-read",
)


@pytest.mark.parametrize("case", QUALIFIER_FD_TRANSFER_HIGH_LEVEL_CASES)
def test_qualifier_fd_transfer_high_level_roster_is_baseexception_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    resources: list[object] = []
    retained_registry: object | None = None

    def anchored(path: Path, label: str):
        handle = QUALIFIER._open_or_create_secure_root(path, label)
        resources.append(handle)
        return handle

    function: object
    needle: str
    target_needle: str | None = None

    if case in {"run-worker-process", "run-worker-output"}:
        artifact = anchored(tmp_path / "worker-artifact", "worker artifact")
        registry = QUALIFIER._RetainedRootRegistry()
        resources.append(registry)
        retained_registry = registry
        bundle = tmp_path / "worker-bundle"
        source = tmp_path / "worker-source"
        bundle.mkdir(mode=0o700)
        source.mkdir(mode=0o700)
        function = QUALIFIER._run_worker
        needle = (
            "process = _create_random_directory("
            if case == "run-worker-process"
            else "output = _open_child_directory("
        )
        target_needle = (
            "output = _open_child_directory("
            if case == "run-worker-process"
            else "output_root = output.path"
        )

        def invoke():
            return function(
                bundle,
                "worker.py",
                source,
                artifact,
                b"{}",
                1.0,
                registry,
            )
    elif case == "run-worker-v2-output":
        artifact = anchored(tmp_path / "v2-worker-artifact", "v2 worker artifact")
        process = anchored(tmp_path / "v2-worker-process", "v2 worker process")
        resources.extend([])
        output = QUALIFIER._open_child_directory(
            process,
            "output",
            "v2 worker output fixture",
            mode=0o700,
            create=True,
        )
        output.close()
        source = tmp_path / "v2-worker-source"
        dependency = tmp_path / "v2-worker-dependency"
        source.mkdir(mode=0o700)
        dependency.mkdir(mode=0o700)
        authority = tmp_path / "v2-worker-authority.json"
        authority.write_bytes(b"{}")
        function = QUALIFIER._run_worker_v2
        needle = "output = _open_child_directory("
        target_needle = "output_root = output.path"

        def invoke():
            return function(
                source_bundle=source,
                dependency_bundle=dependency,
                worker_relative="worker.py",
                authority_path=authority,
                artifact_root=artifact,
                process_root=process,
                request_bytes=b"{}",
                timeout_seconds=1.0,
            )
    elif case == "run-capsule-namespace":
        process = anchored(tmp_path / "capsule-process", "capsule process")
        capsule = tmp_path / "capsule"
        (capsule / "tooling").mkdir(parents=True)
        placeholder = capsule / "placeholder"
        placeholder.write_bytes(b"x")
        monkeypatch.setattr(QUALIFIER, "_source_file", lambda *_args, **_kwargs: placeholder)
        monkeypatch.setattr(
            QUALIFIER,
            "_v2_runtime_authority",
            lambda _authority: {
                "runtime_identity": {
                    "node_path": "bin/node",
                    "tsx_path": "tooling/loader.mjs",
                    "runner_path": "runner.mjs",
                    "sandbox_policy_version": "v1",
                    "sandbox_policy_sha256": "sha256:" + "9" * 64,
                }
            },
        )
        monkeypatch.setattr(QUALIFIER, "_capsule_ancestor_definitions", lambda _path: {})
        monkeypatch.setattr(
            QUALIFIER,
            "_validate_capsule_ancestor_definitions",
            lambda *_args, **_kwargs: None,
        )
        authority = {
            "capsule": {
                "node": {"path": "bin/node", "sha256": "sha256:" + "1" * 64},
                "tsx": {"path": "tooling/loader.mjs", "sha256": "sha256:" + "2" * 64},
                "runner": {"path": "runner.mjs", "sha256": "sha256:" + "3" * 64},
                "tooling": {
                    "node_modules_sha256": "sha256:" + "4" * 64,
                    "package_sha256": "sha256:" + "5" * 64,
                    "lock_sha256": "sha256:" + "6" * 64,
                },
            }
        }
        execution = {
            "candidate_id": "candidate",
            "role": "F1",
            "request": {"request_id": "request"},
        }
        function = QUALIFIER._run_capsule_node_v2
        needle = "namespace = _open_child_directory("
        target_needle = "invocation = _open_child_directory("

        def invoke():
            return function(
                execution=execution,
                capsule=capsule,
                process_root=process,
                run_nonce="7" * 64,
                timeout_seconds=1.0,
                authority=authority,
            )
    elif case.startswith("qualify-"):
        source = tmp_path / "qualify-source"
        source.mkdir(mode=0o700)
        authority_path = tmp_path / "qualify-authority.json"
        authority_path.write_bytes(b"{}")
        artifact_path = tmp_path / "qualify-artifact"
        launcher = {"identity": "fd-transfer-launcher"}
        monkeypatch.setattr(QUALIFIER, "_launcher_identity", lambda: launcher)
        monkeypatch.setattr(
            QUALIFIER,
            "_load_authority",
            lambda *_args: {"worker": {"path": "worker.py"}},
        )
        monkeypatch.setattr(QUALIFIER, "_read_bundle_sources", lambda *_args: ([], {}))
        monkeypatch.setattr(QUALIFIER, "_load_gate_inputs", lambda *_args: ({}, {}, []))
        monkeypatch.setattr(QUALIFIER, "_worker_input", lambda *_args: {})

        def materialize(artifact: object, *_args: object):
            bundles = QUALIFIER._open_child_directory(
                artifact,
                "bundles",
                "fd qualify bundles fixture",
                mode=0o700,
                create=True,
                exist_ok=True,
            )
            digest = "sha256:" + "a" * 64
            target = QUALIFIER._open_child_directory(
                bundles,
                digest[7:],
                "fd qualify bundle fixture",
                mode=0o700,
                create=True,
                exist_ok=True,
            )
            os.fchmod(target.descriptor, 0o555)
            target.close()
            bundles.close()
            return artifact.path / "bundles" / digest[7:], digest, {}

        def worker(
            _bundle: Path,
            _worker_relative: str,
            _source: Path,
            artifact: object,
            *_args: object,
        ):
            process = QUALIFIER._open_child_directory(
                artifact,
                "process",
                "fd qualify process fixture",
                mode=0o700,
                create=True,
            )
            output = QUALIFIER._open_child_directory(
                process,
                "output",
                "fd qualify output fixture",
                mode=0o700,
                create=True,
            )
            output.close()
            return b"{}", process

        monkeypatch.setattr(QUALIFIER, "_materialize_bundle", materialize)
        monkeypatch.setattr(QUALIFIER, "_run_worker", worker)
        monkeypatch.setattr(
            QUALIFIER,
            "_verify_worker_output",
            lambda *_args: ({"counts": {}, "roles": {}}, []),
        )
        function = QUALIFIER._qualify_impl
        mapping = {
            "qualify-artifact": (
                "artifact_handle = _open_or_create_secure_root",
                "bundle, bundle_sha256, bundle_body = _materialize_bundle(",
            ),
            "qualify-output": (
                "output_root = _open_child_directory(",
                "denominators, verified = _verify_worker_output(",
            ),
            "qualify-bundles": (
                "bundles = _open_child_directory(",
                "bundle_handle = _open_child_directory(",
            ),
            "qualify-bundle": (
                "bundle_handle = _open_child_directory(",
                "_verify_materialized_bundle(bundle_handle",
            ),
        }
        needle, target_needle = mapping[case]

        def invoke():
            return function(
                authority_path=authority_path,
                authority_sha256="sha256:" + "b" * 64,
                source_root=source,
                artifact_root=artifact_path,
                timeout_seconds=1.0,
            )
    else:
        authority = _authority_v2(monkeypatch)
        authority_path = tmp_path / "fd-v2-authority.json"
        authority_path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
        roots: dict[str, Path] = {}
        for name in ("source", "dependency", "capsule"):
            roots[name] = tmp_path / f"fd-v2-{name}"
            roots[name].mkdir(mode=0o700)
        artifact_parent = tmp_path / "fd-v2-artifact-parent"
        run_parent = tmp_path / "fd-v2-run-parent"
        artifact_parent.mkdir(mode=0o700)
        run_parent.mkdir(mode=0o700)
        monkeypatch.setattr(QUALIFIER, "_load_authority_v2", lambda *_args: authority)
        monkeypatch.setattr(
            QUALIFIER,
            "_verify_external_tree",
            lambda root, *_args, **_kwargs: (Path(root), {}),
        )
        monkeypatch.setattr(QUALIFIER, "_load_gate_inputs", lambda *_args: ({}, {}, []))
        monkeypatch.setattr(
            QUALIFIER,
            "_materialize_tree_preimage_v2",
            lambda trusted, **_kwargs: trusted.path,
        )
        monkeypatch.setattr(QUALIFIER, "_seal_preimage_namespace_v2", lambda root: root.path)
        monkeypatch.setattr(QUALIFIER, "_run_capsule_roster_v2", lambda **_kwargs: [])
        monkeypatch.setattr(QUALIFIER, "_run_worker_v2", lambda **_kwargs: b"{}")
        function = QUALIFIER._qualify_v2_impl
        mapping = {
            "v2-root-success": (
                "run_handle = _open_or_create_secure_root",
                "if artifact_handle is None or run_handle is None:",
            ),
            "v2-output-create": (
                "output = _open_child_directory(",
                "output.assert_path_identity()",
            ),
            "v2-output-read": (
                "output_root = _open_child_directory(",
                "_verify_worker_output_v2(",
            ),
        }
        needle, target_needle = mapping[case]

        def invoke():
            return function(
                authority_path=authority_path,
                authority_sha256=authority["manifest_sha256"],
                source_bundle_root=roots["source"],
                dependency_bundle_root=roots["dependency"],
                capsule_root=roots["capsule"],
                artifact_root=artifact_parent / "artifact",
                run_root=run_parent / "run",
                run_nonce="8" * 64,
                timeout_seconds=1.0,
            )

    before = _qualifier_open_fd_snapshot()
    retained: BaseException | None = None
    after: dict[int, tuple[int, int, int, int]] = {}
    try:
        retained = _raise_on_line_after(
            function,
            needle,
            invoke,
            target_needle=target_needle,
        )
        if retained_registry is not None:
            cleanup = retained_registry.cleanup(qualified=False)
            assert [root["kind"] for root in cleanup["retained_roots"]] == ["worker-process-root"]
            retained_registry.close()
        after = _qualifier_open_fd_snapshot()
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
        "publication-pair",
        "v2-root-pair",
    ],
)
def test_qualifier_sequential_fd_acquisitions_are_baseexception_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: str,
) -> None:
    captured_handles: list[object] = []
    captured_fds: list[int] = []
    resources: list[object] = []

    if site == "secure-root":
        parent = tmp_path / "secure-root-parent"
        parent.mkdir(mode=0o700)
        original_assert = QUALIFIER._AnchoredDirectory.assert_path_identity

        def interrupt_identity(handle: object) -> None:
            if handle.label == "fd-census secure root":
                captured_handles.append(handle)
                raise KeyboardInterrupt
            original_assert(handle)

        monkeypatch.setattr(
            QUALIFIER._AnchoredDirectory, "assert_path_identity", interrupt_identity
        )

        def invoke() -> None:
            QUALIFIER._open_or_create_secure_root(parent / "root", "fd-census secure root")

    elif site == "random-observe":
        parent = QUALIFIER._open_or_create_secure_root(tmp_path / "random-parent", "random parent")
        registry = QUALIFIER._RetainedRootRegistry()
        resources.extend([registry, parent])

        def interrupt_observe(_token: int, handle: object) -> None:
            captured_handles.append(handle)
            raise KeyboardInterrupt

        monkeypatch.setattr(registry, "observe", interrupt_observe)

        def invoke() -> None:
            QUALIFIER._create_random_directory(
                parent,
                ".w3-fd-",
                "fd-census random root",
                registry=registry,
                kind="production-process-root",
                logical_root="process",
                anchor="run-root",
            )

    elif site == "registry-dup-transfer":
        parent = QUALIFIER._open_or_create_secure_root(tmp_path / "dup-parent", "dup parent")
        child = QUALIFIER._open_child_directory(
            parent,
            "child",
            "dup child",
            mode=0o700,
            create=True,
        )
        registry = QUALIFIER._RetainedRootRegistry()
        token = registry.intent(
            kind="production-process-root",
            logical_root="process",
            anchor="run-root",
            locator="child",
        )
        registry.mark_created(token)
        resources.extend([registry, child, parent])

        class InterruptingEntry(dict):
            fired = False

            def __setitem__(self, key: object, value: object) -> None:
                if key == "descriptor_observed" and not self.fired:
                    self.fired = True
                    captured_fds.append(self["descriptor"])
                    raise KeyboardInterrupt
                super().__setitem__(key, value)

        registry._entries[token] = InterruptingEntry(registry._entries[token])

        def invoke() -> None:
            registry.observe(token, child)

    elif site == "publication-pair":
        artifact, process, report = _publisher_fixture(tmp_path, "fd-census-publication")
        resources.extend([process, artifact])
        original_open = QUALIFIER._open_child_directory

        def interrupt_namespace(*args: object, **kwargs: object):
            label = args[2]
            if label == "qualification namespace":
                raise KeyboardInterrupt
            handle = original_open(*args, **kwargs)
            if label == "qualification output":
                captured_handles.append(handle)
            return handle

        monkeypatch.setattr(QUALIFIER, "_open_child_directory", interrupt_namespace)

        def invoke() -> None:
            QUALIFIER._publish_qualification(artifact, process, report)

    else:
        authority = _authority_v2(monkeypatch)
        authority_path = tmp_path / "fd-census-authority.json"
        authority_path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
        roots: dict[str, Path] = {}
        for name in ("source", "dependency", "capsule"):
            roots[name] = tmp_path / f"fd-census-{name}"
            roots[name].mkdir(mode=0o700)
        artifact_parent = tmp_path / "fd-census-artifact-parent"
        run_parent = tmp_path / "fd-census-run-parent"
        artifact_parent.mkdir(mode=0o700)
        run_parent.mkdir(mode=0o700)
        monkeypatch.setattr(QUALIFIER, "_load_authority_v2", lambda *_: authority)
        monkeypatch.setattr(
            QUALIFIER,
            "_verify_external_tree",
            lambda root, *_args, **_kwargs: (Path(root), {}),
        )
        monkeypatch.setattr(QUALIFIER, "_load_gate_inputs", lambda *_: ({}, {}, []))
        original_open_root = QUALIFIER._open_or_create_secure_root

        def interrupt_run_root(path: Path, label: str):
            if label == "run root":
                raise KeyboardInterrupt
            handle = original_open_root(path, label)
            if label == "artifact root":
                captured_handles.append(handle)
            return handle

        monkeypatch.setattr(QUALIFIER, "_open_or_create_secure_root", interrupt_run_root)

        def invoke() -> None:
            QUALIFIER._qualify_v2_impl(
                authority_path=authority_path,
                authority_sha256=authority["manifest_sha256"],
                source_bundle_root=roots["source"],
                dependency_bundle_root=roots["dependency"],
                capsule_root=roots["capsule"],
                artifact_root=artifact_parent / "artifact",
                run_root=run_parent / "run",
                run_nonce="9" * 64,
                timeout_seconds=1.0,
            )

    before = _qualifier_open_fd_snapshot()
    try:
        with pytest.raises(KeyboardInterrupt):
            invoke()
        assert _qualifier_open_fd_snapshot() == before
    finally:
        for resource in resources:
            resource.close()
        for handle in captured_handles:
            handle.close()
        for descriptor in captured_fds:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def test_materialized_preimage_keyboard_interrupt_keeps_fd_delta_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = QUALIFIER._open_or_create_secure_root(tmp_path / "trusted", "trusted root")
    descriptor = {
        "kind": "source",
        "files": [],
        "manifest_sha256": "sha256:" + "1" * 64,
    }
    monkeypatch.setattr(
        QUALIFIER,
        "_verify_materialized_tree_preimage_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    before = _qualifier_open_fd_snapshot()
    try:
        with pytest.raises(KeyboardInterrupt):
            QUALIFIER._materialize_tree_preimage_v2(
                trusted,
                kind="source",
                descriptor=descriptor,
                contents={},
                manifest_name="bundle.json",
                label="source bundle",
            )
        assert _qualifier_open_fd_snapshot() == before
    finally:
        trusted.close()


def test_publish_new_target_swap_blocks_and_retains_displaced_owned_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, "publish-new-target")
    namespace = artifact.path / "qualifications"
    target = namespace / report["manifest_sha256"][len(QUALIFIER.HASH_PREFIX) :]
    displaced = namespace / "displaced-owned-target"
    outside = tmp_path / "publish-new-target-outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve-exact")
    original_snapshot = QUALIFIER._snapshot_qualification_descriptor
    swapped = False

    def racing_snapshot(
        descriptor: int,
        expected_files: set[str],
        *,
        immutable: bool,
    ) -> dict[str, bytes]:
        nonlocal swapped
        snapshot = original_snapshot(descriptor, expected_files, immutable=immutable)
        if immutable and not swapped:
            target.chmod(0o700)
            target.rename(displaced)
            displaced.chmod(0o555)
            target.symlink_to(outside, target_is_directory=True)
            swapped = True
        return snapshot

    monkeypatch.setattr(QUALIFIER, "_snapshot_qualification_descriptor", racing_snapshot)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._publish_qualification(artifact, process, report)
        assert swapped
        assert displaced.is_dir()
        assert target.is_symlink()
        assert sentinel.read_bytes() == b"preserve-exact"
        assert sorted(item.name for item in outside.iterdir()) == ["sentinel"]
    finally:
        if target.is_symlink():
            target.unlink()
        process.close()
        artifact.close()


def test_publish_namespace_swap_blocks_with_outside_sentinel_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, "publish-namespace")
    namespace = artifact.path / "qualifications"
    displaced = artifact.path / "qualifications-displaced"
    outside = tmp_path / "publish-namespace-outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve-exact")
    original_snapshot = QUALIFIER._snapshot_qualification_descriptor
    swapped = False

    def racing_snapshot(
        descriptor: int,
        expected_files: set[str],
        *,
        immutable: bool,
    ) -> dict[str, bytes]:
        nonlocal swapped
        snapshot = original_snapshot(descriptor, expected_files, immutable=immutable)
        if immutable and not swapped:
            namespace.rename(displaced)
            namespace.symlink_to(outside, target_is_directory=True)
            swapped = True
        return snapshot

    monkeypatch.setattr(QUALIFIER, "_snapshot_qualification_descriptor", racing_snapshot)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._publish_qualification(artifact, process, report)
        assert swapped
        assert sentinel.read_bytes() == b"preserve-exact"
        assert sorted(item.name for item in outside.iterdir()) == ["sentinel"]
    finally:
        if namespace.is_symlink():
            namespace.unlink()
        if displaced.exists():
            displaced.rename(namespace)
        process.close()
        artifact.close()


def test_failed_qualification_publication_retains_measured_partial_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, "publication-partial")
    registry = QUALIFIER._RetainedRootRegistry()

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise QUALIFIER.QualificationBlocked("injected publication failure")

    monkeypatch.setattr(QUALIFIER, "_write_regular_relative", fail_publication)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="publication failure"):
            QUALIFIER._publish_qualification(artifact, process, report, registry)
        cleanup = registry.cleanup(qualified=False)
        QUALIFIER._validate_cleanup(cleanup, qualified=False)
        assert [root["kind"] for root in cleanup["retained_roots"]] == [
            "qualification-publication-partial-root"
        ]
        locator = cleanup["retained_roots"][0]["locator"]
        assert (artifact.path / locator).is_dir()
        assert cleanup["delete_attempts"] == 0
    finally:
        registry.close()
        process.close()
        artifact.close()


def test_publication_precreation_failure_does_not_claim_a_partial_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, "publication-precreate")
    registry = QUALIFIER._RetainedRootRegistry()
    original_open_child = QUALIFIER._open_child_directory

    def fail_target_before_creation(*args: object, **kwargs: object):
        if len(args) >= 3 and args[2] == "qualification artifact":
            raise QUALIFIER.QualificationBlocked("injected publication pre-creation failure")
        return original_open_child(*args, **kwargs)

    monkeypatch.setattr(QUALIFIER, "_open_child_directory", fail_target_before_creation)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pre-creation"):
            QUALIFIER._publish_qualification(artifact, process, report, registry)
        assert registry.cleanup(qualified=False)["retained_roots"] == []
        namespace = artifact.path / "qualifications"
        assert namespace.is_dir()
        assert list(namespace.iterdir()) == []
    finally:
        registry.close()
        process.close()
        artifact.close()


def test_publication_postmkdir_descriptor_failure_retains_unmeasurable_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, "publication-postmkdir")
    registry = QUALIFIER._RetainedRootRegistry()

    def fail_observe(*_args: object) -> None:
        raise QUALIFIER.QualificationBlocked("injected publication descriptor failure")

    monkeypatch.setattr(registry, "observe", fail_observe)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="descriptor failure"):
            QUALIFIER._publish_qualification(artifact, process, report, registry)
        cleanup = registry.cleanup(qualified=False)
        assert len(cleanup["retained_roots"]) == 1
        root = cleanup["retained_roots"][0]
        assert root["state"] == "unmeasurable"
        assert root["creation_observed"] is True
        assert (artifact.path / root["locator"]).is_dir()
    finally:
        registry.close()
        process.close()
        artifact.close()


@pytest.mark.parametrize("branch", ["existing", "raced"])
def test_publish_structural_success_branches_reassert_target_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
) -> None:
    artifact, process, report = _publisher_fixture(tmp_path, f"publish-{branch}")
    QUALIFIER._publish_qualification(artifact, process, report)
    namespace = artifact.path / "qualifications"
    target = namespace / report["manifest_sha256"][len(QUALIFIER.HASH_PREFIX) :]
    displaced = namespace / f"{branch}-target-displaced"
    outside = tmp_path / f"publish-{branch}-outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve-exact")
    original_snapshot = QUALIFIER._snapshot_qualification_descriptor
    original_open = QUALIFIER._open_child_directory
    swapped = False

    def racing_snapshot(
        descriptor: int,
        expected_files: set[str],
        *,
        immutable: bool,
    ) -> dict[str, bytes]:
        nonlocal swapped
        snapshot = original_snapshot(descriptor, expected_files, immutable=immutable)
        if immutable and not swapped:
            target.chmod(0o700)
            target.rename(displaced)
            displaced.chmod(0o555)
            target.symlink_to(outside, target_is_directory=True)
            swapped = True
        return snapshot

    def forced_race(*args: object, **kwargs: object) -> object:
        label = args[2]
        if label == "existing qualification artifact":
            try:
                raise FileNotFoundError
            except FileNotFoundError as error:
                raise QUALIFIER.QualificationBlocked("forced missing target") from error
        if label == "qualification artifact":
            try:
                raise FileExistsError
            except FileExistsError as error:
                raise QUALIFIER.QualificationBlocked("forced raced target") from error
        return original_open(*args, **kwargs)

    monkeypatch.setattr(QUALIFIER, "_snapshot_qualification_descriptor", racing_snapshot)
    if branch == "raced":
        monkeypatch.setattr(QUALIFIER, "_open_child_directory", forced_race)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._publish_qualification(artifact, process, report)
        assert swapped
        assert displaced.is_dir()
        assert target.is_symlink()
        assert sentinel.read_bytes() == b"preserve-exact"
    finally:
        if target.is_symlink():
            target.unlink()
        if displaced.exists():
            displaced.chmod(0o700)
            displaced.rename(target)
            target.chmod(0o555)
        process.close()
        artifact.close()


@pytest.mark.parametrize("schema_version", [1, 2])
def test_shared_publish_parent_swap_writes_nothing_outside(
    tmp_path: Path,
    schema_version: int,
) -> None:
    artifact_parent = tmp_path / f"publish-artifact-parent-{schema_version}"
    process_parent = tmp_path / f"publish-process-parent-{schema_version}"
    artifact_parent.mkdir(mode=0o700)
    process_parent.mkdir(mode=0o700)
    displaced = tmp_path / f"publish-artifact-parent-{schema_version}-displaced"
    outside = tmp_path / f"publish-artifact-outside-{schema_version}"
    outside.mkdir(mode=0o700)
    artifact = QUALIFIER._open_or_create_secure_root(
        artifact_parent / "artifacts",
        "test artifact root",
    )
    process = QUALIFIER._open_or_create_secure_root(
        process_parent / "process",
        "test process root",
    )
    output = QUALIFIER._open_child_directory(
        process,
        "output",
        "test output",
        mode=0o700,
        create=True,
    )
    paths = [f"artifacts/candidate-{index}.json" for index in range(5)]
    try:
        for index, name in enumerate(paths):
            QUALIFIER._write_regular_relative(
                output.descriptor,
                PurePosixPath(name),
                f'{{"index":{index}}}'.encode(),
                f"test artifact {index}",
            )
        output.close()
        body = {
            "schema_version": schema_version,
            "executions": [{"artifact_path": name} for name in paths],
        }
        report = {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}
        artifact_parent.rename(displaced)
        artifact_parent.symlink_to(outside, target_is_directory=True)
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._publish_qualification(artifact, process, report)
        assert list(outside.iterdir()) == []
    finally:
        output.close()
        process.close()
        artifact.close()
        if artifact_parent.is_symlink():
            artifact_parent.unlink()
        if displaced.exists():
            displaced.rename(artifact_parent)


def test_fd_rooted_retention_preserves_owned_and_outside_trees_after_parent_swap(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "cleanup-run-parent"
    parent.mkdir(mode=0o700)
    displaced = tmp_path / "cleanup-run-parent-displaced"
    outside = tmp_path / "cleanup-outside"
    outside.mkdir(mode=0o700)
    run = QUALIFIER._open_or_create_secure_root(parent / "run", "test run root")
    process = QUALIFIER._create_random_directory(run, ".w3-production-", "test process")
    trusted = QUALIFIER._create_random_directory(run, ".w3-trusted-", "test trusted")
    try:
        QUALIFIER._write_regular_relative(
            process.descriptor,
            PurePosixPath("owned"),
            b"owned",
            "owned process file",
        )
        QUALIFIER._write_regular_relative(
            trusted.descriptor,
            PurePosixPath("owned"),
            b"owned",
            "owned trusted file",
        )
        outside_run = outside / "run"
        for name in (process.name, trusted.name):
            target = outside_run / name
            target.mkdir(parents=True, mode=0o700)
            (target / "sentinel").write_text("preserve", encoding="ascii")
        parent.rename(displaced)
        parent.symlink_to(outside, target_is_directory=True)
        process.close()
        trusted.close()
        for name in (process.name, trusted.name):
            assert (outside_run / name / "sentinel").read_text(encoding="ascii") == "preserve"
            assert (displaced / "run" / name / "owned").read_bytes() == b"owned"
    finally:
        process.close()
        trusted.close()
        run.close()
        if parent.is_symlink():
            parent.unlink()
        if displaced.exists():
            displaced.rename(parent)


def _install_stat_to_remove_cleanup_race(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Swap the owned inode after lookup and preserve a canonical replacement."""

    original_remove = module._remove_owned_directory
    original_rename = module.os.rename
    original_rmdir = module.os.rmdir
    original_mkdir = module.os.mkdir
    original_open = module.os.open
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

    monkeypatch.setattr(module.os, "rename", racing_rename)
    monkeypatch.setattr(module.os, "rmdir", racing_rmdir)
    monkeypatch.setattr(module, "_remove_owned_directory", armed_remove)
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


def test_recursive_cleanup_child_swap_never_deletes_nonowned_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = QUALIFIER._open_or_create_secure_root(
        tmp_path / "recursive-cleanup-root",
        "recursive cleanup root",
    )
    child = QUALIFIER._open_child_directory(
        root,
        "owned-child",
        "recursive owned child",
        mode=0o700,
        create=True,
    )
    QUALIFIER._write_regular_relative(
        child.descriptor,
        PurePosixPath("owned-sentinel"),
        b"owned-preserve-exact",
        "recursive owned sentinel",
    )
    child.close()
    escaped = tmp_path / "recursive-escaped-owned-child"
    replacement = tmp_path / "recursive-nonowned-replacement"
    replacement.mkdir(mode=0o700)
    replacement_sentinel = replacement / "replacement-sentinel"
    replacement_sentinel.write_bytes(b"replacement-preserve-exact")
    original_open = QUALIFIER.os.open
    original_rename = QUALIFIER.os.rename
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

    monkeypatch.setattr(QUALIFIER.os, "open", racing_open)
    removed = QUALIFIER._remove_owned_directory(root)

    assert attacked is False
    assert removed is False
    assert (
        tmp_path / "recursive-cleanup-root/owned-child/owned-sentinel"
    ).read_bytes() == b"owned-preserve-exact"
    assert replacement_sentinel.read_bytes() == b"replacement-preserve-exact"


def test_v1_public_finalizer_never_enters_name_based_remove_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    outside = tmp_path / "v1-cleanup-race-outside"
    outside.mkdir()
    outside_sentinel = outside / "sentinel"
    outside_sentinel.write_bytes(b"outside-preserve-exact")
    state = _install_stat_to_remove_cleanup_race(QUALIFIER, monkeypatch)
    report = QUALIFIER._qualify_impl(
        authority_path=fixture["authority_path"],
        authority_sha256=fixture["authority_sha256"],
        source_root=fixture["source"],
        artifact_root=fixture["artifact"],
        timeout_seconds=2.0,
    )
    assert state["attacked"] is False
    assert report["cleanup"]["delete_attempts"] == 0
    assert [root["kind"] for root in report["cleanup"]["retained_roots"]] == ["worker-process-root"]
    assert outside_sentinel.read_bytes() == b"outside-preserve-exact"


def test_v2_public_finalizer_retains_both_roots_without_name_based_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _authority_v2(monkeypatch)
    authority_path = tmp_path / "cleanup-v2-authority.json"
    authority_path.write_bytes(QUALIFIER.canonical_json_bytes(authority))
    roots: dict[str, Path] = {}
    for name in ("source", "dependency", "capsule"):
        roots[name] = tmp_path / f"cleanup-v2-{name}"
        roots[name].mkdir(mode=0o700)
    artifact = tmp_path / "cleanup-v2-artifact"
    run = tmp_path / "cleanup-v2-run"
    monkeypatch.setattr(QUALIFIER, "_load_authority_v2", lambda *_: authority)
    monkeypatch.setattr(
        QUALIFIER,
        "_verify_external_tree",
        lambda root, *_args, **_kwargs: (Path(root), {}),
    )
    monkeypatch.setattr(QUALIFIER, "_load_gate_inputs", lambda *_: ({}, {}, []))
    monkeypatch.setattr(
        QUALIFIER,
        "_materialize_tree_preimage_v2",
        lambda _trusted, *, kind, **_kwargs: roots[kind],
    )
    monkeypatch.setattr(QUALIFIER, "_seal_preimage_namespace_v2", lambda *_: None)
    monkeypatch.setattr(QUALIFIER, "_run_capsule_roster_v2", lambda **_: [])

    def fake_worker_v2(**kwargs: object) -> bytes:
        process_root = kwargs["process_root"]
        for name in ("stdout.json", "stderr.txt"):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=process_root.descriptor,
            )
            if name == "stdout.json":
                os.write(descriptor, b"{}")
            os.close(descriptor)
        return b"{}"

    monkeypatch.setattr(QUALIFIER, "_run_worker_v2", fake_worker_v2)
    monkeypatch.setattr(
        QUALIFIER,
        "_verify_worker_output_v2",
        lambda *_: (
            {
                "counts": {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
                "roles": dict(QUALIFIER.EXPECTED_ROLE_COUNTS),
            },
            [],
            "sha256:" + "8" * 64,
            b'{"normalized":true}',
        ),
    )
    monkeypatch.setattr(QUALIFIER, "_verify_tree_preimage_at_v2", lambda *_, **__: None)
    monkeypatch.setattr(QUALIFIER, "_validate_report_v2", lambda *_: None)
    monkeypatch.setattr(QUALIFIER, "_publish_qualification", lambda *_: None)
    cleanup_calls = 0
    state = _install_stat_to_remove_cleanup_race(QUALIFIER, monkeypatch)
    racing_remove = QUALIFIER._remove_owned_directory

    def counted_remove(handle: object) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return racing_remove(handle)

    monkeypatch.setattr(QUALIFIER, "_remove_owned_directory", counted_remove)
    report = QUALIFIER._qualify_v2_impl(
        authority_path=authority_path,
        authority_sha256=authority["manifest_sha256"],
        source_bundle_root=roots["source"],
        dependency_bundle_root=roots["dependency"],
        capsule_root=roots["capsule"],
        artifact_root=artifact,
        run_root=run,
        run_nonce="8" * 64,
        timeout_seconds=1.0,
    )
    assert cleanup_calls == 0
    assert state["attacked"] is False
    assert [root["kind"] for root in report["cleanup"]["retained_roots"]] == [
        "production-process-root",
        "production-trusted-root",
    ]


def _materialize_dependency_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict]:
    root = tmp_path / "dependency"
    descriptor = _descriptor("dependency")
    for index, record in enumerate(descriptor["files"]):
        raw = bytes([index % 251]) * record["size"]
        path = root / record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(record["mode"])
        record["sha256"] = QUALIFIER._bytes_hash(raw)
    roster = QUALIFIER._dependency_roster_digest(root, descriptor["files"])
    monkeypatch.setattr(QUALIFIER, "V2_DEPENDENCY_ROSTER_SHA256", roster)
    descriptor["roster_sha256"] = roster
    body = {key: value for key, value in descriptor.items() if key != "manifest_sha256"}
    descriptor["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    (root / "bundle.json").write_bytes(QUALIFIER.canonical_json_bytes(descriptor))
    (root / "bundle.json").chmod(0o444)
    for directory in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    root.chmod(0o555)
    return root, descriptor


@pytest.mark.parametrize("attack", ["missing", "extra", "symlink", "mode", "bytes"])
def test_external_dependency_tree_attacks_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    root, descriptor = _materialize_dependency_bundle(tmp_path, monkeypatch)
    verified, contents = QUALIFIER._verify_external_tree(
        root, descriptor, manifest_name="bundle.json", label="dependency bundle"
    )
    assert verified == root
    assert len(contents) == 144
    root.chmod(0o755)
    target = root / descriptor["files"][0]["path"]
    target.parent.chmod(0o755)
    if attack == "missing":
        target.unlink()
    elif attack == "extra":
        (root / "extra.py").write_text("x")
        (root / "extra.py").chmod(0o444)
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "outside")
    elif attack == "mode":
        target.chmod(0o644)
    else:
        target.chmod(0o644)
        target.write_bytes(b"drift")
        target.chmod(0o444)
    root.chmod(0o555)
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._verify_external_tree(
            root, descriptor, manifest_name="bundle.json", label="dependency bundle"
        )


def _retained_root_fixture(
    kind: str, logical_root: str, anchor: str, locator: str, digest_character: str
) -> dict:
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
    return {**body, "root_id": _hash(body)}


def _unmeasurable_retained_root_fixture(
    kind: str, logical_root: str, anchor: str, locator: str
) -> dict:
    body = {
        "state": "unmeasurable",
        "kind": kind,
        "logical_root": logical_root,
        "anchor": anchor,
        "locator": locator,
        "creation_observed": True,
        "reason": "injected retained-root measurement failure",
    }
    return {**body, "root_id": _hash(body)}


def _blocked_qualification_fixture(*, production: bool, roots: list[dict]) -> dict:
    report = {
        "schema_version": 2 if production else 1,
        "qualification_id": (
            QUALIFIER.V2_QUALIFICATION_ID if production else QUALIFIER.QUALIFICATION_ID
        ),
        "status": "blocked",
        "claim": "no_qualification_claim",
        "reason": "injected blocked qualification",
        "cleanup": {
            "status": "cleanup_deferred",
            "gc_policy": QUALIFIER.GC_POLICY,
            "delete_attempts": 0,
            "retained_roots": roots,
        },
    }
    if production:
        report["qualification_kind"] = "production-capsule-v2"
    return report


@pytest.mark.parametrize(
    ("production", "roots"),
    [
        (
            False,
            [
                _retained_root_fixture(
                    "qualification-publication-partial-root",
                    "qualification-publication-partial",
                    "artifact-root",
                    "qualifications/partial-v1",
                    "1",
                )
            ],
        ),
        (
            True,
            [
                _retained_root_fixture(
                    "production-trusted-root",
                    "trusted",
                    "run-root",
                    ".w3-trusted-forbidden",
                    "2",
                )
            ],
        ),
    ],
    ids=("v1-publication-without-worker", "v2-trusted-without-process"),
)
def test_blocked_qualification_rehashed_cleanup_prefixes_fail_schema_and_manual(
    production: bool, roots: list[dict]
) -> None:
    report = _blocked_qualification_fixture(production=production, roots=deepcopy(roots))
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))
    with pytest.raises(QUALIFIER.QualificationBlocked, match="blocked retained root order"):
        QUALIFIER._validate_blocked_report(report, production=production)


@pytest.mark.parametrize("production", [False, True], ids=("v1", "v2"))
@pytest.mark.parametrize("state", ["sealed", "unmeasurable"])
def test_blocked_qualification_allows_only_ordered_prefixes_in_both_root_states(
    production: bool, state: str
) -> None:
    definitions = [
        (
            "production-process-root" if production else "worker-process-root",
            "process",
            "run-root" if production else "artifact-root",
            ".w3-production-allowed" if production else ".w3-worker-allowed",
            "3",
        )
    ]
    if production:
        definitions.append(
            (
                "production-trusted-root",
                "trusted",
                "run-root",
                ".w3-trusted-allowed",
                "4",
            )
        )
    definitions.append(
        (
            "qualification-publication-partial-root",
            "qualification-publication-partial",
            "artifact-root",
            "qualifications/partial-allowed",
            "5",
        )
    )
    roots = [
        (
            _retained_root_fixture(kind, logical, anchor, locator, digest)
            if state == "sealed"
            else _unmeasurable_retained_root_fixture(kind, logical, anchor, locator)
        )
        for kind, logical, anchor, locator, digest in definitions
    ]
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    for length in range(len(roots) + 1):
        report = _blocked_qualification_fixture(
            production=production,
            roots=deepcopy(roots[:length]),
        )
        assert list(Draft202012Validator(schema).iter_errors(report)) == []
        QUALIFIER._validate_blocked_report(report, production=production)


def _v2_report() -> dict:
    roles = (
        ("candidate-f1", "F-1", "author"),
        ("candidate-f2", "F-2", "before"),
        ("candidate-f2", "F-2", "after"),
        ("candidate-f3", "F-3", "mutated"),
        ("candidate-f3", "F-3", "fixed"),
    )
    body = {
        "schema_version": 2,
        "qualification_id": QUALIFIER.V2_QUALIFICATION_ID,
        "qualification_kind": "production-capsule-v2",
        "status": "qualified",
        "claim": QUALIFIER.V2_CLAIM,
        "authority_manifest_sha256": "sha256:" + "1" * 64,
        "ratification_evidence_sha256": QUALIFIER.V2_KIMI_REPORT_SHA256,
        "project_revision": QUALIFIER.V2_PROJECT_SHA,
        "source_bundle_manifest_sha256": "sha256:" + "2" * 64,
        "dependency_bundle_manifest_sha256": "sha256:" + "3" * 64,
        "dependency_roster_sha256": QUALIFIER.V2_DEPENDENCY_ROSTER_SHA256,
        "capsule_manifest_sha256": "sha256:" + "4" * 64,
        "candidate_manifest_sha256": QUALIFIER.V2_CANDIDATE_MANIFEST_SHA256,
        "semantic_registry_sha256": QUALIFIER.V2_SEMANTIC_REGISTRY_SHA256,
        "worker_input_sha256": "sha256:" + "5" * 64,
        "worker_output_sha256": "sha256:" + "6" * 64,
        "launcher": QUALIFIER._launcher_identity_v2(),
        "counts": {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "roles": dict(QUALIFIER.EXPECTED_ROLE_COUNTS),
        "executions": [
            {
                "candidate_id": candidate,
                "family": family,
                "role": role,
                "request_sha256": "sha256:" + "7" * 64,
                "capsule_envelope_sha256": "sha256:" + "8" * 64,
                "oracle_envelope_sha256": "sha256:" + "9" * 64,
                "result_sha256": "sha256:" + "a" * 64,
                "artifact_path": f"artifacts/{candidate}/{role}.json",
                "artifact_sha256": "sha256:" + "b" * 64,
            }
            for candidate, family, role in roles
        ],
        "non_claims": list(QUALIFIER.V2_NON_CLAIMS),
        "cleanup": {
            "status": "cleanup_deferred",
            "gc_policy": QUALIFIER.GC_POLICY,
            "delete_attempts": 0,
            "retained_roots": [
                _retained_root_fixture(
                    "production-process-root", "process", "run-root", ".w3-production-a", "c"
                ),
                _retained_root_fixture(
                    "production-trusted-root", "trusted", "run-root", ".w3-trusted-b", "d"
                ),
            ],
        },
    }
    return {**body, "manifest_sha256": QUALIFIER.canonical_hash(body)}


def test_v2_report_is_schema_valid_and_keeps_claims_separate() -> None:
    report = _v2_report()
    QUALIFIER._validate_report_v2(report, report["launcher"])
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report)) == []
    assert "no_w1_15_of_15_claim" in report["non_claims"]
    assert "no_semantic_accuracy_claim" in report["non_claims"]


@pytest.mark.parametrize(("files", "valid"), [(512, True), (513, False)])
def test_v2_process_root_schema_and_manual_caps_agree(files: int, valid: bool) -> None:
    report = _v2_report()
    root = report["cleanup"]["retained_roots"][0]
    root["counts"]["files"] = files
    root["root_id"] = _hash({key: value for key, value in root.items() if key != "root_id"})
    report["manifest_sha256"] = _manifest_hash(report)
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    schema_errors = list(Draft202012Validator(schema).iter_errors(report))
    if valid:
        assert schema_errors == []
        QUALIFIER._validate_report_v2(report, report["launcher"])
    else:
        assert schema_errors
        with pytest.raises(QUALIFIER.QualificationBlocked, match="counts exceed"):
            QUALIFIER._validate_report_v2(report, report["launcher"])


@pytest.mark.parametrize(
    "attack",
    ["kind", "logical-root", "anchor", "state", "order", "trusted-over-cap"],
)
def test_v2_qualified_cleanup_schema_and_manual_semantics_agree(attack: str) -> None:
    report = _v2_report()
    roots = report["cleanup"]["retained_roots"]
    if attack == "kind":
        roots[0]["kind"] = "production-trusted-root"
    elif attack == "logical-root":
        roots[0]["logical_root"] = "trusted"
    elif attack == "anchor":
        roots[0]["anchor"] = "artifact-root"
    elif attack == "state":
        body = {
            "state": "unmeasurable",
            "kind": "production-process-root",
            "logical_root": "process",
            "anchor": "run-root",
            "locator": roots[0]["locator"],
            "creation_observed": True,
            "reason": "injected qualified measurement failure",
        }
        roots[0] = {**body, "root_id": _hash(body)}
    elif attack == "order":
        roots.reverse()
    else:
        roots[1]["counts"]["files"] = 4097
    for root in roots:
        root["root_id"] = _hash({key: value for key, value in root.items() if key != "root_id"})
    report["manifest_sha256"] = _manifest_hash(report)
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report))
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_report_v2(report, report["launcher"])


def test_v1_worker_cleanup_schema_and_manual_caps_identity_and_state_agree(
    tmp_path: Path,
) -> None:
    report = _qualify(_fixture(tmp_path))
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    boundary = deepcopy(report)
    boundary_root = boundary["cleanup"]["retained_roots"][0]
    boundary_root["counts"]["files"] = 512
    boundary_root["root_id"] = _hash(
        {key: value for key, value in boundary_root.items() if key != "root_id"}
    )
    boundary["manifest_sha256"] = _manifest_hash(boundary)
    assert list(Draft202012Validator(schema).iter_errors(boundary)) == []
    QUALIFIER._validate_report(boundary, boundary["launcher"])

    attacks = []
    for field, value in (
        ("files", 513),
        ("kind", "production-process-root"),
        ("anchor", "run-root"),
    ):
        changed = deepcopy(report)
        root = changed["cleanup"]["retained_roots"][0]
        if field == "files":
            root["counts"][field] = value
        else:
            root[field] = value
        root["root_id"] = _hash({key: item for key, item in root.items() if key != "root_id"})
        changed["manifest_sha256"] = _manifest_hash(changed)
        attacks.append(changed)
    changed = deepcopy(report)
    previous = changed["cleanup"]["retained_roots"][0]
    body = {
        "state": "unmeasurable",
        "kind": "worker-process-root",
        "logical_root": "process",
        "anchor": "artifact-root",
        "locator": previous["locator"],
        "creation_observed": True,
        "reason": "injected qualified measurement failure",
    }
    changed["cleanup"]["retained_roots"][0] = {**body, "root_id": _hash(body)}
    changed["manifest_sha256"] = _manifest_hash(changed)
    attacks.append(changed)
    assert len(attacks) == 4
    for changed in attacks:
        assert list(Draft202012Validator(schema).iter_errors(changed))
        with pytest.raises(QUALIFIER.QualificationBlocked):
            QUALIFIER._validate_report(changed, changed["launcher"])


@pytest.mark.parametrize(
    "attack",
    [
        "unmeasurable-qualified",
        "snapshot-drift",
        "physical-snapshot-split",
        "bool-count",
        "files-cap",
        "directories-cap",
        "bytes-cap",
        "malformed-hash",
        "duplicate-root-id",
        "duplicate-kind",
        "wrong-order",
        "missing-root",
        "kind-swap",
        "anchor-swap",
        "locator-traversal",
        "status-drift",
        "policy-drift",
        "delete-attempt-bool",
    ],
)
def test_v2_retained_cleanup_mutation_contract_fails_closed(attack: str) -> None:
    cleanup = deepcopy(_v2_report()["cleanup"])
    roots = cleanup["retained_roots"]
    if attack == "unmeasurable-qualified":
        body = {
            "state": "unmeasurable",
            "kind": "production-process-root",
            "logical_root": "process",
            "anchor": "run-root",
            "locator": ".w3-production-a",
            "creation_observed": True,
            "reason": "measurement failed",
        }
        roots[0] = {**body, "root_id": _hash(body)}
    elif attack == "snapshot-drift":
        roots[0]["snapshot_second_sha256"] = "sha256:" + "f" * 64
    elif attack == "physical-snapshot-split":
        roots[0]["physical_roster_sha256"] = "sha256:" + "f" * 64
    elif attack == "bool-count":
        roots[0]["counts"]["files"] = True
    elif attack == "files-cap":
        roots[0]["counts"]["files"] = 513
    elif attack == "directories-cap":
        roots[0]["counts"]["directories"] = 513
    elif attack == "bytes-cap":
        roots[0]["counts"]["bytes"] = 128 * 1024 * 1024 + 1
    elif attack == "malformed-hash":
        roots[0]["normalized_roster_sha256"] = "sha256:ABC"
    elif attack == "duplicate-root-id":
        roots[1]["root_id"] = roots[0]["root_id"]
    elif attack == "duplicate-kind":
        roots[1]["kind"] = "production-process-root"
        roots[1]["logical_root"] = "process"
    elif attack == "wrong-order":
        roots.reverse()
    elif attack == "missing-root":
        roots.pop()
    elif attack == "kind-swap":
        roots[0]["kind"] = "production-trusted-root"
    elif attack == "anchor-swap":
        roots[0]["anchor"] = "artifact-root"
    elif attack == "locator-traversal":
        roots[0]["locator"] = "../escape"
    elif attack == "status-drift":
        cleanup["status"] = "cleaned"
    elif attack == "policy-drift":
        cleanup["gc_policy"] = "automatic"
    else:
        cleanup["delete_attempts"] = False
    if attack not in {"malformed-hash", "duplicate-root-id", "unmeasurable-qualified"}:
        for root in roots:
            root["root_id"] = _hash({key: value for key, value in root.items() if key != "root_id"})
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_cleanup(
            cleanup,
            qualified=True,
            expected_kinds=("production-process-root", "production-trusted-root"),
        )


@pytest.mark.parametrize("attack", ["symlink", "fifo", "socket", "device", "hardlink"])
def test_retained_root_special_entry_attacks_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    parent = tmp_path / attack
    parent.mkdir()
    root = QUALIFIER._open_or_create_secure_root(parent / "root", "retained attack root")
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
        original_stat = QUALIFIER.os.stat

        def device_stat(*args: object, **kwargs: object) -> os.stat_result:
            observed = original_stat(*args, **kwargs)
            if args and args[0] == "entry" and kwargs.get("dir_fd") == root.descriptor:
                values = list(observed)
                values[0] = stat.S_IFCHR | 0o600
                return os.stat_result(values)
            return observed

        monkeypatch.setattr(QUALIFIER.os, "stat", device_stat)
    else:
        os.link(outside, root.path / "entry")
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked):
            QUALIFIER._sealed_retained_root(
                descriptor=root.descriptor,
                handle=root,
                kind="worker-process-root",
                logical_root="process",
                anchor="artifact-root",
                locator="root",
            )
        assert outside.read_bytes() == b"outside-preserve-exact"
    finally:
        root.close()


@pytest.mark.parametrize(
    ("kind", "logical_root", "anchor"),
    [
        ("worker-process-root", "process", "artifact-root"),
        ("production-process-root", "process", "run-root"),
        ("production-trusted-root", "trusted", "run-root"),
        (
            "qualification-publication-partial-root",
            "qualification-publication-partial",
            "artifact-root",
        ),
    ],
)
def test_each_qualifier_retained_root_cap_class_blocks_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    logical_root: str,
    anchor: str,
) -> None:
    parent = tmp_path / kind
    parent.mkdir()
    root = QUALIFIER._open_or_create_secure_root(parent / "root", "cap root")
    descriptor = os.open(
        "entry",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=root.descriptor,
    )
    os.write(descriptor, b"x")
    os.close(descriptor)
    monkeypatch.setitem(QUALIFIER.RETAINED_ROOT_CAPS, kind, (0, 1, 0, 0))
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="cap"):
            QUALIFIER._sealed_retained_root(
                descriptor=root.descriptor,
                handle=root,
                kind=kind,
                logical_root=logical_root,
                anchor=anchor,
                locator="root",
            )
    finally:
        root.close()


def test_retained_double_snapshot_blocks_content_rewrite_and_mode_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "snapshot-restore"
    parent.mkdir()
    root = QUALIFIER._open_or_create_secure_root(parent / "root", "snapshot restore root")
    path = root.path / "entry"
    path.write_bytes(b"original")
    path.chmod(0o600)
    original_snapshot = QUALIFIER._snapshot_retained_tree
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

    monkeypatch.setattr(QUALIFIER, "_snapshot_retained_tree", rewrite_after_first)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="between retained snapshots"):
            QUALIFIER._sealed_retained_root(
                descriptor=root.descriptor,
                handle=root,
                kind="worker-process-root",
                logical_root="process",
                anchor="artifact-root",
                locator="root",
            )
        assert path.read_bytes() == b"original"
        assert stat.S_IMODE(path.stat().st_mode) == 0o444
    finally:
        root.close()


def test_worker_stdout_is_physically_canonicalized_before_retained_snapshot(
    tmp_path: Path,
) -> None:
    descriptors = []
    canonical = b'{"status":"completed"}'
    roots = []
    try:
        for index, raw in enumerate(
            (
                b'{"run_nonce":"' + b"a" * 64 + b'","status":"completed"}',
                b'{"run_nonce":"' + b"b" * 64 + b'","status":"completed"}',
            )
        ):
            root = QUALIFIER._open_or_create_secure_root(
                tmp_path / f"canonical-process-{index}", "canonical process root"
            )
            roots.append(root)
            stdout = root.path / "stdout.json"
            stdout.write_bytes(raw)
            stdout.chmod(0o600)
            QUALIFIER._canonicalize_owned_regular_at(root, "stdout.json", raw, canonical)
            assert stdout.read_bytes() == canonical
            descriptors.append(
                QUALIFIER._sealed_retained_root(
                    descriptor=root.descriptor,
                    handle=root,
                    kind="production-process-root",
                    logical_root="process",
                    anchor="run-root",
                    locator=f"process-{index}",
                )
            )
        assert [item["physical_roster_sha256"] for item in descriptors] == [
            descriptors[0]["normalized_roster_sha256"],
            descriptors[0]["normalized_roster_sha256"],
        ]
        assert all(
            item["physical_roster_sha256"] == item["normalized_roster_sha256"]
            for item in descriptors
        )
    finally:
        for root in roots:
            root.close()


def test_worker_stdout_canonicalization_blocks_path_replacement_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = QUALIFIER._open_or_create_secure_root(
        tmp_path / "canonicalization-race", "canonicalization race root"
    )
    stdout = root.path / "stdout.json"
    displaced = root.path / "stdout-owned-displaced"
    raw = b'{"run_nonce":"physical"}'
    canonical = b'{"status":"completed"}'
    stdout.write_bytes(raw)
    stdout.chmod(0o600)
    original_stat = QUALIFIER.os.stat
    calls = 0

    def racing_stat(*args: object, **kwargs: object) -> os.stat_result:
        nonlocal calls
        if args and args[0] == "stdout.json" and kwargs.get("dir_fd") == root.descriptor:
            calls += 1
            if calls == 3:
                os.rename(
                    "stdout.json",
                    displaced.name,
                    src_dir_fd=root.descriptor,
                    dst_dir_fd=root.descriptor,
                )
                replacement = os.open(
                    "stdout.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=root.descriptor,
                )
                os.write(replacement, b"replacement-preserve-exact")
                os.close(replacement)
        return original_stat(*args, **kwargs)

    monkeypatch.setattr(QUALIFIER.os, "stat", racing_stat)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="changed"):
            QUALIFIER._canonicalize_owned_regular_at(root, "stdout.json", raw, canonical)
        assert stdout.read_bytes() == b"replacement-preserve-exact"
        assert displaced.read_bytes() == canonical
    finally:
        root.close()


def test_cleanup_duplicate_json_key_is_rejected_by_both_standalone_parsers() -> None:
    duplicated = b'{"status":"cleanup_deferred","status":"cleanup_deferred"}'
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._decode_json(duplicated, "duplicate cleanup", require_canonical=True)
    with pytest.raises(BRIDGE.BridgeGateBlocked):
        BRIDGE._decode_canonical(duplicated, "duplicate cleanup")


def test_retained_creation_intent_survives_descriptor_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = QUALIFIER._open_or_create_secure_root(tmp_path / "parent", "intent parent")
    registry = QUALIFIER._RetainedRootRegistry()

    def fail_observe(*_args: object) -> None:
        raise QUALIFIER.QualificationBlocked("injected retained descriptor failure")

    monkeypatch.setattr(registry, "observe", fail_observe)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="injected"):
            QUALIFIER._create_random_directory(
                parent,
                ".w3-intent-",
                "intent root",
                registry=registry,
                kind="worker-process-root",
                logical_root="process",
                anchor="artifact-root",
            )
        cleanup = registry.cleanup(qualified=False)
        assert len(cleanup["retained_roots"]) == 1
        assert cleanup["retained_roots"][0]["state"] == "unmeasurable"
        assert cleanup["retained_roots"][0]["creation_observed"] is True
        assert list(parent.path.glob(".w3-intent-*"))
    finally:
        registry.close()
        parent.close()


def test_retained_precreation_failure_does_not_claim_an_observed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = QUALIFIER._open_or_create_secure_root(tmp_path / "precreate-parent", "parent")
    registry = QUALIFIER._RetainedRootRegistry()

    def fail_before_creation(*_args: object, **_kwargs: object) -> None:
        raise QUALIFIER.QualificationBlocked("injected pre-creation failure")

    monkeypatch.setattr(QUALIFIER, "_open_child_directory", fail_before_creation)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pre-creation"):
            QUALIFIER._create_random_directory(
                parent,
                ".w3-precreate-",
                "precreate root",
                registry=registry,
                kind="worker-process-root",
                logical_root="process",
                anchor="artifact-root",
            )
        assert registry.cleanup(qualified=False)["retained_roots"] == []
        assert list(parent.path.iterdir()) == []
    finally:
        registry.close()
        parent.close()


@pytest.mark.parametrize("mutation", ["claim", "count", "role", "nonce", "manifest", "nonclaim"])
def test_v2_report_claim_and_replay_mutations_fail_closed(mutation: str) -> None:
    report = _v2_report()
    if mutation == "claim":
        report["claim"] = "semantic_accuracy_99"
    elif mutation == "count":
        report["counts"]["executions"] = 10
    elif mutation == "role":
        report["executions"][0]["role"] = "before"
    elif mutation == "nonce":
        report["run_nonce"] = "0" * 64
    elif mutation == "manifest":
        report["manifest_sha256"] = "sha256:" + "0" * 64
    else:
        report["non_claims"].remove("no_semantic_accuracy_claim")
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._validate_report_v2(report, report["launcher"])


def _materialize_capsule_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    root = tmp_path / "capsule-tree"
    descriptor = _capsule_descriptor(monkeypatch)
    by_role = {}
    for index, record in enumerate(descriptor["files"]):
        raw = bytes([index + 1]) * record["size"]
        target = root / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(record["mode"])
        record["sha256"] = QUALIFIER._bytes_hash(raw)
        by_role[record["role"]] = record
    for role in ("node", "runner", "tsx"):
        descriptor[role] = {key: by_role[role][key] for key in ("path", "sha256", "mode")}
    monkeypatch.setattr(QUALIFIER, "V2_NODE_BINARY_SHA256", descriptor["node"]["sha256"])
    monkeypatch.setattr(QUALIFIER, "V2_RUNNER_SHA256", descriptor["runner"]["sha256"])
    descriptor["roster_sha256"] = QUALIFIER.canonical_hash(descriptor["files"])
    body = {key: item for key, item in descriptor.items() if key != "manifest_sha256"}
    descriptor["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    (root / "capsule.json").write_bytes(QUALIFIER.canonical_json_bytes(descriptor))
    (root / "capsule.json").chmod(0o444)
    for directory in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    root.chmod(0o555)
    return root, descriptor


def _execute_capsule_tree_attack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    root, descriptor = _materialize_capsule_tree(tmp_path, monkeypatch)
    verified, contents = QUALIFIER._verify_external_tree(
        root, descriptor, manifest_name="capsule.json", label="runtime capsule"
    )
    assert verified == root
    assert len(contents) == 3
    root.chmod(0o755)
    target = root / descriptor["files"][0]["path"]
    target.parent.chmod(0o755)
    if attack == "missing":
        target.unlink()
    elif attack == "extra":
        extra = root / "extra.txt"
        extra.write_text("extra")
        extra.chmod(0o444)
    else:
        target.unlink()
        outside = tmp_path / "capsule-outside"
        outside.write_text("outside")
        target.symlink_to(outside)
    root.chmod(0o555)
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._verify_external_tree(
            root, descriptor, manifest_name="capsule.json", label="runtime capsule"
        )


def _matrix_worker_request() -> dict:
    roles = (
        ("candidate-f1", "F-1", "author", "ok"),
        ("candidate-f2", "F-2", "before", "ok"),
        ("candidate-f2", "F-2", "after", "ok"),
        ("candidate-f3", "F-3", "mutated", "invalid"),
        ("candidate-f3", "F-3", "fixed", "ok"),
    )
    return {
        "schema_version": 2,
        "protocol": WORKER.PROTOCOL,
        "authority_manifest_sha256": "sha256:" + "1" * 64,
        "source_bundle_manifest_sha256": "sha256:" + "2" * 64,
        "dependency_bundle_manifest_sha256": "sha256:" + "3" * 64,
        "capsule_manifest_sha256": "sha256:" + "4" * 64,
        "candidate_manifest_sha256": "sha256:" + "5" * 64,
        "semantic_registry_sha256": "sha256:" + "6" * 64,
        "run_nonce": "7" * 64,
        "expected": {"candidates": 3, "executions": 5, "roles": dict(WORKER.ROLE_COUNTS)},
        "executions": [
            {
                "candidate_id": candidate,
                "family": family,
                "role": role,
                "expected_status": status,
                "request": {"schema_version": 1, "role": role},
                "capsule_envelope": {"fixture": True},
            }
            for candidate, family, role, status in roles
        ],
    }


def _execute_worker_request_mutation(case: str) -> None:
    request = _matrix_worker_request()
    if case == "request-schema":
        request["schema_version"] = True
    elif case == "request-protocol":
        request["protocol"] = "fixture-v1"
    elif case == "request-id":
        request["executions"][0]["candidate_id"] = "../escape"
    elif case == "request-role":
        request["executions"][0]["role"] = "before"
    elif case == "request-family":
        request["executions"][0]["family"] = "F-3"
    elif case == "request-capsule":
        request["capsule_manifest_sha256"] = "not-a-hash"
    else:
        request["authority_manifest_sha256"] = "sha256:short"
    with pytest.raises(WORKER.ProductionWorkerError):
        WORKER._validated_request(request)


@pytest.mark.parametrize(
    ("field", "key", "message"),
    [
        ("counts", "candidates", "exact integer 3"),
        ("roles", "author", "exact integer 1"),
    ],
)
def test_v2_worker_output_rejects_rehashed_boolean_count_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    key: str,
    message: str,
) -> None:
    request = _matrix_worker_request()
    for row in request["executions"]:
        body = {
            "schema_version": 2,
            "protocol": "metis-runtime-capsule-v2",
            "execution_id": f"{row['candidate_id']}.{row['role']}",
            "request_sha256": QUALIFIER.canonical_hash(row["request"]),
            "capsule_manifest_sha256": request["capsule_manifest_sha256"],
            "execution_policy": dict(QUALIFIER.V2_CAPSULE_EXECUTION_POLICY),
            "oracle_envelope": {"result": {"status": row["expected_status"]}},
        }
        row["capsule_envelope"] = {
            **body,
            "run_nonce": request["run_nonce"],
            "manifest_sha256": QUALIFIER.canonical_hash(body),
        }
    process = tmp_path / "bool-output-process"
    output = process / "output"
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    monkeypatch.setenv("W3_PRODUCTION_PROCESS_ROOT", str(process))
    monkeypatch.setenv("W3_PRODUCTION_OUTPUT_ROOT", str(output))
    monkeypatch.setattr(WORKER, "verify_capsule_oracle_envelope", lambda *args, **_: args[0])
    monkeypatch.setattr(
        WORKER,
        "normalize_capsule_oracle_envelope",
        lambda value: {name: item for name, item in value.items() if name != "run_nonce"},
    )
    worker_output = WORKER.execute(request)
    for item in output.rglob("*"):
        item.chmod(0o700 if item.is_dir() else 0o600)
    worker_output[field][key] = True
    body = {
        name: item
        for name, item in worker_output.items()
        if name not in {"run_nonce", "manifest_sha256"}
    }
    worker_output["manifest_sha256"] = QUALIFIER.canonical_hash(body)

    def accept_capsule(envelope: dict, **_: object) -> tuple[dict, dict]:
        normalized = {name: item for name, item in envelope.items() if name != "run_nonce"}
        return normalized, envelope["oracle_envelope"]["result"]

    monkeypatch.setattr(QUALIFIER, "_verify_capsule_envelope_v2", accept_capsule)
    monkeypatch.setattr(QUALIFIER, "_verify_semantics", lambda *_: None)
    output_handle = QUALIFIER._open_or_create_secure_root(output, "test production output")
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match=message):
            QUALIFIER._verify_worker_output_v2(
                QUALIFIER.canonical_json_bytes(worker_output),
                output_handle,
                request,
                {"capsule": {"manifest_sha256": request["capsule_manifest_sha256"]}},
                {},
                {},
            )
    finally:
        output_handle.close()


def _matrix_capsule_envelope() -> tuple[dict, dict, dict]:
    request = {"schema_version": 1, "source": "fixture"}
    authority = {"capsule": {"manifest_sha256": "sha256:" + "4" * 64}}
    oracle = {"schema_version": 1, "result": {"status": "ok"}, "evidence": {}}
    body = {
        "schema_version": 2,
        "protocol": "metis-runtime-capsule-v2",
        "execution_id": "candidate-f1.author",
        "request_sha256": QUALIFIER.canonical_hash(request),
        "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
        "execution_policy": dict(QUALIFIER.V2_CAPSULE_EXECUTION_POLICY),
        "oracle_envelope": oracle,
    }
    return (
        {**body, "run_nonce": "7" * 64, "manifest_sha256": QUALIFIER.canonical_hash(body)},
        request,
        authority,
    )


def _execute_envelope_mutation(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    envelope, request, authority = _matrix_capsule_envelope()
    monkeypatch.setattr(QUALIFIER, "_verify_envelope", lambda *args, **kwargs: {"status": "ok"})
    if case == "envelope-nonce":
        envelope["run_nonce"] = "8" * 64
    elif case == "envelope-request":
        envelope["request_sha256"] = "sha256:" + "0" * 64
    elif case == "envelope-capsule":
        envelope["capsule_manifest_sha256"] = "sha256:" + "0" * 64
    elif case == "envelope-result":
        envelope["oracle_envelope"]["result"]["status"] = "invalid"
    else:
        envelope["manifest_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(QUALIFIER.QualificationBlocked):
        QUALIFIER._verify_capsule_envelope_v2(
            envelope,
            request=request,
            run_nonce="7" * 64,
            expected_status="ok",
            authority=authority,
        )


def test_capsule_envelope_binds_exact_process_policy_and_ancestor_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, request, authority = _matrix_capsule_envelope()
    monkeypatch.setattr(QUALIFIER, "_verify_envelope", lambda *args, **kwargs: {"status": "ok"})
    envelope["execution_policy"]["capsule_ancestor_slots"] -= 1
    body = {
        key: item for key, item in envelope.items() if key not in {"run_nonce", "manifest_sha256"}
    }
    envelope["manifest_sha256"] = QUALIFIER.canonical_hash(body)

    with pytest.raises(QUALIFIER.QualificationBlocked, match="request and capsule"):
        QUALIFIER._verify_capsule_envelope_v2(
            envelope,
            request=request,
            run_nonce="7" * 64,
            expected_status="ok",
            authority=authority,
        )


def _bridge_authority_and_artifacts() -> tuple[dict, dict, dict[str, bytes]]:
    launcher = {
        "qualifier_path": "/fixture/w3_qualifier.py",
        "qualifier_sha256": "sha256:" + "1" * 64,
        "python_executable": "/fixture/python",
        "python_executable_sha256": "sha256:" + "2" * 64,
        "python_version": "3.13.3",
        "required_flags": ["-I", "-S", "-B"],
        "sandbox_exec_path": "/usr/bin/sandbox-exec",
        "sandbox_exec_sha256": "sha256:" + "3" * 64,
        "sandbox_policy_template_sha256": BRIDGE.PINNED_LAUNCHER_POLICY_SHA256,
        "qualifier_bootstrap_sha256": BRIDGE.QUALIFIER_BOOTSTRAP_SHA256,
    }
    authority = BRIDGE_FIXTURES._authority(launcher)
    report, artifacts = BRIDGE_FIXTURES._qualification(authority)
    return authority, report, artifacts


def _execute_artifact_mutation(case: str) -> None:
    authority, report, artifacts = _bridge_authority_and_artifacts()
    row = report["executions"][0]
    raw = artifacts[row["artifact_path"]]
    if case == "artifact-path":
        report["executions"][0]["artifact_path"] = "../escape.json"
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE._validate_qualification(report, authority, authority["manifest_sha256"])
    elif case == "artifact-bytes":
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE._validate_artifact(raw + b" ", row, authority)
    elif case == "artifact-hash":
        row = deepcopy(row)
        row["artifact_sha256"] = "sha256:" + "0" * 64
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE._validate_artifact(raw, row, authority)
    else:
        report["executions"].pop()
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE._validate_qualification(report, authority, authority["manifest_sha256"])


def _fake_capsule_node_authority(
    tmp_path: Path, runner_source: str
) -> tuple[Path, Path, dict, dict, Path]:
    capsule = tmp_path / "fake-node-capsule"
    node = capsule / "bin/node"
    loader = capsule / "tooling/loader.mjs"
    runner = capsule / "runner.mjs"
    process_root = tmp_path / "fake-node-process"
    node.parent.mkdir(parents=True)
    loader.parent.mkdir(parents=True)
    process_root.mkdir(mode=0o700)
    shutil.copy2(_registered_node(), node)
    node.chmod(0o555)
    loader.write_text("export {};", encoding="utf-8")
    runner.write_text(runner_source, encoding="utf-8")
    capsule_descriptor = {
        "node": {
            "path": "bin/node",
            "sha256": QUALIFIER._bytes_hash(node.read_bytes()),
            "mode": 0o555,
        },
        "tsx": {
            "path": "tooling/loader.mjs",
            "sha256": QUALIFIER._bytes_hash(loader.read_bytes()),
            "mode": 0o444,
        },
        "runner": {
            "path": "runner.mjs",
            "sha256": QUALIFIER._bytes_hash(runner.read_bytes()),
            "mode": 0o444,
        },
        "tooling": {
            "package_sha256": "sha256:" + "1" * 64,
            "lock_sha256": "sha256:" + "2" * 64,
            "node_modules_sha256": "sha256:" + "3" * 64,
        },
        "manifest_sha256": "sha256:" + "4" * 64,
    }
    authority = {"capsule": capsule_descriptor}
    execution = {
        "candidate_id": "candidate-f1",
        "family": "F-1",
        "role": "author",
        "expected_status": "ok",
        "request": {"schema_version": 1, "source": "fixture"},
    }
    return capsule, process_root, authority, execution, node


def test_v2_live_fake_capsule_runner_executes_with_exact_ancestor_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capsule, process_root, authority, execution, _ = _fake_capsule_node_authority(
        tmp_path, "process.stdout.write(JSON.stringify({fixture:true}));"
    )
    observed = {}

    def accept(**kwargs: object) -> dict:
        observed.update(kwargs)
        return {"verified": True}

    monkeypatch.setattr(QUALIFIER, "_capsule_envelope_from_result_v2", accept)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    try:
        result = QUALIFIER._run_capsule_node_v2(
            execution=execution,
            capsule=capsule,
            process_root=process_handle,
            run_nonce="7" * 64,
            timeout_seconds=5.0,
            authority=authority,
        )
    finally:
        process_handle.close()
    assert result == {"verified": True}
    assert observed["result"] == {"fixture": True}


def test_v2_capsule_node_success_retains_invocation_without_cleanup_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capsule, process_root, authority, execution, _ = _fake_capsule_node_authority(
        tmp_path, "process.stdout.write(JSON.stringify({fixture:true}));"
    )
    monkeypatch.setattr(
        QUALIFIER,
        "_capsule_envelope_from_result_v2",
        lambda **_kwargs: {"verified": True},
    )
    cleanup_calls = 0

    def forbidden_cleanup(handle: object) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return False

    monkeypatch.setattr(QUALIFIER, "_remove_owned_directory", forbidden_cleanup)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    try:
        result = QUALIFIER._run_capsule_node_v2(
            execution=execution,
            capsule=capsule,
            process_root=process_handle,
            run_nonce="7" * 64,
            timeout_seconds=5.0,
            authority=authority,
        )
    finally:
        process_handle.close()
    assert result == {"verified": True}
    assert cleanup_calls == 0
    invocation = process_root / "node-invocations/candidate-f1.author"
    assert sorted(path.name for path in invocation.iterdir()) == ["stderr.txt", "stdout.json"]


def test_v2_node_invocation_creation_parent_swap_writes_nothing_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capsule, initial_process, authority, execution, _ = _fake_capsule_node_authority(
        tmp_path, "process.stdout.write(JSON.stringify({fixture:true}));"
    )
    process_parent = tmp_path / "node-invocation-parent"
    process_parent.mkdir(mode=0o700)
    process_root = process_parent / "process"
    initial_process.rename(process_root)
    displaced = tmp_path / "node-invocation-parent-displaced"
    outside = tmp_path / "node-invocation-outside"
    outside.mkdir(mode=0o700)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    original_mkdir = QUALIFIER.os.mkdir
    swapped = False

    def racing_mkdir(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped and name == "node-invocations" and dir_fd is not None:
            process_parent.rename(displaced)
            process_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(QUALIFIER.os, "mkdir", racing_mkdir)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._run_capsule_node_v2(
                execution=execution,
                capsule=capsule,
                process_root=process_handle,
                run_nonce="7" * 64,
                timeout_seconds=5.0,
                authority=authority,
            )
        assert swapped
        assert list(outside.iterdir()) == []
    finally:
        process_handle.close()
        if process_parent.is_symlink():
            process_parent.unlink()
        if displaced.exists():
            displaced.rename(process_parent)


def test_v2_node_stream_parent_swap_keeps_outside_sentinel_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capsule, initial_process, authority, execution, _ = _fake_capsule_node_authority(
        tmp_path, "process.stdout.write(JSON.stringify({fixture:true}));"
    )
    process_parent = tmp_path / "node-stream-parent"
    process_parent.mkdir(mode=0o700)
    process_root = process_parent / "process"
    initial_process.rename(process_root)
    displaced = tmp_path / "node-stream-parent-displaced"
    outside = tmp_path / "node-stream-outside"
    outside_invocation = outside / "process" / "node-invocations" / "candidate-f1.author"
    outside_invocation.mkdir(parents=True, mode=0o700)
    for directory in (
        outside,
        outside / "process",
        outside / "process" / "node-invocations",
        outside_invocation,
    ):
        directory.chmod(0o700)
    sentinel = outside_invocation / "stdout.json"
    sentinel.write_bytes(b"outside-sentinel")
    sentinel.chmod(0o600)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    original_read = QUALIFIER._read_regular_at
    swapped = False

    def racing_read(
        directory_descriptor: int,
        name: str,
        limit: int,
        label: str,
        *,
        mode: int,
    ) -> bytes:
        nonlocal swapped
        if not swapped and label == "capsule Node stdout":
            process_parent.rename(displaced)
            process_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_read(directory_descriptor, name, limit, label, mode=mode)

    monkeypatch.setattr(QUALIFIER, "_read_regular_at", racing_read)
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match="pathname was replaced"):
            QUALIFIER._run_capsule_node_v2(
                execution=execution,
                capsule=capsule,
                process_root=process_handle,
                run_nonce="7" * 64,
                timeout_seconds=5.0,
                authority=authority,
            )
        assert swapped
        assert sentinel.read_bytes() == b"outside-sentinel"
        assert sorted(item.name for item in outside_invocation.iterdir()) == ["stdout.json"]
    finally:
        process_handle.close()
        if process_parent.is_symlink():
            process_parent.unlink()
        if displaced.exists():
            displaced.rename(process_parent)


def test_v2_capsule_executes_measured_preimage_during_external_runner_swap_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (
        "import fs from 'node:fs';let writeDenied=false;"
        "try{fs.writeFileSync(new URL(import.meta.url),'mutated')}"
        "catch(error){writeDenied=error.code==='EPERM'||error.code==='EACCES'};"
        "process.stdout.write(JSON.stringify({fixture:'original',writeDenied}));"
    )
    capsule, process_root, authority, execution, _ = _fake_capsule_node_authority(
        tmp_path, original
    )
    loader = capsule / authority["capsule"]["tsx"]["path"]
    runner = capsule / authority["capsule"]["runner"]["path"]
    loader.chmod(0o444)
    runner.chmod(0o444)
    records = []
    roles = {
        authority["capsule"]["node"]["path"]: "node",
        authority["capsule"]["tsx"]["path"]: "tsx",
        authority["capsule"]["runner"]["path"]: "runner",
    }
    for name, role in roles.items():
        path = capsule / name
        raw = path.read_bytes()
        records.append(
            {
                "path": name,
                "size": len(raw),
                "mode": stat.S_IMODE(path.lstat().st_mode),
                "sha256": QUALIFIER._bytes_hash(raw),
                "role": role,
            }
        )
    descriptor = {
        **authority["capsule"],
        "files": records,
        "manifest_sha256": "",
    }
    body = {key: value for key, value in descriptor.items() if key != "manifest_sha256"}
    descriptor["manifest_sha256"] = QUALIFIER.canonical_hash(body)
    (capsule / "capsule.json").write_bytes(QUALIFIER.canonical_json_bytes(descriptor))
    (capsule / "capsule.json").chmod(0o444)
    for directory in sorted(
        (item for item in capsule.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    capsule.chmod(0o555)
    authority["capsule"] = descriptor
    verified, measured = QUALIFIER._verify_external_tree(
        capsule,
        descriptor,
        manifest_name="capsule.json",
        label="runtime capsule",
    )
    assert verified == capsule
    trusted_root = tmp_path / "trusted-preimages"
    trusted_root.mkdir(mode=0o700)
    trusted_handle = QUALIFIER._open_or_create_secure_root(
        trusted_root,
        "test trusted root",
    )
    preimage = QUALIFIER._materialize_tree_preimage_v2(
        trusted_handle,
        kind="capsule",
        descriptor=descriptor,
        contents=measured,
        manifest_name="capsule.json",
        label="runtime capsule",
    )
    QUALIFIER._seal_preimage_namespace_v2(trusted_handle)
    trusted_handle.close()

    capsule.chmod(0o755)
    runner.chmod(0o644)
    runner.write_text(
        "process.stdout.write(JSON.stringify({fixture:'swapped',writeDenied:false}));",
        encoding="utf-8",
    )
    runner.chmod(0o444)
    capsule.chmod(0o555)
    observed: dict[str, object] = {}

    def accept(**kwargs: object) -> dict:
        observed.update(kwargs)
        return {"verified": True}

    monkeypatch.setattr(QUALIFIER, "_capsule_envelope_from_result_v2", accept)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    try:
        result = QUALIFIER._run_capsule_node_v2(
            execution=execution,
            capsule=preimage,
            process_root=process_handle,
            run_nonce="7" * 64,
            timeout_seconds=5.0,
            authority=authority,
        )
    finally:
        process_handle.close()

    capsule.chmod(0o755)
    runner.chmod(0o644)
    runner.write_text(original, encoding="utf-8")
    runner.chmod(0o444)
    capsule.chmod(0o555)
    QUALIFIER._verify_external_tree(
        capsule,
        descriptor,
        manifest_name="capsule.json",
        label="runtime capsule",
    )
    _, after = QUALIFIER._verify_external_tree(
        preimage,
        descriptor,
        manifest_name="capsule.json",
        label="runtime capsule",
    )

    assert result == {"verified": True}
    assert observed["result"] == {"fixture": "original", "writeDenied": True}
    assert after == measured


def _execute_node_supervisor_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    pid_path = tmp_path / "fake-node-process" / f"{kind}.pid"
    prefix = (
        "import fs from 'node:fs';"
        f"fs.writeFileSync({json.dumps(str(pid_path))},String(process.pid));"
    )
    if kind == "timeout":
        source = prefix + "setInterval(()=>{},1000);"
        message = "timeout cap"
    elif kind == "stdout-cap":
        monkeypatch.setattr(QUALIFIER, "MAX_WORKER_STDOUT_BYTES", 1024)
        source = prefix + "fs.writeSync(1,Buffer.alloc(4096));setInterval(()=>{},1000);"
        message = "stdout exceeded"
    else:
        monkeypatch.setattr(QUALIFIER, "MAX_WORKER_STDERR_BYTES", 1024)
        source = prefix + "fs.writeSync(2,Buffer.alloc(4096));setInterval(()=>{},1000);"
        message = "stderr exceeded"
    capsule, process_root, authority, execution, _ = _fake_capsule_node_authority(tmp_path, source)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "test process root",
    )
    try:
        with pytest.raises(QUALIFIER.QualificationBlocked, match=message):
            QUALIFIER._run_capsule_node_v2(
                execution=execution,
                capsule=capsule,
                process_root=process_handle,
                run_nonce="7" * 64,
                timeout_seconds=10.0,
                authority=authority,
            )
    finally:
        process_handle.close()
    assert pid_path.exists()
    _assert_pid_absent(int(pid_path.read_text()))


def test_capsule_node_keyboard_interrupt_unconditionally_reaps_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_path = tmp_path / "fake-node-process" / "interrupt.pid"
    source = (
        "import fs from 'node:fs';"
        f"fs.writeFileSync({json.dumps(str(pid_path))},String(process.pid));"
        "fs.writeSync(1,Buffer.alloc(4096));setInterval(()=>{},1000);"
    )
    capsule, process_root, authority, execution, _ = _fake_capsule_node_authority(tmp_path, source)
    process_handle = QUALIFIER._open_or_create_secure_root(
        process_root,
        "interrupt process root",
    )
    original_fstat = QUALIFIER.os.fstat
    interrupted = False

    def interrupt_after_node_start(descriptor: int) -> os.stat_result:
        nonlocal interrupted
        observed = original_fstat(descriptor)
        if not interrupted and pid_path.exists() and stat.S_ISREG(observed.st_mode):
            interrupted = True
            raise KeyboardInterrupt
        return observed

    monkeypatch.setattr(QUALIFIER.os, "fstat", interrupt_after_node_start)
    try:
        with pytest.raises(KeyboardInterrupt):
            QUALIFIER._run_capsule_node_v2(
                execution=execution,
                capsule=capsule,
                process_root=process_handle,
                run_nonce="7" * 64,
                timeout_seconds=10.0,
                authority=authority,
            )
    finally:
        process_handle.close()
    assert interrupted is True
    assert pid_path.exists()
    pid = int(pid_path.read_text())
    _assert_pid_absent(pid)
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def _interrupting_sleep_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> list[subprocess.Popen[bytes]]:
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []

    def spawn_sleep(*_args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(
            ["/bin/sleep", "30"],
            stdin=subprocess.PIPE,
            stdout=kwargs.get("stdout", subprocess.DEVNULL),
            stderr=kwargs.get("stderr", subprocess.DEVNULL),
            start_new_session=True,
        )

        def interrupt(*_args: object, **_kwargs: object) -> tuple[bytes, bytes]:
            raise KeyboardInterrupt

        process.communicate = interrupt  # type: ignore[method-assign]
        spawned.append(process)
        return process

    monkeypatch.setattr(QUALIFIER.subprocess, "Popen", spawn_sleep)
    return spawned


def _assert_test_processes_reaped(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        assert process.poll() is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)


def _force_reap_test_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, 9)
        with contextlib.suppress(ProcessLookupError, subprocess.TimeoutExpired):
            process.wait(timeout=2)


def test_fixture_worker_keyboard_interrupt_unconditionally_reaps_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "fixture-worker-bundle"
    bundle.mkdir()
    (bundle / "worker.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    artifact = QUALIFIER._open_or_create_secure_root(
        tmp_path / "fixture-worker-artifact", "fixture worker artifact root"
    )
    registry = QUALIFIER._RetainedRootRegistry()
    spawned = _interrupting_sleep_factory(monkeypatch)
    monkeypatch.setattr(
        QUALIFIER,
        "_launcher_identity",
        lambda: {
            "sandbox_exec_path": "/usr/bin/sandbox-exec",
            "python_executable": str(Path(sys.executable).resolve(strict=True)),
        },
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            QUALIFIER._run_worker(
                bundle,
                "worker.py",
                bundle,
                artifact,
                b"{}",
                5.0,
                registry,
            )
        assert len(spawned) == 1
        _assert_test_processes_reaped(spawned)
    finally:
        _force_reap_test_processes(spawned)
        registry.close()
        artifact.close()


def test_production_worker_keyboard_interrupt_unconditionally_reaps_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "production-worker-source"
    dependency = tmp_path / "production-worker-dependency"
    source.mkdir()
    dependency.mkdir()
    (source / "worker.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    authority = tmp_path / "production-worker-authority.json"
    authority.write_text("{}", encoding="utf-8")
    artifact = QUALIFIER._open_or_create_secure_root(
        tmp_path / "production-worker-artifact", "production worker artifact root"
    )
    process_root = QUALIFIER._create_random_directory(
        artifact,
        ".w3-production-",
        "production worker process root",
    )
    output = QUALIFIER._open_child_directory(
        process_root,
        "output",
        "production worker output root",
        mode=0o700,
        create=True,
    )
    output.close()
    spawned = _interrupting_sleep_factory(monkeypatch)
    monkeypatch.setattr(
        QUALIFIER,
        "_launcher_identity_v2",
        lambda: {
            "sandbox_exec_path": "/usr/bin/sandbox-exec",
            "python_executable": str(Path(sys.executable).resolve(strict=True)),
        },
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            QUALIFIER._run_worker_v2(
                source_bundle=source,
                dependency_bundle=dependency,
                worker_relative="worker.py",
                authority_path=authority,
                artifact_root=artifact,
                process_root=process_root,
                request_bytes=b"{}",
                timeout_seconds=5.0,
            )
        assert len(spawned) == 1
        _assert_test_processes_reaped(spawned)
    finally:
        _force_reap_test_processes(spawned)
        process_root.close()
        artifact.close()


def _execute_node_policy_denial(tmp_path: Path, case: str) -> None:
    capsule, node, process_root = _tmp_node_capsule(tmp_path)
    if case == "exec-node-drift":
        command = _node_policy_command(capsule, node, process_root, "process.exit(0)")
        node_index = command.index(f"NODE_EXECUTABLE={node}")
        command[node_index] = "NODE_EXECUTABLE=/usr/bin/true"
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
            timeout=10,
        )
        assert completed.returncode != 0
        return
    if case in {"network-connect", "network-bind"}:
        operation = (
            "const socket=require('net').createConnection({host:'127.0.0.1',port:9});"
            if case == "network-connect"
            else "const socket=require('net').createServer();socket.listen(0,'127.0.0.1');"
        )
        script = (
            operation
            + "socket.on('error',(error)=>{if(error.code==='EPERM'||error.code==='EACCES')"
            "{process.exit(0)}process.exit(91)});"
            "setTimeout(()=>process.exit(92),1000);"
        )
    else:
        if case == "read-external":
            operation = "require('fs').readFileSync('/etc/hosts')"
        elif case == "read-source-checkout":
            operation = f"require('fs').readFileSync({json.dumps(str(QUALIFIER_PATH))})"
        elif case == "write-external":
            operation = f"require('fs').writeFileSync({json.dumps(str(tmp_path / 'outside'))},'x')"
        else:
            operation = f"require('fs').writeFileSync({json.dumps(str(capsule / 'source'))},'x')"
        script = (
            f"try{{{operation};process.exit(92)}}catch(error){{"
            "if(error.code==='EPERM'||error.code==='EACCES'){process.exit(0)}process.exit(91)}"
        )
    completed = subprocess.run(
        _node_policy_command(capsule, node, process_root, script),
        capture_output=True,
        check=False,
        env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == completed.stderr == b""


def _matrix_bridge_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict, dict[str, bytes]]:
    qualifier = tmp_path / "matrix-qualifier.py"
    qualifier.write_text("# matrix fixture\n")
    qualifier_sha256 = BRIDGE.bytes_hash(qualifier.read_bytes())
    monkeypatch.setattr(BRIDGE, "PINNED_QUALIFIER_SHA256", qualifier_sha256)
    launcher = BRIDGE._measured_launcher(
        qualifier.resolve(), qualifier_sha256, Path(sys.executable).resolve()
    )
    authority = BRIDGE_FIXTURES._authority(launcher)
    authority_path = tmp_path / "matrix-authority.json"
    authority_path.write_bytes(BRIDGE.canonical_json_bytes(authority))
    roots = {}
    for name in ("source", "dependency", "capsule"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    qualification, artifacts = BRIDGE_FIXTURES._qualification(authority)
    arguments = {
        "qualifier_path": qualifier,
        "qualifier_sha256": qualifier_sha256,
        "authority_path": authority_path,
        "authority_sha256": authority["manifest_sha256"],
        "source_bundle_root": roots["source"],
        "dependency_bundle_root": roots["dependency"],
        "capsule_root": roots["capsule"],
        "artifact_root": tmp_path / "bridge-artifacts",
    }
    return arguments, qualification, artifacts


def _execute_replay_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    arguments, qualification, artifacts = _matrix_bridge_state(tmp_path, monkeypatch)
    if case == "fixture-v1-downgrade":
        authority = BRIDGE._load_authority(
            Path(arguments["authority_path"]),
            str(arguments["authority_sha256"]),
            qualification["launcher"],
        )
        qualification["qualification_kind"] = "fixture-v1"
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE._validate_qualification(qualification, authority, authority["manifest_sha256"])
        return
    if case == "v1-regression":
        v1_root = tmp_path / "v1"
        v1_root.mkdir()
        report = _qualify(_fixture(v1_root))
        assert report["status"] == "qualified"
        assert report["schema_version"] == 1
        return
    calls = 0

    def fake_once(**kwargs: object):
        nonlocal calls
        calls += 1
        result = BRIDGE_FIXTURES._physicalize_qualification(qualification, calls)
        rendered = BRIDGE.canonical_json_bytes(result) + b"\n"
        run_artifacts = deepcopy(artifacts)
        if calls == 2 and case != "replay-nonce-scope":
            if case == "replay-report":
                rendered += b" "
            elif case == "replay-artifact":
                run_artifacts[next(iter(run_artifacts))] += b" "
            elif case == "replay-role":
                result["roles"]["author"] = 0
                rendered = BRIDGE.canonical_json_bytes(result) + b"\n"
            elif case == "replay-count":
                result["counts"]["executions"] = 4
                rendered = BRIDGE.canonical_json_bytes(result) + b"\n"
            else:
                result["manifest_sha256"] = "sha256:" + "0" * 64
                rendered = BRIDGE.canonical_json_bytes(result) + b"\n"
        return rendered, result, run_artifacts

    monkeypatch.setattr(BRIDGE, "_run_once", fake_once)
    if case == "replay-nonce-scope":
        report = BRIDGE.run_replay_gate(**arguments)
        assert report["status"] == "replay-qualified"
        assert calls == 2
    else:
        with pytest.raises(BRIDGE.BridgeGateBlocked):
            BRIDGE.run_replay_gate(**arguments)


def _execute_mutation_case(
    group: str,
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if group == "A-authority-kimi":
        test_authority_and_kimi_mutations_fail_closed(tmp_path, monkeypatch, case)
        return
    if group == "B-dependency-closure":
        suffix = case.removeprefix("dependency-")
        if suffix in {"missing", "extra", "symlink", "mode"}:
            test_external_dependency_tree_attacks_fail_closed(tmp_path, monkeypatch, suffix)
        else:
            test_dependency_descriptor_mutations_fail_closed(suffix)
        return
    if group == "C-capsule":
        suffix = case.removeprefix("capsule-")
        if suffix in {"missing", "extra", "symlink"}:
            _execute_capsule_tree_attack(tmp_path, monkeypatch, suffix)
        else:
            test_capsule_descriptor_mutations_fail_closed(suffix, monkeypatch)
        return
    if group == "D-process-policy":
        if case == "exec-unregistered":
            test_v2_live_node_cannot_spawn_unregistered_or_detached_registered_child(
                tmp_path, False
            )
        elif case == "registered-node-direct-supervised-no-fork":
            test_v2_live_registered_node_is_exact_supervised_session_leader(tmp_path)
        elif case in {"timeout", "stdout-cap", "stderr-cap"}:
            _execute_node_supervisor_failure(tmp_path, monkeypatch, case)
        else:
            _execute_node_policy_denial(tmp_path, case)
        return
    if group == "E-request-envelope-artifact":
        if case.startswith("request-"):
            _execute_worker_request_mutation(case)
        elif case.startswith("envelope-"):
            _execute_envelope_mutation(case, monkeypatch)
        else:
            _execute_artifact_mutation(case)
        return
    _execute_replay_case(tmp_path, monkeypatch, case)


V2_EXECUTABLE_MUTATIONS = tuple(
    (group, case) for group, cases in V2_MUTATION_MATRIX.items() for case in cases
)


@pytest.mark.parametrize(("group", "case"), V2_EXECUTABLE_MUTATIONS)
def test_v2_executable_mutation_matrix_case(
    group: str,
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _execute_mutation_case(group, case, tmp_path, monkeypatch)
