from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from metis_model1.oracles import CAPSULE_EXECUTION_POLICY

PROJECT_ROOT = Path(__file__).parents[1]
WORKER_PATH = PROJECT_ROOT / "runtime/w3_production_worker.py"
SPEC = importlib.util.spec_from_file_location("w3_production_worker_under_test", WORKER_PATH)
assert SPEC and SPEC.loader
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def _request() -> dict:
    roles = (
        ("candidate-f1", "F-1", "author", "ok"),
        ("candidate-f2", "F-2", "before", "ok"),
        ("candidate-f2", "F-2", "after", "ok"),
        ("candidate-f3", "F-3", "mutated", "invalid"),
        ("candidate-f3", "F-3", "fixed", "ok"),
    )
    return {
        "schema_version": 3,
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
                "capsule_envelope": {
                    "schema_version": 3,
                    "protocol": "metis-runtime-capsule-v3",
                    "execution_id": f"{candidate}.{role}",
                    "run_nonce": "7" * 64,
                    "request_sha256": "sha256:" + "8" * 64,
                    "capsule_manifest_sha256": "sha256:" + "4" * 64,
                    "execution_policy": dict(CAPSULE_EXECUTION_POLICY),
                    "oracle_envelope": {"result": {"status": status}},
                    "manifest_sha256": "sha256:" + "9" * 64,
                },
            }
            for candidate, family, role, status in roles
        ],
    }


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    process = tmp_path / "process"
    output = process / "output"
    output.mkdir(parents=True)
    monkeypatch.setenv("W3_PRODUCTION_PROCESS_ROOT", str(process))
    monkeypatch.setenv("W3_PRODUCTION_OUTPUT_ROOT", str(output))
    return {"process": process, "output": output}


def test_worker_executes_exact_three_candidate_five_role_roster(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(WORKER, "verify_capsule_oracle_envelope", lambda *args, **kwargs: args[0])
    monkeypatch.setattr(
        WORKER,
        "normalize_capsule_oracle_envelope",
        lambda value: {key: item for key, item in value.items() if key != "run_nonce"},
    )
    result = WORKER.execute(_request())

    assert result["status"] == "completed"
    assert result["counts"] == {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0}
    assert result["roles"] == WORKER.ROLE_COUNTS
    assert len(result["executions"]) == 5
    assert {row["role"] for row in result["executions"]} == set(WORKER.ROLE_COUNTS)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version=True), "schema version"),
        (lambda value: value.update(protocol="fixture-v1"), "protocol"),
        (lambda value: value.update(run_nonce="short"), "nonce"),
        (lambda value: value["expected"].update(executions=4), "execution count"),
        (lambda value: value["executions"].pop(), "exactly five"),
        (lambda value: value["executions"][0].update(role="before"), "identity"),
        (lambda value: value["executions"][0].update(family="F-3"), "identity"),
        (lambda value: value["executions"][0].update(candidate_id="../x"), "identity"),
    ],
)
def test_worker_request_mutations_fail_closed(mutation, message: str) -> None:
    request = _request()
    mutation(request)
    with pytest.raises(WORKER.ProductionWorkerError, match=message):
        WORKER._validated_request(request)


def test_worker_rejects_boolean_expected_role_count() -> None:
    request = _request()
    request["expected"]["roles"]["author"] = True

    with pytest.raises(WORKER.ProductionWorkerError, match="exact integer 1"):
        WORKER._validated_request(request)


def test_worker_rejects_role_status_relabel_even_with_matching_envelope() -> None:
    request = _request()
    mutated = next(row for row in request["executions"] if row["role"] == "mutated")
    mutated["expected_status"] = "ok"
    mutated["capsule_envelope"]["oracle_envelope"]["result"]["status"] = "ok"

    with pytest.raises(WORKER.ProductionWorkerError, match="registered role"):
        WORKER._validated_request(request)


def test_worker_rejects_output_root_outside_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = tmp_path / "process"
    output = tmp_path / "outside"
    for root in (process, output):
        root.mkdir()
    monkeypatch.setenv("W3_PRODUCTION_PROCESS_ROOT", str(process))
    monkeypatch.setenv("W3_PRODUCTION_OUTPUT_ROOT", str(output))

    with pytest.raises(WORKER.ProductionWorkerTrustError, match="below process root"):
        WORKER.execute(_request())


@pytest.mark.parametrize("name", ["W3_PRODUCTION_PROCESS_ROOT", "W3_PRODUCTION_OUTPUT_ROOT"])
def test_worker_rejects_symlink_in_registered_root_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    real = tmp_path / "real"
    process = real / "process"
    output = process / "output"
    output.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("W3_PRODUCTION_PROCESS_ROOT", str(process))
    monkeypatch.setenv("W3_PRODUCTION_OUTPUT_ROOT", str(output))
    selected = alias / ("process" if name.endswith("PROCESS_ROOT") else "process/output")
    monkeypatch.setenv(name, str(selected))

    with pytest.raises(WORKER.ProductionWorkerTrustError, match="ancestry contains a symlink"):
        WORKER._safe_root(name)


def test_worker_maps_capsule_failure_to_typed_execution_error(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: object, **kwargs: object) -> dict:
        raise WORKER.OracleError("blocked")

    monkeypatch.setattr(WORKER, "verify_capsule_oracle_envelope", blocked)
    with pytest.raises(WORKER.ProductionWorkerTrustError, match="capsule evidence"):
        WORKER.execute(_request())


def test_worker_cli_blocked_envelope_is_canonical(tmp_path: Path, monkeypatch) -> None:
    rendered = WORKER._blocked(WORKER.ProductionWorkerTrustError("denied"))
    assert json.loads(WORKER._canonical(rendered)) == rendered
    assert rendered["failure"] == {"kind": "worker-trust", "message": "denied"}
