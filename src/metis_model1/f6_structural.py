"""Deterministic, fail-closed automatic oracle for F-6 structural explanations.

The automatic lane binds a model answer to a previously verified Metis Oracle
envelope and an exact roster of AST/IR claims.  It deliberately cannot award
the required human predicate, so an automatic pass remains ineligible for F-6
benchmark credit until a separate blind-review authority is implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OID_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
CLAIM_BASES = frozenset({"ast", "ir", "ast_ir"})
TRUTH_KEYS = frozenset(
    {
        "schema_version",
        "truth_id",
        "task_id",
        "family",
        "status",
        "source",
        "oracle_evidence",
        "required_claims",
        "human_review_required",
        "model_outputs_observed",
        "truth_sha256",
    }
)
SOURCE_KEYS = frozenset(
    {
        "toolchain_revision",
        "toolchain_tree",
        "source_blob_oid",
        "source_sha256",
        "source_path",
        "oracle_request_sha256",
        "oracle_envelope_sha256",
    }
)
ORACLE_KEYS = frozenset(
    {
        "endpoint_name",
        "ast_signature",
        "ir_signature",
        "ast_inventory_sha256",
        "ir_value_sha256",
    }
)
CLAIM_KEYS = frozenset({"claim_id", "basis", "ast_path", "ir_path", "value"})
CANDIDATE_KEYS = frozenset(
    {"schema_version", "task_id", "ast_signature", "ir_signature", "claims", "summary"}
)
RESULT_KEYS = frozenset(
    {
        "schema_version",
        "task_id",
        "status",
        "eligible_for_f6_credit",
        "outcomes",
        "failure_reasons",
        "evidence",
        "result_sha256",
    }
)
OUTCOME_KEYS = frozenset({"ast", "ir", "semantic", "human"})
RESULT_EVIDENCE_KEYS = frozenset({"truth_sha256", "candidate_sha256", "oracle_envelope_sha256"})
FAILURE_REASON_RE = re.compile(
    r"^(?:ast_signature_mismatch|ir_signature_mismatch|claim_roster_mismatch|"
    r"claim_mismatch:[a-z0-9][a-z0-9._/-]{0,127})$"
)


class F6StructuralError(ValueError):
    """Base error for the structural-explanation contract."""


class F6TruthError(F6StructuralError):
    """Raised when pre-output truth or compiler evidence is not trustworthy."""


class F6CandidateError(F6StructuralError):
    """Raised when a parsed model output does not implement the candidate wire."""


class F6ResultError(F6StructuralError):
    """Raised when an automatic F-6 result is malformed or self-inconsistent."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise F6StructuralError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _source_sha256(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _git_blob_oid(source: str) -> str:
    content = source.encode("utf-8")
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324 - Git object identity


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise F6StructuralError(f"{label} must contain exactly {sorted(keys)}")
    return value


