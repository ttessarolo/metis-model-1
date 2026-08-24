"""Fail-closed blind-human-review receipt contract for F-6.

This module supplies an *infrastructure* seam only.  A reviewer signature proves
key possession, but this repository deliberately has no credit-granting
implementation until a protected policy/truth registry and atomic durable nonce
authority exist.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .f6_structural import F6ResultError, validate_f6_auto_result, validate_f6_truth

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
VERDICTS = frozenset({"pass", "fail", "abstain"})
POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "status",
        "truth_author_id",
        "model_operator_id",
        "rubric_sha256",
        "reviewers",
        "model_outputs_observed",
        "policy_sha256",
    }
)
REVIEWER_KEYS = frozenset({"reviewer_id", "public_key"})
REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "policy_sha256",
        "task_id",
        "nonce",
        "candidate_sha256",
        "blind_package_sha256",
        "blind_package",
        "request_sha256",
    }
)
BLIND_PACKAGE_KEYS = frozenset({"source", "ast_inventory", "ir_value", "candidate_response"})
BLIND_SOURCE_KEYS = frozenset({"path", "text"})
RECEIPT_BODY_KEYS = frozenset(
    {
        "schema_version",
        "policy_sha256",
        "request_sha256",
        "task_id",
        "nonce",
        "candidate_sha256",
        "blind_package_sha256",
        "reviewer_id",
        "verdict",
        "reason_codes",
        "issued_at",
    }
)
RECEIPT_KEYS = RECEIPT_BODY_KEYS | frozenset({"signature", "receipt_sha256"})
FINAL_KEYS = frozenset(
    {
        "schema_version",
        "task_id",
        "status",
        "eligible_for_f6_credit",
        "policy_sha256",
        "request_sha256",
        "receipt_sha256",
        "automatic_result_sha256",
        "human_verdict",
        "final_sha256",
    }
)


class F6HumanReviewError(ValueError):
    """Raised when blind review evidence cannot safely receive F-6 credit."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise F6HumanReviewError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise F6HumanReviewError(f"{label} must contain exactly {sorted(keys)}")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or ID_RE.fullmatch(value) is None:
        raise F6HumanReviewError(f"{label} must be a stable identifier")
    return value


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or HASH_RE.fullmatch(value) is None:
        raise F6HumanReviewError(f"{label} must be sha256:<64 hex>")
    return value


