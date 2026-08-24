from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jsonschema import Draft202012Validator

from metis_model1.f6_human_review import (
    F6HumanReviewError,
    create_f6_blind_review_request,
    finalize_f6_human_review,
    seal_f6_human_review_policy,
    sign_f6_human_review_receipt,
    validate_f6_human_review_final,
)


def _sha(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
    )


def _key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


@pytest.fixture
def review_material() -> dict[str, object]:
    reviewer_key = Ed25519PrivateKey.generate()  # ephemeral test key; never serialized
    policy = seal_f6_human_review_policy(
        truth_author_id="truth-author",
        model_operator_id="model-operator",
        rubric_sha256="sha256:" + "a" * 64,
        reviewers=[{"reviewer_id": "blind-reviewer", "public_key": _key_hex(reviewer_key)}],
    )
    source_text = (
        'metis 0.43\nendpoint public.synthetic_review as "review" {\n'
        "  variant baseline { empty }\n}\n"
    )
    ast_inventory = {"elements": [{"name": "public.synthetic_review"}]}
    ir_value = {"name": "public.synthetic_review", "variants": [{"name": "baseline"}]}
    claim = {
        "claim_id": "endpoint.name",
        "basis": "ast_ir",
        "ast_path": "/elements/0/name",
        "ir_path": "/name",
        "value": "public.synthetic_review",
    }
    candidate = {
        "schema_version": 1,
        "task_id": "f6-case-001",
        "ast_signature": "sha256:" + "d" * 64,
        "ir_signature": "sha256:" + "e" * 64,
        "claims": [claim],
        "summary": "The endpoint name is grounded in both AST and IR.",
    }
    truth_body = {
        "schema_version": 1,
        "truth_id": "f6-truth/f6-case-001",
        "task_id": "f6-case-001",
        "family": "F-6",
        "status": "sealed_pre_output",
        "source": {
            "toolchain_revision": "a" * 40,
            "toolchain_tree": "b" * 40,
            "source_blob_oid": "c" * 40,
            "source_sha256": "sha256:" + hashlib.sha256(source_text.encode()).hexdigest(),
            "source_path": "synthetic/review.metis",
            "oracle_request_sha256": "sha256:" + "1" * 64,
            "oracle_envelope_sha256": "sha256:" + "2" * 64,
        },
        "oracle_evidence": {
            "endpoint_name": "public.synthetic_review",
            "ast_signature": candidate["ast_signature"],
            "ir_signature": candidate["ir_signature"],
            "ast_inventory_sha256": _sha(ast_inventory),
            "ir_value_sha256": _sha(ir_value),
        },
        "required_claims": [claim],
        "human_review_required": True,
        "model_outputs_observed": False,
    }
    truth = {**truth_body, "truth_sha256": _sha(truth_body)}
    package = {
        "source": {"path": "synthetic/review.metis", "text": source_text},
        "ast_inventory": ast_inventory,
        "ir_value": ir_value,
        "candidate_response": candidate,
    }
    request = create_f6_blind_review_request(
        policy=policy,
        task_id="f6-case-001",
        nonce="1" * 64,
        candidate=candidate,
        blind_package=package,
    )
    auto_body = {
        "schema_version": 1,
        "task_id": "f6-case-001",
        "status": "automatic_pass_human_pending",
        "eligible_for_f6_credit": False,
        "outcomes": {"ast": "pass", "ir": "pass", "semantic": "pass", "human": "not_run"},
        "failure_reasons": [],
        "evidence": {
            "truth_sha256": truth["truth_sha256"],
            "candidate_sha256": request["candidate_sha256"],
            "oracle_envelope_sha256": truth["source"]["oracle_envelope_sha256"],
        },
    }
    return {
        "policy": policy,
        "request": request,
        "automatic_result": {**auto_body, "result_sha256": _sha(auto_body)},
        "truth": truth,
        "candidate": candidate,
        "key": reviewer_key,
    }


def _receipt(material: dict[str, object], verdict: str = "pass") -> dict[str, object]:
    return sign_f6_human_review_receipt(
        policy=material["policy"],
        request=material["request"],
        reviewer_id="blind-reviewer",
        private_key=material["key"],
        verdict=verdict,
        reason_codes=[] if verdict == "pass" else ["insufficient-evidence"],
        issued_at="2026-08-24T12:00:00Z",
    )


def _schema_errors(name: str, value: object) -> list[object]:
    path = Path("schemas") / name
    return list(Draft202012Validator(json.loads(path.read_text())).iter_errors(value))


def test_signed_blind_pass_still_cannot_grant_credit_without_protected_authority(
    review_material: dict[str, object],
) -> None:
    receipt = _receipt(review_material)
    with pytest.raises(F6HumanReviewError, match="protected F-6 review authority"):
        finalize_f6_human_review(
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=review_material["automatic_result"],
            request=review_material["request"],
            receipt=receipt,
        )
    assert not _schema_errors("f6-human-review-policy.schema.json", review_material["policy"])
    assert not _schema_errors("f6-blind-review-request.schema.json", review_material["request"])
    assert not _schema_errors("f6-human-review-receipt.schema.json", receipt)


@pytest.mark.parametrize("verdict", ["fail", "abstain"])
def test_non_pass_receipt_is_signed_evidence_but_never_grants_credit(
    review_material: dict[str, object], verdict: str
) -> None:
    final = finalize_f6_human_review(
        policy=review_material["policy"],
        truth=review_material["truth"],
        candidate=review_material["candidate"],
        automatic_result=review_material["automatic_result"],
        request=review_material["request"],
        receipt=_receipt(review_material, verdict),
    )
    assert final["eligible_for_f6_credit"] is False
    assert final["status"] == "f6_credit_denied"
    assert not _schema_errors("f6-human-review-final.schema.json", final)
    assert (
        validate_f6_human_review_final(
            final,
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=review_material["automatic_result"],
            request=review_material["request"],
            receipt=_receipt(review_material, verdict),
        )
        == final
    )