def _nonempty_string(value: Any, label: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise F6StructuralError(f"{label} must be a bounded non-empty string")
    return value


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or HASH_RE.fullmatch(value) is None:
        raise F6StructuralError(f"{label} must be sha256:<64 hex>")
    return value


def _json_value(value: Any, label: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise F6StructuralError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{label}[]") for item in value]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise F6StructuralError(f"{label} contains a non-string object key")
        return {key: _json_value(item, f"{label}.{key}") for key, item in value.items()}
    raise F6StructuralError(f"{label} contains a non-JSON value")


def _claim(value: Any, label: str) -> dict[str, Any]:
    try:
        raw = _exact_mapping(value, CLAIM_KEYS, label)
        claim_id = _nonempty_string(raw["claim_id"], f"{label}.claim_id", maximum=128)
        if ID_RE.fullmatch(claim_id) is None:
            raise F6StructuralError(f"{label}.claim_id has an invalid identifier")
        basis = raw["basis"]
        if basis not in CLAIM_BASES:
            raise F6StructuralError(f"{label}.basis is outside the F-6 registry")
        ast_path = raw["ast_path"]
        ir_path = raw["ir_path"]
        for name, path in (("ast_path", ast_path), ("ir_path", ir_path)):
            if path is not None:
                _nonempty_string(path, f"{label}.{name}", maximum=512)
                _pointer_tokens(path, f"{label}.{name}")
        if basis in {"ast", "ast_ir"} and ast_path is None:
            raise F6StructuralError(f"{label} requires an AST path")
        if basis in {"ir", "ast_ir"} and ir_path is None:
            raise F6StructuralError(f"{label} requires an IR path")
        if basis == "ast" and ir_path is not None:
            raise F6StructuralError(f"{label} AST-only claim must not carry an IR path")
        if basis == "ir" and ast_path is not None:
            raise F6StructuralError(f"{label} IR-only claim must not carry an AST path")
        return {
            "claim_id": claim_id,
            "basis": basis,
            "ast_path": ast_path,
            "ir_path": ir_path,
            "value": _json_value(raw["value"], f"{label}.value"),
        }
    except F6StructuralError:
        raise
    except Exception as error:  # noqa: BLE001 - untrusted nested mappings fail closed
        raise F6StructuralError(f"{label} is malformed") from error


def _claims(value: Any, label: str) -> list[dict[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= 64
    ):
        raise F6StructuralError(f"{label} must contain between 1 and 64 claims")
    claims = [_claim(item, f"{label}[{index}]") for index, item in enumerate(value)]
    ids = [item["claim_id"] for item in claims]
    if len(ids) != len(set(ids)):
        raise F6StructuralError(f"{label} contains duplicate claim ids")
    return sorted(claims, key=lambda item: item["claim_id"])


def _pointer_tokens(path: str, label: str) -> list[str]:
    if not path.startswith("/"):
        raise F6StructuralError(f"{label} must be an absolute JSON Pointer")
    tokens: list[str] = []
    for raw in path[1:].split("/"):
        index = 0
        decoded = ""
        while index < len(raw):
            if raw[index] != "~":
                decoded += raw[index]
                index += 1
                continue
            if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                raise F6StructuralError(f"{label} contains an invalid JSON Pointer escape")
            decoded += "~" if raw[index + 1] == "0" else "/"
            index += 2
        tokens.append(decoded)
    return tokens


def _resolve_pointer(value: Any, path: str, label: str) -> Any:
    current = value
    for token in _pointer_tokens(path, label):
        if isinstance(current, Mapping):
            if token not in current:
                raise F6TruthError(f"{label} does not resolve in its Oracle value")
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise F6TruthError(f"{label} has a non-canonical array index")
            index = int(token)
            if index >= len(current):
                raise F6TruthError(f"{label} array index is outside its Oracle value")
            current = current[index]
            continue
        raise F6TruthError(f"{label} traverses a scalar Oracle value")
    return current


def _assert_claims_grounded(
    claims: Sequence[Mapping[str, Any]], ast_inventory: Any, ir_value: Any
) -> None:
    for claim in claims:
        claim_id = claim["claim_id"]
        expected = claim["value"]
        if claim["basis"] in {"ast", "ast_ir"}:
            actual = _resolve_pointer(
                ast_inventory, claim["ast_path"], f"F-6 claim {claim_id} AST path"
            )
            if actual != expected:
                raise F6TruthError(f"F-6 claim {claim_id} value disagrees with the AST")
        if claim["basis"] in {"ir", "ast_ir"}:
            actual = _resolve_pointer(ir_value, claim["ir_path"], f"F-6 claim {claim_id} IR path")
            if actual != expected:
                raise F6TruthError(f"F-6 claim {claim_id} value disagrees with the IR")


def _validate_source(value: Any) -> dict[str, Any]:
    raw = _exact_mapping(value, SOURCE_KEYS, "F-6 source")
    revision = raw["toolchain_revision"]
    tree = raw["toolchain_tree"]
    source_blob_oid = raw["source_blob_oid"]
    if any(type(item) is not str or OID_RE.fullmatch(item) is None for item in (revision, tree)):
        raise F6TruthError("F-6 source revision/tree must be exact Git object ids")
    if type(source_blob_oid) is not str or OID_RE.fullmatch(source_blob_oid) is None:
        raise F6TruthError("F-6 source blob must be an exact Git object id")
    source_path = _nonempty_string(raw["source_path"], "F-6 source path", maximum=1024)
    parsed = PurePosixPath(source_path)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.suffix != ".metis":
        raise F6TruthError("F-6 source path must be a safe relative .metis path")
    return {
        "toolchain_revision": revision,
        "toolchain_tree": tree,
        "source_blob_oid": source_blob_oid,
        "source_sha256": _hash(raw["source_sha256"], "F-6 source content hash"),
        "source_path": source_path,
        "oracle_request_sha256": _hash(raw["oracle_request_sha256"], "F-6 Oracle request hash"),
        "oracle_envelope_sha256": _hash(raw["oracle_envelope_sha256"], "F-6 Oracle envelope hash"),
    }


def _validate_oracle_evidence(value: Any) -> dict[str, Any]:
    raw = _exact_mapping(value, ORACLE_KEYS, "F-6 Oracle evidence")
    return {
        "endpoint_name": _nonempty_string(raw["endpoint_name"], "F-6 endpoint name"),
        "ast_signature": _hash(raw["ast_signature"], "F-6 AST signature"),
        "ir_signature": _hash(raw["ir_signature"], "F-6 IR signature"),
        "ast_inventory_sha256": _hash(raw["ast_inventory_sha256"], "F-6 AST inventory hash"),
        "ir_value_sha256": _hash(raw["ir_value_sha256"], "F-6 IR value hash"),
    }


def validate_f6_truth(value: Any) -> dict[str, Any]:
    """Validate and normalize one sealed, pre-output F-6 truth contract."""

    try:
        raw = _exact_mapping(value, TRUTH_KEYS, "F-6 truth")
        task_id = _nonempty_string(raw["task_id"], "F-6 task id", maximum=128)
        truth_id = _nonempty_string(raw["truth_id"], "F-6 truth id", maximum=160)
        if ID_RE.fullmatch(task_id) is None or truth_id != f"f6-truth/{task_id}":
            raise F6TruthError("F-6 task/truth identity is invalid")
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
            or raw["family"] != "F-6"
            or raw["status"] != "sealed_pre_output"
            or raw["human_review_required"] is not True
            or raw["model_outputs_observed"] is not False
        ):
            raise F6TruthError("F-6 truth state is not a sealed pre-output contract")
        normalized = {
            "schema_version": 1,
            "truth_id": truth_id,
            "task_id": task_id,
            "family": "F-6",
            "status": "sealed_pre_output",
            "source": _validate_source(raw["source"]),
            "oracle_evidence": _validate_oracle_evidence(raw["oracle_evidence"]),
            "required_claims": _claims(raw["required_claims"], "F-6 required claims"),
            "human_review_required": True,
            "model_outputs_observed": False,
        }
        if raw["truth_sha256"] != _sha(normalized):
            raise F6TruthError("F-6 truth hash does not match its canonical body")
        return {**normalized, "truth_sha256": raw["truth_sha256"]}
    except F6TruthError:
        raise
    except F6StructuralError as error:
        raise F6TruthError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - truth is an untrusted contract boundary
        raise F6TruthError("F-6 truth is malformed") from error


def seal_f6_truth(
    *,
    task_id: str,
    source_path: str,
    source_blob_oid: str,
    oracle_request: Any,
    oracle_envelope: Any,
    required_claims: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create F-6 truth only from a fully verified endpoint-mode Oracle envelope."""

    from metis_model1.oracles import OracleError, build_oracle_request, verify_oracle_envelope

    try:
        if not isinstance(oracle_request, Mapping):
            raise F6TruthError("F-6 Oracle request must be an object")
        workspace = oracle_request.get("workspace_sources")
        if not isinstance(workspace, list) or any(
            not isinstance(row, Mapping) or set(row) != {"filename", "source"} for row in workspace
        ):
            raise F6TruthError("F-6 Oracle request workspace is malformed")
        rebuilt_request = build_oracle_request(
            oracle_request.get("source"),
            filename=oracle_request.get("filename"),
            execution_mode=oracle_request.get("execution_mode"),
            endpoint=oracle_request.get("endpoint"),
            workspace_sources={row["filename"]: row["source"] for row in workspace},
            revision=oracle_request.get("metis_revision"),
            tree=oracle_request.get("metis_tree"),
        )
        if dict(oracle_request) != rebuilt_request:
            raise F6TruthError("F-6 Oracle request is not canonical")
        if rebuilt_request["execution_mode"] != "endpoint":
            raise F6TruthError("F-6 requires an endpoint-mode Oracle request")
        if rebuilt_request["filename"] != source_path:
            raise F6TruthError("F-6 source path differs from the Oracle request")
        source = rebuilt_request["source"]
        if _git_blob_oid(source) != source_blob_oid:
            raise F6TruthError("F-6 source blob id differs from Oracle request bytes")
        verified = verify_oracle_envelope(oracle_envelope, request=rebuilt_request)
    except OracleError as error:
        raise F6TruthError(f"F-6 Oracle envelope is not verified: {error}") from error
    if not isinstance(verified, Mapping):
        raise F6TruthError("F-6 Oracle verifier returned a malformed envelope")
    result = verified.get("result")
    evidence = verified.get("evidence")
    if not isinstance(result, Mapping) or not isinstance(evidence, Mapping):
        raise F6TruthError("F-6 Oracle envelope omitted result/evidence")
    endpoint = result.get("endpoint")
    ast = result.get("ast")
    ir = result.get("ir")
    toolchain = result.get("toolchain")
    if (
        result.get("status") != "ok"
        or result.get("failure") is not None
        or not isinstance(endpoint, Mapping)
        or endpoint.get("count") != 1
        or type(endpoint.get("name")) is not str
        or not endpoint["name"]
        or endpoint.get("name") != rebuilt_request["endpoint"]
        or not isinstance(ast, Mapping)
        or not isinstance(ir, Mapping)
        or not isinstance(toolchain, Mapping)
        or toolchain.get("revision") != rebuilt_request["metis_revision"]
        or toolchain.get("tree") != rebuilt_request["metis_tree"]
        or ir.get("value") is None
        or ir.get("signature") is None
    ):
        raise F6TruthError("F-6 requires one successful endpoint-mode AST/IR result")
    if ast.get("signature") != evidence.get("ast_sha256"):
        raise F6TruthError("F-6 AST signature differs from verified envelope evidence")
    if ir.get("signature") != evidence.get("ir_sha256"):
        raise F6TruthError("F-6 IR signature differs from verified envelope evidence")
    claims = _claims(required_claims, "F-6 required claims")
    _assert_claims_grounded(claims, ast.get("inventory"), ir.get("value"))
    envelope_hash = evidence.get("envelope_sha256")
    body = {
        "schema_version": 1,
        "truth_id": f"f6-truth/{task_id}",
        "task_id": task_id,
        "family": "F-6",
        "status": "sealed_pre_output",
        "source": {
            "toolchain_revision": toolchain.get("revision"),
            "toolchain_tree": toolchain.get("tree"),
            "source_blob_oid": source_blob_oid,
            "source_sha256": _source_sha256(source),
            "source_path": source_path,
            "oracle_request_sha256": evidence.get("input_sha256"),
            "oracle_envelope_sha256": envelope_hash,
        },
        "oracle_evidence": {
            "endpoint_name": endpoint["name"],
            "ast_signature": ast.get("signature"),
            "ir_signature": ir.get("signature"),
            "ast_inventory_sha256": evidence.get("ast_sha256"),
            "ir_value_sha256": evidence.get("ir_sha256"),
        },
        "required_claims": claims,
        "human_review_required": True,
        "model_outputs_observed": False,
    }
    truth = {**body, "truth_sha256": _sha(body)}
    return validate_f6_truth(truth)


def _validate_candidate(value: Any, task_id: str) -> dict[str, Any]:
    try:
        raw = _exact_mapping(value, CANDIDATE_KEYS, "F-6 candidate")
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise F6CandidateError("F-6 candidate schema version is invalid")
        if raw["task_id"] != task_id:
            raise F6CandidateError("F-6 candidate task id differs from sealed truth")
        return {
            "schema_version": 1,
            "task_id": task_id,
            "ast_signature": _hash(raw["ast_signature"], "candidate AST signature"),
            "ir_signature": _hash(raw["ir_signature"], "candidate IR signature"),
            "claims": _claims(raw["claims"], "F-6 candidate claims"),
            "summary": _nonempty_string(raw["summary"], "F-6 candidate summary"),
        }
    except F6CandidateError:
        raise
    except F6StructuralError as error:
        raise F6CandidateError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - model output is untrusted
        raise F6CandidateError("F-6 candidate is malformed") from error


def evaluate_f6_structural_explanation(truth: Any, candidate: Any) -> dict[str, Any]:
    """Evaluate AST/IR grounding while retaining the mandatory human gap."""

    sealed = validate_f6_truth(truth)
    output = _validate_candidate(candidate, sealed["task_id"])
    oracle = sealed["oracle_evidence"]
    ast_ok = output["ast_signature"] == oracle["ast_signature"]
    ir_ok = output["ir_signature"] == oracle["ir_signature"]
    expected_claims = {item["claim_id"]: item for item in sealed["required_claims"]}
    actual_claims = {item["claim_id"]: item for item in output["claims"]}
    reasons: list[str] = []
    if not ast_ok:
        reasons.append("ast_signature_mismatch")
    if not ir_ok:
        reasons.append("ir_signature_mismatch")
    if set(actual_claims) != set(expected_claims):
        reasons.append("claim_roster_mismatch")
    for claim_id in sorted(set(actual_claims) & set(expected_claims)):
        if actual_claims[claim_id] != expected_claims[claim_id]:
            reasons.append(f"claim_mismatch:{claim_id}")
    claims_ok = not any(reason.startswith("claim_") for reason in reasons)
    semantic_ok = ast_ok and ir_ok and claims_ok
    status = "automatic_pass_human_pending" if semantic_ok else "automatic_fail"
    body = {
        "schema_version": 1,
        "task_id": sealed["task_id"],
        "status": status,
        "eligible_for_f6_credit": False,
        "outcomes": {
            "ast": "pass" if ast_ok else "fail",
            "ir": "pass" if ir_ok else "fail",
            "semantic": "pass" if semantic_ok else "fail",
            "human": "not_run",
        },
        "failure_reasons": reasons,
        "evidence": {
            "truth_sha256": sealed["truth_sha256"],
            "candidate_sha256": _sha(output),
            "oracle_envelope_sha256": sealed["source"]["oracle_envelope_sha256"],
        },
    }
    return validate_f6_auto_result(
        {**body, "result_sha256": _sha(body)}, truth=sealed, candidate=output
    )


def validate_f6_auto_result(
    value: Any,
    *,
    truth: Any | None = None,
    candidate: Any | None = None,
) -> dict[str, Any]:
    """Validate the self-hash, outcome coherence, and optional input bindings."""

    try:
        raw = _exact_mapping(value, RESULT_KEYS, "F-6 automatic result")
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise F6ResultError("F-6 automatic result schema version is invalid")
        task_id = _nonempty_string(raw["task_id"], "F-6 result task id", maximum=128)
        if ID_RE.fullmatch(task_id) is None:
            raise F6ResultError("F-6 result task id is invalid")
        if raw["eligible_for_f6_credit"] is not False:
            raise F6ResultError("automatic F-6 result cannot receive complete F-6 credit")
        outcomes = _exact_mapping(raw["outcomes"], OUTCOME_KEYS, "F-6 outcomes")
        if (
            outcomes["ast"] not in {"pass", "fail"}
            or outcomes["ir"] not in {"pass", "fail"}
            or outcomes["semantic"] not in {"pass", "fail"}
            or outcomes["human"] != "not_run"
        ):
            raise F6ResultError("F-6 automatic outcomes are outside the registry")
        reasons = raw["failure_reasons"]
        if not isinstance(reasons, list) or any(
            type(reason) is not str or FAILURE_REASON_RE.fullmatch(reason) is None
            for reason in reasons
        ):
            raise F6ResultError("F-6 automatic failure reasons are malformed")
        if len(reasons) != len(set(reasons)):
            raise F6ResultError("F-6 automatic failure reasons contain duplicates")
        ast_failed = "ast_signature_mismatch" in reasons
        ir_failed = "ir_signature_mismatch" in reasons
        claim_failed = any(reason.startswith("claim_") for reason in reasons)
        expected_outcomes = {
            "ast": "fail" if ast_failed else "pass",
            "ir": "fail" if ir_failed else "pass",
            "semantic": "fail" if ast_failed or ir_failed or claim_failed else "pass",
            "human": "not_run",
        }
        if dict(outcomes) != expected_outcomes:
            raise F6ResultError("F-6 automatic outcomes disagree with failure reasons")
        expected_status = (
            "automatic_pass_human_pending"
            if expected_outcomes["semantic"] == "pass"
            else "automatic_fail"
        )
        if raw["status"] != expected_status:
            raise F6ResultError("F-6 automatic status disagrees with its outcomes")
        evidence = _exact_mapping(raw["evidence"], RESULT_EVIDENCE_KEYS, "F-6 result evidence")
        normalized_evidence = {
            key: _hash(evidence[key], f"F-6 result evidence {key}")
            for key in sorted(RESULT_EVIDENCE_KEYS)
        }
        body = {
            "schema_version": 1,
            "task_id": task_id,
            "status": expected_status,
            "eligible_for_f6_credit": False,
            "outcomes": expected_outcomes,
            "failure_reasons": reasons,
            "evidence": normalized_evidence,
        }
        if raw["result_sha256"] != _sha(body):
            raise F6ResultError("F-6 automatic result hash does not match its canonical body")

        sealed = validate_f6_truth(truth) if truth is not None else None
        if sealed is not None and (
            sealed["task_id"] != task_id
            or sealed["truth_sha256"] != normalized_evidence["truth_sha256"]
            or sealed["source"]["oracle_envelope_sha256"]
            != normalized_evidence["oracle_envelope_sha256"]
        ):
            raise F6ResultError("F-6 automatic result differs from sealed truth")
        if candidate is not None:
            parsed_candidate = _validate_candidate(candidate, task_id)
            if _sha(parsed_candidate) != normalized_evidence["candidate_sha256"]:
                raise F6ResultError("F-6 automatic result differs from candidate output")
        return {**body, "result_sha256": raw["result_sha256"]}
    except F6ResultError:
        raise
    except F6StructuralError as error:
        raise F6ResultError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - result receipts are untrusted
        raise F6ResultError("F-6 automatic result is malformed") from error