def _json_value(value: Any, label: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise F6HumanReviewError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{label}[]") for item in value]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise F6HumanReviewError(f"{label} contains a non-string object key")
        return {key: _json_value(item, f"{label}.{key}") for key, item in value.items()}
    raise F6HumanReviewError(f"{label} contains a non-JSON value")


def _public_key(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or HEX_RE.fullmatch(value) is None:
        raise F6HumanReviewError(f"{label} must be an Ed25519 public key encoded as 32-byte hex")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(value))
    except ValueError as error:
        raise F6HumanReviewError(f"{label} is not an Ed25519 public key") from error
    return value


def _signature(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 128 or HEX_RE.fullmatch(value) is None:
        raise F6HumanReviewError(f"{label} must be an Ed25519 signature encoded as 64-byte hex")
    return value


def _forbidden_blind_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    parts = frozenset(part for part in re.split(r"[^a-z0-9]+", normalized) if part)
    return (
        "truth" in parts
        or "expected" in parts
        or "auto_result" in normalized
        or "automatic_result" in normalized
    )


def _assert_blind(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise F6HumanReviewError(f"{label} contains a non-string object key")
            if _forbidden_blind_key(key):
                raise F6HumanReviewError(f"{label} exposes a forbidden blind-review field: {key}")
            _assert_blind(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_blind(item, f"{label}[{index}]")


def _reviewers(value: Any, *, truth_author_id: str, model_operator_id: str) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise F6HumanReviewError("policy.reviewers must be a non-empty list")
    reviewers: list[dict[str, str]] = []
    for index, item in enumerate(value):
        raw = _exact_mapping(item, REVIEWER_KEYS, f"policy.reviewers[{index}]")
        reviewer_id = _identifier(raw["reviewer_id"], f"policy.reviewers[{index}].reviewer_id")
        public_key = _public_key(raw["public_key"], f"policy.reviewers[{index}].public_key")
        if reviewer_id in {truth_author_id, model_operator_id}:
            raise F6HumanReviewError(
                "reviewer identity must differ from truth author and model operator"
            )
        reviewers.append({"reviewer_id": reviewer_id, "public_key": public_key})
    if not reviewers or len(reviewers) > 64:
        raise F6HumanReviewError("policy.reviewers must contain between 1 and 64 reviewers")
    ids = [item["reviewer_id"] for item in reviewers]
    keys = [item["public_key"] for item in reviewers]
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
        raise F6HumanReviewError("policy.reviewers contains duplicate identities or public keys")
    return sorted(reviewers, key=lambda item: item["reviewer_id"])


def _policy_body(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {key: policy[key] for key in POLICY_KEYS - {"policy_sha256"}}


def validate_f6_human_review_policy(policy: Any) -> dict[str, Any]:
    """Validate a sealed, pre-output policy and return its canonical form."""
    raw = _exact_mapping(policy, POLICY_KEYS, "policy")
    if raw["schema_version"] != 1 or raw["policy_id"] != "f6-human-review-policy/v1":
        raise F6HumanReviewError("policy has an unsupported schema or policy id")
    if raw["status"] != "sealed_pre_output" or raw["model_outputs_observed"] is not False:
        raise F6HumanReviewError("policy must be sealed before model outputs are observed")
    truth_author_id = _identifier(raw["truth_author_id"], "policy.truth_author_id")
    model_operator_id = _identifier(raw["model_operator_id"], "policy.model_operator_id")
    if truth_author_id == model_operator_id:
        raise F6HumanReviewError("truth author must differ from model operator")
    canonical = {
        "schema_version": 1,
        "policy_id": "f6-human-review-policy/v1",
        "status": "sealed_pre_output",
        "truth_author_id": truth_author_id,
        "model_operator_id": model_operator_id,
        "rubric_sha256": _hash(raw["rubric_sha256"], "policy.rubric_sha256"),
        "reviewers": _reviewers(
            raw["reviewers"], truth_author_id=truth_author_id, model_operator_id=model_operator_id
        ),
        "model_outputs_observed": False,
    }
    if raw["policy_sha256"] != _sha(canonical):
        raise F6HumanReviewError("policy.policy_sha256 does not bind the policy")
    return {**canonical, "policy_sha256": raw["policy_sha256"]}


def seal_f6_human_review_policy(
    *,
    truth_author_id: str,
    model_operator_id: str,
    rubric_sha256: str,
    reviewers: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Create an immutable policy without accepting any model-output payload."""
    provisional = {
        "schema_version": 1,
        "policy_id": "f6-human-review-policy/v1",
        "status": "sealed_pre_output",
        "truth_author_id": truth_author_id,
        "model_operator_id": model_operator_id,
        "rubric_sha256": rubric_sha256,
        "reviewers": list(reviewers),
        "model_outputs_observed": False,
        "policy_sha256": "sha256:" + "0" * 64,
    }
    raw = _exact_mapping(provisional, POLICY_KEYS, "policy")
    truth_author = _identifier(raw["truth_author_id"], "policy.truth_author_id")
    model_operator = _identifier(raw["model_operator_id"], "policy.model_operator_id")
    if truth_author == model_operator:
        raise F6HumanReviewError("truth author must differ from model operator")
    body = {
        "schema_version": 1,
        "policy_id": "f6-human-review-policy/v1",
        "status": "sealed_pre_output",
        "truth_author_id": truth_author,
        "model_operator_id": model_operator,
        "rubric_sha256": _hash(raw["rubric_sha256"], "policy.rubric_sha256"),
        "reviewers": _reviewers(
            raw["reviewers"], truth_author_id=truth_author, model_operator_id=model_operator
        ),
        "model_outputs_observed": False,
    }
    return {**body, "policy_sha256": _sha(body)}


def _blind_package(value: Any) -> dict[str, Any]:
    raw = _exact_mapping(value, BLIND_PACKAGE_KEYS, "request.blind_package")
    source = _exact_mapping(raw["source"], BLIND_SOURCE_KEYS, "request.blind_package.source")
    path = source["path"]
    parsed = PurePosixPath(path) if type(path) is str else PurePosixPath("")
    if (
        type(path) is not str
        or parsed.is_absolute()
        or ".." in parsed.parts
        or parsed.suffix != ".metis"
    ):
        raise F6HumanReviewError("request.blind_package.source.path must be a safe .metis path")
    text = source["text"]
    if type(text) is not str or not text:
        raise F6HumanReviewError("request.blind_package.source.text must be non-empty")
    package = {
        "source": {"path": path, "text": text},
        "ast_inventory": _json_value(raw["ast_inventory"], "request.blind_package.ast_inventory"),
        "ir_value": _json_value(raw["ir_value"], "request.blind_package.ir_value"),
        "candidate_response": _json_value(
            raw["candidate_response"], "request.blind_package.candidate_response"
        ),
    }
    _assert_blind(package, "request.blind_package")
    return package


def _request_body(request: Mapping[str, Any]) -> dict[str, Any]:
    return {key: request[key] for key in REQUEST_KEYS - {"request_sha256"}}


def validate_f6_blind_review_request(request: Any, *, policy: Any | None = None) -> dict[str, Any]:
    """Validate that a request binds one candidate but reveals no answer key."""
    raw = _exact_mapping(request, REQUEST_KEYS, "request")
    if raw["schema_version"] != 1:
        raise F6HumanReviewError("request has an unsupported schema")
    task_id = _identifier(raw["task_id"], "request.task_id")
    nonce = raw["nonce"]
    if type(nonce) is not str or NONCE_RE.fullmatch(nonce) is None:
        raise F6HumanReviewError("request.nonce must be 32-byte lowercase hex")
    expected_request_id = f"f6-blind-review/{task_id}/{nonce}"
    if raw["request_id"] != expected_request_id:
        raise F6HumanReviewError("request.request_id does not bind task and nonce")
    canonical = {
        "schema_version": 1,
        "request_id": expected_request_id,
        "policy_sha256": _hash(raw["policy_sha256"], "request.policy_sha256"),
        "task_id": task_id,
        "nonce": nonce,
        "candidate_sha256": _hash(raw["candidate_sha256"], "request.candidate_sha256"),
        "blind_package_sha256": _hash(raw["blind_package_sha256"], "request.blind_package_sha256"),
        "blind_package": _blind_package(raw["blind_package"]),
    }
    if canonical["blind_package_sha256"] != _sha(canonical["blind_package"]):
        raise F6HumanReviewError("request.blind_package_sha256 does not bind the package")
    if canonical["candidate_sha256"] != _sha(canonical["blind_package"]["candidate_response"]):
        raise F6HumanReviewError("request.candidate_sha256 does not bind candidate_response")
    if raw["request_sha256"] != _sha(canonical):
        raise F6HumanReviewError("request.request_sha256 does not bind the request")
    if policy is not None:
        sealed_policy = validate_f6_human_review_policy(policy)
        if canonical["policy_sha256"] != sealed_policy["policy_sha256"]:
            raise F6HumanReviewError("request is not bound to the supplied policy")
    return {**canonical, "request_sha256": raw["request_sha256"]}


def create_f6_blind_review_request(
    *, policy: Any, task_id: str, nonce: str, candidate: Any, blind_package: Any
) -> dict[str, Any]:
    """Build the sole blinded package accepted by this review protocol."""
    sealed_policy = validate_f6_human_review_policy(policy)
    body = {
        "schema_version": 1,
        "request_id": f"f6-blind-review/{task_id}/{nonce}",
        "policy_sha256": sealed_policy["policy_sha256"],
        "task_id": task_id,
        "nonce": nonce,
        "candidate_sha256": _sha(_json_value(candidate, "candidate")),
        "blind_package_sha256": _sha(_blind_package(blind_package)),
        "blind_package": _blind_package(blind_package),
    }
    # Validate the body by temporarily adding its real digest, rather than
    # accepting a placeholder hash that could escape into a review package.
    request = {**body, "request_sha256": _sha(body)}
    return validate_f6_blind_review_request(request, policy=sealed_policy)


def _receipt_body(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: receipt[key] for key in RECEIPT_BODY_KEYS}


def _reason_codes(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise F6HumanReviewError("receipt.reason_codes must be a list")
    if len(value) > 32:
        raise F6HumanReviewError("receipt.reason_codes has too many entries")
    codes = []
    for item in value:
        if type(item) is not str or ID_RE.fullmatch(item) is None:
            raise F6HumanReviewError("receipt.reason_codes contains an invalid code")
        codes.append(item)
    if codes != sorted(set(codes)):
        raise F6HumanReviewError("receipt.reason_codes must be sorted and distinct")
    return codes


def _receipt_body_from_inputs(
    *, request: Mapping[str, Any], reviewer_id: str, verdict: str, reason_codes: Any, issued_at: str
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise F6HumanReviewError("receipt.verdict must be pass, fail, or abstain")
    if type(issued_at) is not str or not issued_at.strip() or len(issued_at) > 128:
        raise F6HumanReviewError("receipt.issued_at must be a bounded non-empty string")
    return {
        "schema_version": 1,
        "policy_sha256": request["policy_sha256"],
        "request_sha256": request["request_sha256"],
        "task_id": request["task_id"],
        "nonce": request["nonce"],
        "candidate_sha256": request["candidate_sha256"],
        "blind_package_sha256": request["blind_package_sha256"],
        "reviewer_id": _identifier(reviewer_id, "receipt.reviewer_id"),
        "verdict": verdict,
        "reason_codes": _reason_codes(reason_codes),
        "issued_at": issued_at,
    }


def _private_key(value: bytes | Ed25519PrivateKey) -> Ed25519PrivateKey:
    if isinstance(value, Ed25519PrivateKey):
        return value
    if not isinstance(value, bytes) or len(value) != 32:
        raise F6HumanReviewError("private key must be an ephemeral 32-byte Ed25519 key")
    try:
        return Ed25519PrivateKey.from_private_bytes(value)
    except ValueError as error:
        raise F6HumanReviewError("private key is not Ed25519") from error


def sign_f6_human_review_receipt(
    *,
    policy: Any,
    request: Any,
    reviewer_id: str,
    private_key: bytes | Ed25519PrivateKey,
    verdict: str,
    reason_codes: Sequence[str] = (),
    issued_at: str,
) -> dict[str, Any]:
    """Sign a review verdict; test callers may generate the private key in memory."""
    sealed_policy = validate_f6_human_review_policy(policy)
    blind_request = validate_f6_blind_review_request(request, policy=sealed_policy)
    key = _private_key(private_key)
    reviewer = next(
        (item for item in sealed_policy["reviewers"] if item["reviewer_id"] == reviewer_id), None
    )
    if reviewer is None:
        raise F6HumanReviewError("receipt reviewer is not authorized by the policy")
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    if public != reviewer["public_key"]:
        raise F6HumanReviewError("private key does not match the authorized reviewer public key")
    body = _receipt_body_from_inputs(
        request=blind_request,
        reviewer_id=reviewer_id,
        verdict=verdict,
        reason_codes=reason_codes,
        issued_at=issued_at,
    )
    signature = key.sign(_canonical(body)).hex()
    receipt = {**body, "signature": signature, "receipt_sha256": "sha256:" + "0" * 64}
    signed_body = {key: receipt[key] for key in RECEIPT_KEYS - {"receipt_sha256"}}
    return {**receipt, "receipt_sha256": _sha(signed_body)}


def validate_f6_human_review_receipt(receipt: Any, *, policy: Any, request: Any) -> dict[str, Any]:
    """Verify the receipt's exact request binding and Ed25519 signature."""
    sealed_policy = validate_f6_human_review_policy(policy)
    blind_request = validate_f6_blind_review_request(request, policy=sealed_policy)
    raw = _exact_mapping(receipt, RECEIPT_KEYS, "receipt")
    if raw["schema_version"] != 1:
        raise F6HumanReviewError("receipt has an unsupported schema")
    body = _receipt_body(raw)
    expected = _receipt_body_from_inputs(
        request=blind_request,
        reviewer_id=body["reviewer_id"],
        verdict=body["verdict"],
        reason_codes=body["reason_codes"],
        issued_at=body["issued_at"],
    )
    if body != expected:
        raise F6HumanReviewError("receipt does not bind the exact blind request")
    signature = _signature(raw["signature"], "receipt.signature")
    receipt_with_signature = {**body, "signature": signature}
    if raw["receipt_sha256"] != _sha(receipt_with_signature):
        raise F6HumanReviewError("receipt.receipt_sha256 does not bind the signed receipt")
    reviewer = next(
        (item for item in sealed_policy["reviewers"] if item["reviewer_id"] == body["reviewer_id"]),
        None,
    )
    if reviewer is None:
        raise F6HumanReviewError("receipt reviewer is not authorized by the policy")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(reviewer["public_key"])).verify(
            bytes.fromhex(signature), _canonical(body)
        )
    except (InvalidSignature, ValueError) as error:
        raise F6HumanReviewError("receipt signature is invalid") from error
    return {**body, "signature": signature, "receipt_sha256": raw["receipt_sha256"]}


def _automatic_pass(
    automatic_result: Any,
    request: Mapping[str, Any],
    *,
    truth: Any,
    candidate: Any,
) -> str:
    try:
        validated = validate_f6_auto_result(automatic_result, truth=truth, candidate=candidate)
    except F6ResultError as error:
        raise F6HumanReviewError(
            "automatic result does not implement the F-6 result contract"
        ) from error
    if (
        validated["task_id"] != request["task_id"]
        or validated["status"] != "automatic_pass_human_pending"
        or validated["eligible_for_f6_credit"] is not False
        or validated["outcomes"]
        != {"ast": "pass", "ir": "pass", "semantic": "pass", "human": "not_run"}
        or validated["failure_reasons"] != []
        or validated["evidence"]["candidate_sha256"] != request["candidate_sha256"]
    ):
        raise F6HumanReviewError("automatic result is not a credit-ineligible F-6 automatic pass")
    return validated["result_sha256"]


def _assert_blind_package_grounded(request: Mapping[str, Any], truth: Any) -> dict[str, Any]:
    sealed = validate_f6_truth(truth)
    package = request["blind_package"]
    source = package["source"]
    source_sha256 = "sha256:" + hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
    if source["path"] != sealed["source"]["source_path"]:
        raise F6HumanReviewError("blind package source path differs from sealed truth")
    if source_sha256 != sealed["source"]["source_sha256"]:
        raise F6HumanReviewError("blind package source bytes differ from sealed truth")
    if _sha(package["ast_inventory"]) != sealed["oracle_evidence"]["ast_inventory_sha256"]:
        raise F6HumanReviewError("blind package AST differs from sealed truth")
    if _sha(package["ir_value"]) != sealed["oracle_evidence"]["ir_value_sha256"]:
        raise F6HumanReviewError("blind package IR differs from sealed truth")
    return sealed


def finalize_f6_human_review(
    *,
    policy: Any,
    truth: Any,
    candidate: Any,
    automatic_result: Any,
    request: Any,
    receipt: Any,
) -> dict[str, Any]:
    """Record a negative review; fail closed on pass without protected authority."""
    sealed_policy = validate_f6_human_review_policy(policy)
    blind_request = validate_f6_blind_review_request(request, policy=sealed_policy)
    sealed_truth = _assert_blind_package_grounded(blind_request, truth)
    automatic_result_sha256 = _automatic_pass(
        automatic_result,
        blind_request,
        truth=sealed_truth,
        candidate=candidate,
    )
    signed_receipt = validate_f6_human_review_receipt(
        receipt, policy=sealed_policy, request=blind_request
    )
    if signed_receipt["verdict"] == "pass":
        raise F6HumanReviewError(
            "protected F-6 review authority is unavailable; signed pass cannot grant credit"
        )
    final = {
        "schema_version": 1,
        "task_id": blind_request["task_id"],
        "status": "f6_credit_denied",
        "eligible_for_f6_credit": False,
        "policy_sha256": sealed_policy["policy_sha256"],
        "request_sha256": blind_request["request_sha256"],
        "receipt_sha256": signed_receipt["receipt_sha256"],
        "automatic_result_sha256": automatic_result_sha256,
        "human_verdict": signed_receipt["verdict"],
    }
    return validate_f6_human_review_final(
        {**final, "final_sha256": _sha(final)},
        policy=sealed_policy,
        truth=sealed_truth,
        candidate=candidate,
        automatic_result=automatic_result,
        request=blind_request,
        receipt=signed_receipt,
    )


def validate_f6_human_review_final(
    value: Any,
    *,
    policy: Any,
    truth: Any,
    candidate: Any,
    automatic_result: Any,
    request: Any,
    receipt: Any,
) -> dict[str, Any]:
    """Validate a credit-denied final record against every supplied input."""

    raw = _exact_mapping(value, FINAL_KEYS, "final")
    if raw["schema_version"] != 1:
        raise F6HumanReviewError("final has an unsupported schema")
    task_id = _identifier(raw["task_id"], "final.task_id")
    verdict = raw["human_verdict"]
    if verdict not in VERDICTS:
        raise F6HumanReviewError("final.human_verdict is outside the registry")
    if verdict == "pass" or raw["eligible_for_f6_credit"] is not False:
        raise F6HumanReviewError("protected F-6 authority is required for any credit grant")
    if raw["status"] != "f6_credit_denied":
        raise F6HumanReviewError("final status must remain credit-denied")
    canonical = {
        "schema_version": 1,
        "task_id": task_id,
        "status": raw["status"],
        "eligible_for_f6_credit": False,
        "policy_sha256": _hash(raw["policy_sha256"], "final.policy_sha256"),
        "request_sha256": _hash(raw["request_sha256"], "final.request_sha256"),
        "receipt_sha256": _hash(raw["receipt_sha256"], "final.receipt_sha256"),
        "automatic_result_sha256": _hash(
            raw["automatic_result_sha256"], "final.automatic_result_sha256"
        ),
        "human_verdict": verdict,
    }
    if raw["final_sha256"] != _sha(canonical):
        raise F6HumanReviewError("final.final_sha256 does not bind the final result")
    sealed_policy = validate_f6_human_review_policy(policy)
    blind_request = validate_f6_blind_review_request(request, policy=sealed_policy)
    sealed_truth = _assert_blind_package_grounded(blind_request, truth)
    automatic_result_sha256 = _automatic_pass(
        automatic_result,
        blind_request,
        truth=sealed_truth,
        candidate=candidate,
    )
    signed_receipt = validate_f6_human_review_receipt(
        receipt, policy=sealed_policy, request=blind_request
    )
    if (
        canonical["policy_sha256"] != sealed_policy["policy_sha256"]
        or canonical["task_id"] != blind_request["task_id"]
        or canonical["request_sha256"] != blind_request["request_sha256"]
        or canonical["receipt_sha256"] != signed_receipt["receipt_sha256"]
        or canonical["human_verdict"] != signed_receipt["verdict"]
        or canonical["automatic_result_sha256"] != automatic_result_sha256
    ):
        raise F6HumanReviewError("final differs from its supplied review evidence")
    return {**canonical, "final_sha256": raw["final_sha256"]}
