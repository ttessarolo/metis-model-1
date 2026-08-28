"""Structured Brain-side grounding over the local semantic index.

This adapter is deliberately not an agent runtime: request text is treated as
data, resolution is delegated to exact snapshot membership, and the public
receipt contains no request text, annotations, or chain-of-thought.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metis_model1.video_semantic_index import (
    HASH_RE,
    SemanticIndexError,
    _hash,
    resolve_grounding,
    validate_semantic_index,
)


def ground_request(
    index: Mapping[str, Any], request: str, *, catalog: str | None = None
) -> dict[str, Any]:
    """Return structured grounding and a sanitized, self-hashed receipt."""

    errors = validate_semantic_index(index)
    if errors:
        raise SemanticIndexError("invalid index: " + "; ".join(errors))
    result = resolve_grounding(index, request, catalog=catalog)
    grounding: dict[str, Any] = {
        "schema_version": 1,
        "grounding_id": "video-semantics/brain-grounding-v1",
        "index_revision": index["revision"],
        "request_sha256": _hash(request),
        "status": result["status"],
        "reason": result["reason"],
        "selected": result.get("selected"),
        "selections": result.get("selections", []),
        "candidates": result.get("candidates", []),
        "lookup": result.get("lookup"),
        "lookups": result.get("lookups", []),
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/brain-grounding-receipt-v1",
        "index_revision": index["revision"],
        "request_sha256": grounding["request_sha256"],
        "status": grounding["status"],
        "candidate_count": len(grounding["candidates"]),
        "selection_count": len(grounding["selections"]),
        "lookup_count": len(grounding["lookups"]),
        "lookup_mode": grounding["lookup"]["mode"] if grounding["lookup"] else None,
        "values_redacted": True,
        "reasoning_present": False,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    return {"grounding": grounding, "receipt": receipt}


def validate_grounding_receipt(receipt: Any) -> list[str]:
    """Validate receipt identity, redaction, and self-hash."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "receipt_id",
        "index_revision",
        "request_sha256",
        "status",
        "candidate_count",
        "selection_count",
        "lookup_count",
        "lookup_mode",
        "values_redacted",
        "reasoning_present",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed public contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/brain-grounding-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    forbidden = {"request", "means", "aka", "literal", "chain_of_thought", "model_output"}

    def contains_forbidden(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(key in forbidden or contains_forbidden(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    if contains_forbidden(receipt):
        errors.append("receipt contains unredacted request or reasoning material")
    if receipt.get("reasoning_present") is not False:
        errors.append("receipt reasoning marker is invalid")
    if receipt.get("values_redacted") is not True:
        errors.append("receipt values redaction marker is invalid")
    for key in ("index_revision", "request_sha256", "receipt_sha256"):
        value = receipt.get(key)
        if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
            errors.append(f"receipt {key} is invalid")
    if receipt.get("status") not in {"resolved", "clarify", "unsupported"}:
        errors.append("receipt status is invalid")
    for key in ("candidate_count", "selection_count", "lookup_count"):
        if type(receipt.get(key)) is not int or receipt[key] < 0:
            errors.append(f"receipt {key} is invalid")
    if receipt.get("lookup_mode") not in {None, "exact_on_demand"}:
        errors.append("receipt lookup mode is invalid")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


ground = ground_request


__all__ = ["ground", "ground_request", "validate_grounding_receipt"]
