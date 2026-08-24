from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.oracles as oracles
from metis_model1.f6_structural import (
    F6CandidateError,
    F6ResultError,
    F6TruthError,
    evaluate_f6_structural_explanation,
    seal_f6_truth,
    validate_f6_auto_result,
    validate_f6_truth,
)

ROOT = Path(__file__).parents[1]


def _sha(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _git_blob_oid(source: str) -> str:
    content = source.encode()
    return hashlib.sha1(
        f"blob {len(content)}\0".encode() + content,
        usedforsecurity=False,
    ).hexdigest()


def _claim(
    claim_id: str = "endpoint.name",
    value: object = "home",
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "basis": "ast_ir",
        "ast_path": "/elements/0/name",
        "ir_path": "/name",
        "value": value,
    }


def _truth() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "truth_id": "f6-truth/f6-example-001",
        "task_id": "f6-example-001",
        "family": "F-6",
        "status": "sealed_pre_output",
        "source": {
            "toolchain_revision": "a" * 40,
            "toolchain_tree": "b" * 40,
            "source_blob_oid": "c" * 40,
            "source_sha256": "sha256:" + "3" * 64,
            "source_path": "examples/synthetic/home.metis",
            "oracle_request_sha256": "sha256:" + "4" * 64,
            "oracle_envelope_sha256": "sha256:" + "d" * 64,
        },
        "oracle_evidence": {
            "endpoint_name": "home",
            "ast_signature": "sha256:" + "e" * 64,
            "ir_signature": "sha256:" + "f" * 64,
            "ast_inventory_sha256": "sha256:" + "1" * 64,
            "ir_value_sha256": "sha256:" + "2" * 64,
        },
        "required_claims": [_claim()],
        "human_review_required": True,
        "model_outputs_observed": False,
    }
    return {**body, "truth_sha256": _sha(body)}


def _candidate() -> dict[str, object]:
    truth = _truth()
    oracle = truth["oracle_evidence"]
    return {
        "schema_version": 1,
        "task_id": truth["task_id"],
        "ast_signature": oracle["ast_signature"],
        "ir_signature": oracle["ir_signature"],
        "claims": [_claim()],
        "summary": "The endpoint name is grounded in both normalized AST and IR.",
    }


def test_automatic_f6_pass_is_schema_valid_but_never_receives_human_credit() -> None:
    truth = validate_f6_truth(_truth())
    result = evaluate_f6_structural_explanation(truth, _candidate())
    truth_schema = json.loads((ROOT / "schemas/f6-structural-truth.schema.json").read_text())
    result_schema = json.loads((ROOT / "schemas/f6-structural-auto-result.schema.json").read_text())

    assert list(Draft202012Validator(truth_schema).iter_errors(truth)) == []
    assert list(Draft202012Validator(result_schema).iter_errors(result)) == []
    assert result["status"] == "automatic_pass_human_pending"
    assert result["outcomes"] == {
        "ast": "pass",
        "ir": "pass",
        "semantic": "pass",
        "human": "not_run",
    }
    assert result["eligible_for_f6_credit"] is False


@pytest.mark.parametrize(
    ("mutation", "reason", "failed_oracle"),
    [
        (
            lambda candidate: candidate.update({"ast_signature": "sha256:" + "0" * 64}),
            "ast_signature_mismatch",
            "ast",
        ),
        (
            lambda candidate: candidate.update({"ir_signature": "sha256:" + "0" * 64}),
            "ir_signature_mismatch",
            "ir",
        ),
        (
            lambda candidate: candidate["claims"][0].update({"value": "invented"}),
            "claim_mismatch:endpoint.name",
            "semantic",
        ),
        (
            lambda candidate: candidate.update({"claims": [_claim("endpoint.other")]}),
            "claim_roster_mismatch",
            "semantic",
        ),
    ],
)
def test_automatic_f6_rejects_signature_and_claim_drift(
    mutation, reason: str, failed_oracle: str
) -> None:
    candidate = _candidate()
    mutation(candidate)

    result = evaluate_f6_structural_explanation(_truth(), candidate)

    assert result["status"] == "automatic_fail"
    assert reason in result["failure_reasons"]
    assert result["outcomes"][failed_oracle] == "fail"
    assert result["eligible_for_f6_credit"] is False