@pytest.mark.parametrize("key", ["truth", "nested_expected", "auto-result"])
def test_blind_package_rejects_truth_expected_and_automatic_results(
    key: str, review_material: dict[str, object]
) -> None:
    package = {
        "source": {"path": "fixture.metis", "text": "rule x"},
        "ast_inventory": {"root": "Rule"},
        "ir_value": {"opcode": "filter"},
        "candidate_response": {key: "leak"},
    }
    with pytest.raises(F6HumanReviewError, match="forbidden"):
        create_f6_blind_review_request(
            policy=review_material["policy"],
            task_id="f6-case-001",
            nonce="2" * 64,
            candidate={"text": "candidate"},
            blind_package=package,
        )


def test_blind_package_must_match_the_sealed_truth(review_material: dict[str, object]) -> None:
    package = deepcopy(review_material["request"]["blind_package"])
    package["ast_inventory"] = {"elements": [{"name": "invented"}]}
    request = create_f6_blind_review_request(
        policy=review_material["policy"],
        task_id="f6-case-001",
        nonce="3" * 64,
        candidate=review_material["candidate"],
        blind_package=package,
    )
    receipt = sign_f6_human_review_receipt(
        policy=review_material["policy"],
        request=request,
        reviewer_id="blind-reviewer",
        private_key=review_material["key"],
        verdict="pass",
        issued_at="2026-08-24T12:00:00Z",
    )

    with pytest.raises(F6HumanReviewError, match="AST differs"):
        finalize_f6_human_review(
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=review_material["automatic_result"],
            request=request,
            receipt=receipt,
        )


def test_policy_requires_three_separate_identities() -> None:
    key = Ed25519PrivateKey.generate()
    with pytest.raises(F6HumanReviewError, match="truth author"):
        seal_f6_human_review_policy(
            truth_author_id="same-person",
            model_operator_id="same-person",
            rubric_sha256="sha256:" + "a" * 64,
            reviewers=[{"reviewer_id": "blind-reviewer", "public_key": _key_hex(key)}],
        )
    with pytest.raises(F6HumanReviewError, match="reviewer identity"):
        seal_f6_human_review_policy(
            truth_author_id="truth-author",
            model_operator_id="model-operator",
            rubric_sha256="sha256:" + "a" * 64,
            reviewers=[{"reviewer_id": "truth-author", "public_key": _key_hex(key)}],
        )


def test_tampered_receipt_and_wrong_key_cannot_finalize(review_material: dict[str, object]) -> None:
    receipt = _receipt(review_material)
    receipt["verdict"] = "fail"
    with pytest.raises(F6HumanReviewError, match="signature|hash|bind"):
        finalize_f6_human_review(
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=review_material["automatic_result"],
            request=review_material["request"],
            receipt=receipt,
        )
    with pytest.raises(F6HumanReviewError, match="does not match"):
        sign_f6_human_review_receipt(
            policy=review_material["policy"],
            request=review_material["request"],
            reviewer_id="blind-reviewer",
            private_key=Ed25519PrivateKey.generate(),
            verdict="pass",
            issued_at="2026-08-24T12:00:00Z",
        )


def test_auto_failure_and_candidate_mismatch_are_fail_closed(
    review_material: dict[str, object],
) -> None:
    receipt = _receipt(review_material)
    failed_auto = dict(review_material["automatic_result"])
    failed_auto["status"] = "automatic_fail"
    with pytest.raises(F6HumanReviewError, match="hash|automatic result"):
        finalize_f6_human_review(
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=failed_auto,
            request=review_material["request"],
            receipt=receipt,
        )
    mismatched_auto = dict(review_material["automatic_result"])
    mismatched_evidence = dict(mismatched_auto["evidence"])
    mismatched_evidence["candidate_sha256"] = "sha256:" + "d" * 64
    mismatched_auto["evidence"] = mismatched_evidence
    mismatch_body = {key: value for key, value in mismatched_auto.items() if key != "result_sha256"}
    mismatched_auto["result_sha256"] = _sha(mismatch_body)
    with pytest.raises(F6HumanReviewError, match="automatic result|credit-ineligible"):
        finalize_f6_human_review(
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=mismatched_auto,
            request=review_material["request"],
            receipt=receipt,
        )


def test_standalone_self_hashed_credit_grant_is_rejected(
    review_material: dict[str, object],
) -> None:
    forged_body = {
        "schema_version": 1,
        "task_id": "f6-case-001",
        "status": "f6_credit_granted",
        "eligible_for_f6_credit": True,
        "policy_sha256": "sha256:" + "1" * 64,
        "request_sha256": "sha256:" + "2" * 64,
        "receipt_sha256": "sha256:" + "3" * 64,
        "automatic_result_sha256": "sha256:" + "4" * 64,
        "human_verdict": "pass",
    }
    forged = {**forged_body, "final_sha256": _sha(forged_body)}

    with pytest.raises(F6HumanReviewError, match="protected F-6 authority"):
        validate_f6_human_review_final(
            forged,
            policy=review_material["policy"],
            truth=review_material["truth"],
            candidate=review_material["candidate"],
            automatic_result=review_material["automatic_result"],
            request=review_material["request"],
            receipt=_receipt(review_material),
        )
