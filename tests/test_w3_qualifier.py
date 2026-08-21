from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
QUALIFIER_PATH = PROJECT_ROOT / "runtime/w3_qualifier.py"
QUALIFICATION_SCHEMA = PROJECT_ROOT / "schemas/w3-qualification.schema.json"

SPEC = importlib.util.spec_from_file_location("w3_qualifier_under_test", QUALIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
QUALIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALIFIER
SPEC.loader.exec_module(QUALIFIER)


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
    artifact.mkdir()
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


def test_two_fresh_launchers_are_byte_identical_and_schema_valid(tmp_path: Path) -> None:
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
    assert outputs[0] == outputs[1]
    assert outputs[0].endswith(b"\n")
    report = json.loads(outputs[0])
    schema = json.loads(QUALIFICATION_SCHEMA.read_text())
    assert list(Draft202012Validator(schema).iter_errors(report)) == []
    assert report["manifest_sha256"] == _manifest_hash(report)


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