def test_truth_hash_and_pre_output_state_are_fail_closed() -> None:
    truth = _truth()
    truth["required_claims"][0]["value"] = "tampered"
    with pytest.raises(F6TruthError, match="truth hash"):
        validate_f6_truth(truth)

    truth = _truth()
    body = {key: value for key, value in truth.items() if key != "truth_sha256"}
    body["model_outputs_observed"] = True
    truth = {**body, "truth_sha256": _sha(body)}
    with pytest.raises(F6TruthError, match="sealed pre-output"):
        validate_f6_truth(truth)


def test_candidate_wire_rejects_unknown_fields_and_duplicate_claims() -> None:
    candidate = _candidate()
    candidate["unknown"] = True
    with pytest.raises(F6CandidateError, match="exactly"):
        evaluate_f6_structural_explanation(_truth(), candidate)


def test_automatic_result_hash_outcomes_and_input_bindings_fail_closed() -> None:
    truth = _truth()
    candidate = _candidate()
    result = evaluate_f6_structural_explanation(truth, candidate)
    assert validate_f6_auto_result(result, truth=truth, candidate=candidate) == result

    tampered = deepcopy(result)
    tampered["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(F6ResultError, match="result hash"):
        validate_f6_auto_result(tampered)

    incoherent = deepcopy(result)
    incoherent["outcomes"]["ast"] = "fail"
    body = {key: value for key, value in incoherent.items() if key != "result_sha256"}
    incoherent["result_sha256"] = _sha(body)
    with pytest.raises(F6ResultError, match="outcomes disagree"):
        validate_f6_auto_result(incoherent)

    other_candidate = _candidate()
    other_candidate["summary"] = "Different normalized candidate bytes."
    with pytest.raises(F6ResultError, match="differs from candidate"):
        validate_f6_auto_result(result, truth=truth, candidate=other_candidate)

    candidate = _candidate()
    candidate["claims"].append(deepcopy(candidate["claims"][0]))
    with pytest.raises(F6CandidateError, match="duplicate claim"):
        evaluate_f6_structural_explanation(_truth(), candidate)


def test_seal_f6_truth_uses_verified_endpoint_mode_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        'metis 0.43\nendpoint public.synthetic_home as "home" {\n  variant baseline { empty }\n}\n'
    )
    request = oracles.build_oracle_request(
        source,
        filename="examples/synthetic/home.metis",
        endpoint="public.synthetic_home",
    )
    envelope = {
        "result": {
            "status": "ok",
            "failure": None,
            "endpoint": {"name": "public.synthetic_home", "count": 1},
            "ast": {
                "inventory": {"elements": [{"name": "home"}]},
                "signature": "sha256:" + "1" * 64,
            },
            "ir": {"value": {"name": "home"}, "signature": "sha256:" + "2" * 64},
            "toolchain": {
                "revision": request["metis_revision"],
                "tree": request["metis_tree"],
                "language_version": "0.43",
            },
        },
        "evidence": {
            "envelope_sha256": "sha256:" + "3" * 64,
            "input_sha256": _sha(request),
            "ast_sha256": "sha256:" + "1" * 64,
            "ir_sha256": "sha256:" + "2" * 64,
        },
    }
    observed: dict[str, object] = {}

    def verify(value, *, request=None):
        observed["request"] = request
        return value

    monkeypatch.setattr(oracles, "verify_oracle_envelope", verify)

    truth = seal_f6_truth(
        task_id="f6-example-001",
        source_path="examples/synthetic/home.metis",
        source_blob_oid=_git_blob_oid(source),
        oracle_request=request,
        oracle_envelope=envelope,
        required_claims=[_claim()],
    )

    assert truth["source"]["toolchain_revision"] == request["metis_revision"]
    assert (
        truth["source"]["source_sha256"] == "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    )
    assert truth["oracle_evidence"]["endpoint_name"] == "public.synthetic_home"
    assert observed["request"] == request
    assert validate_f6_truth(truth) == truth


@pytest.mark.parametrize(
    ("source_path", "source_blob_oid", "message"),
    [
        ("examples/synthetic/other.metis", None, "source path differs"),
        (None, "0" * 40, "source blob id differs"),
    ],
)
def test_seal_f6_truth_rejects_unbound_source_identity(
    monkeypatch: pytest.MonkeyPatch,
    source_path: str | None,
    source_blob_oid: str | None,
    message: str,
) -> None:
    source = (
        'metis 0.43\nendpoint public.synthetic_home as "home" {\n  variant baseline { empty }\n}\n'
    )
    request = oracles.build_oracle_request(
        source,
        filename="examples/synthetic/home.metis",
        endpoint="public.synthetic_home",
    )
    monkeypatch.setattr(
        oracles,
        "verify_oracle_envelope",
        lambda value, *, request=None: pytest.fail("unbound input reached the Oracle verifier"),
    )

    with pytest.raises(F6TruthError, match=message):
        seal_f6_truth(
            task_id="f6-example-001",
            source_path=source_path or request["filename"],
            source_blob_oid=source_blob_oid or _git_blob_oid(source),
            oracle_request=request,
            oracle_envelope={},
            required_claims=[_claim()],
        )


def test_seal_f6_truth_rejects_source_mode_without_ir(monkeypatch: pytest.MonkeyPatch) -> None:
    source = (
        'metis 0.43\nendpoint public.synthetic_home as "home" {\n  variant baseline { empty }\n}\n'
    )
    request = oracles.build_oracle_request(
        source,
        filename="examples/synthetic/home.metis",
        endpoint="public.synthetic_home",
    )
    envelope = {
        "result": {
            "status": "ok",
            "failure": None,
            "endpoint": {"name": "public.synthetic_home", "count": 1},
            "ast": {"inventory": {}, "signature": "sha256:" + "1" * 64},
            "ir": {"value": None, "signature": None},
            "toolchain": {
                "revision": request["metis_revision"],
                "tree": request["metis_tree"],
            },
        },
        "evidence": {
            "envelope_sha256": "sha256:" + "3" * 64,
            "input_sha256": _sha(request),
            "ast_sha256": "sha256:" + "1" * 64,
            "ir_sha256": None,
        },
    }
    monkeypatch.setattr(
        oracles,
        "verify_oracle_envelope",
        lambda value, *, request=None: value,
    )

    with pytest.raises(F6TruthError, match="endpoint-mode AST/IR"):
        seal_f6_truth(
            task_id="f6-example-001",
            source_path="examples/synthetic/home.metis",
            source_blob_oid=_git_blob_oid(source),
            oracle_request=request,
            oracle_envelope=envelope,
            required_claims=[_claim()],
        )


def test_seal_f6_truth_rejects_claim_path_or_value_not_grounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        'metis 0.43\nendpoint public.synthetic_home as "home" {\n  variant baseline { empty }\n}\n'
    )
    request = oracles.build_oracle_request(
        source,
        filename="examples/synthetic/home.metis",
        endpoint="public.synthetic_home",
    )
    blob_oid = _git_blob_oid(source)
    envelope = {
        "result": {
            "status": "ok",
            "failure": None,
            "endpoint": {"name": "public.synthetic_home", "count": 1},
            "ast": {
                "inventory": {"elements": [{"name": "home"}]},
                "signature": "sha256:" + "1" * 64,
            },
            "ir": {"value": {"name": "home"}, "signature": "sha256:" + "2" * 64},
            "toolchain": {
                "revision": request["metis_revision"],
                "tree": request["metis_tree"],
            },
        },
        "evidence": {
            "envelope_sha256": "sha256:" + "3" * 64,
            "input_sha256": _sha(request),
            "ast_sha256": "sha256:" + "1" * 64,
            "ir_sha256": "sha256:" + "2" * 64,
        },
    }
    monkeypatch.setattr(
        oracles,
        "verify_oracle_envelope",
        lambda value, *, request=None: value,
    )

    with pytest.raises(F6TruthError, match="disagrees with the AST"):
        seal_f6_truth(
            task_id="f6-example-001",
            source_path="examples/synthetic/home.metis",
            source_blob_oid=blob_oid,
            oracle_request=request,
            oracle_envelope=envelope,
            required_claims=[_claim(value="invented")],
        )

    broken_path = _claim()
    broken_path["ast_path"] = "/elements/1/name"
    with pytest.raises(F6TruthError, match="outside"):
        seal_f6_truth(
            task_id="f6-example-001",
            source_path="examples/synthetic/home.metis",
            source_blob_oid=blob_oid,
            oracle_request=request,
            oracle_envelope=envelope,
            required_claims=[broken_path],
        )
