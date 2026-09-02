"""Typed, single-turn bridge from reviewed grounding to compiler lossless edits.

The model never receives source spans, node identifiers, payload text, placement
or delete modes.  Brain issues opaque, role-typed references for one turn,
translates the admitted v2 EditPlan into the compiler contract, and independently
checks the lossless receipt before a Draft can be published.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from metis_model1.brain_bounded_edit import (
    _PREDICATE,
    _include_span,
    _selection_surface,
    _strict_predicate_lines,
)
from metis_model1.brain_candidate_grounding import (
    TakeContract,
    _endpoint_blocks,
    _scan_take_directive,
    _word_at,
    source_take_contract,
    take_contract,
)
from metis_model1.brain_edit_plan import EDIT_PLAN_CONTRACT, admit_edit_plan
from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_protocol import (
    MAX_SOURCE_BYTES,
    BrainError,
    bounded_source,
    bytes_sha256,
    canonical_sha256,
)

LOSSLESS_INVENTORY_CONTRACT = "metis-lossless-inventory/v1"
LOSSLESS_PLAN_CONTRACT = "metis-lossless-edit-plan/v1"
LOSSLESS_RECEIPT_CONTRACT = "metis-lossless-receipt/v1"
MAX_LOSSLESS_NODES = 8192
MAX_OPERATION_TEXT_UNITS = 65536
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NODE_RE = re.compile(r"^\$(?:/[A-Za-z_][A-Za-z0-9_]*(?:@[0-9]+)?)*$")
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
_REASON_CODES = frozenset(
    {
        "MALFORMED_PLAN",
        "OVERSIZED_TEXT",
        "STALE_SOURCE",
        "INVALID_UTF8",
        "BOM_PRESENT",
        "PARSE_ERROR",
        "PARSER_LIMIT",
        "CST_COVERAGE_GAP",
        "NODE_WITHOUT_CST",
        "UNKNOWN_NODE",
        "AMBIGUOUS_NODE",
        "PREIMAGE_MISMATCH",
        "LINE_NOT_OWNED",
        "OVERLAP",
        "RENDER_NOT_PARSEABLE",
        "RENDER_NOT_VALID",
        "BASELINE_NOT_CLEAN",
    }
)

RefRole = Literal["target", "base", "basis", "node", "slot", "delete", "payload"]


class LosslessInapplicable(ValueError):
    """The safe deterministic subset does not cover this edit."""


@dataclass(frozen=True, slots=True)
class HostRefRecord:
    """One server-owned opaque capability, valid only for one edit source."""

    ref: str
    role: RefRole
    relative_path: str
    context_revision: str
    workspace_base_revision: str
    edit_source_revision: str
    toolchain_binding: str
    node_id: str | None = None
    preimage_sha256: str | None = None
    payload: str | None = None
    payload_sha256: str | None = None
    placement: Literal["before", "after"] | None = None
    delete_mode: Literal["exact", "own-lines"] | None = None
    basis_proposal_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            _REF_RE.fullmatch(self.ref) is None
            or _PATH_RE.fullmatch(self.relative_path) is None
            or any(part in {"", ".", ".."} for part in self.relative_path.split("/"))
            or _HASH_RE.fullmatch(self.context_revision) is None
            or _HASH_RE.fullmatch(self.workspace_base_revision) is None
            or _HASH_RE.fullmatch(self.edit_source_revision) is None
            or _HASH_RE.fullmatch(self.toolchain_binding) is None
        ):
            raise BrainError("EDIT_PLAN_INVALID", 500, "host reference binding is invalid")
        node = self.node_id is not None or self.preimage_sha256 is not None
        payload = self.payload is not None or self.payload_sha256 is not None
        if self.role in {"target", "base"}:
            valid = not any(
                (
                    node,
                    payload,
                    self.placement is not None,
                    self.delete_mode is not None,
                    self.basis_proposal_ref is not None,
                )
            )
        elif self.role == "basis":
            valid = (
                not node
                and not payload
                and self.placement is None
                and self.delete_mode is None
                and isinstance(self.basis_proposal_ref, str)
                and bool(self.basis_proposal_ref)
            )
        elif self.role in {"node", "slot", "delete"}:
            role_options_are_exact = (
                (self.role == "node" and self.placement is None and self.delete_mode is None)
                or (
                    self.role == "slot"
                    and self.placement in {"before", "after"}
                    and self.delete_mode is None
                )
                or (
                    self.role == "delete"
                    and self.placement is None
                    and self.delete_mode in {"exact", "own-lines"}
                )
            )
            valid = (
                isinstance(self.node_id, str)
                and _NODE_RE.fullmatch(self.node_id) is not None
                and isinstance(self.preimage_sha256, str)
                and _HASH_RE.fullmatch(self.preimage_sha256) is not None
                and not payload
                and self.basis_proposal_ref is None
                and role_options_are_exact
            )
        elif self.role == "payload":
            try:
                payload_units = (
                    len(self.payload.encode("utf-16-le")) // 2
                    if isinstance(self.payload, str)
                    else -1
                )
            except UnicodeEncodeError:
                payload_units = -1
            valid = (
                not node
                and isinstance(self.payload, str)
                and 0 <= payload_units <= MAX_OPERATION_TEXT_UNITS
                and self.payload_sha256 == bytes_sha256(self.payload.encode("utf-8"))
                and self.placement is None
                and self.delete_mode is None
                and self.basis_proposal_ref is None
            )
        else:
            valid = False
        if not valid:
            raise BrainError("EDIT_PLAN_INVALID", 500, "host reference role is invalid")


class HostRefRegistry:
    """Single-use translator; raw authority never crosses the model boundary."""

    def __init__(
        self,
        *,
        records: Sequence[HostRefRecord],
        target_ref: str,
        base_ref: str,
        basis_ref: str | None,
    ) -> None:
        self._records = {record.ref: record for record in records}
        if len(self._records) != len(records):
            raise BrainError("EDIT_PLAN_INVALID", 500, "host references are not distinct")
        self.target_ref = target_ref
        self.base_ref = base_ref
        self.basis_ref = basis_ref
        if (
            self._role(target_ref, "target") is None
            or self._role(base_ref, "base") is None
            or (basis_ref is not None and self._role(basis_ref, "basis") is None)
        ):
            raise BrainError("EDIT_PLAN_INVALID", 500, "host reference roots are invalid")
        target = self._records[target_ref]
        if any(
            record.relative_path != target.relative_path
            or record.context_revision != target.context_revision
            or record.workspace_base_revision != target.workspace_base_revision
            or record.edit_source_revision != target.edit_source_revision
            or record.toolchain_binding != target.toolchain_binding
            for record in records
        ):
            raise BrainError("EDIT_PLAN_INVALID", 500, "host reference binding drifted")
        self._consumed = False

    @property
    def issued_refs(self) -> frozenset[str]:
        return frozenset(self._records)

    def _role(self, ref: str, role: RefRole) -> HostRefRecord | None:
        record = self._records.get(ref)
        return record if record is not None and record.role == role else None

    def translate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if self._consumed:
            raise BrainError("EDIT_PLAN_STALE", 409, "host references were already consumed")
        self._consumed = True
        target = self._records[self.target_ref]
        admitted = admit_edit_plan(
            value,
            issued_refs=self._records,
            expected_context_revision=target.context_revision,
            expected_workspace_base_revision=target.workspace_base_revision,
            expected_edit_source_revision=target.edit_source_revision,
            expected_basis_ref=self.basis_ref,
        )
        if (
            admitted["target_ref"] != self.target_ref
            or admitted["base_ref"] != self.base_ref
            or admitted["basis_ref"] != self.basis_ref
        ):
            raise BrainError("EDIT_PLAN_INVALID", 502, "EditPlan roots differ from host authority")
        translated: list[dict[str, Any]] = []
        for operation in admitted["operations"]:
            kind = operation["kind"]
            if kind == "replace":
                node = self._role(operation["node_ref"], "node")
                payload = self._role(operation["payload_ref"], "payload")
                if node is None or payload is None:
                    raise BrainError(
                        "EDIT_PLAN_INVALID",
                        502,
                        "replace host reference role differs",
                    )
                translated.append(
                    {
                        "kind": "replace",
                        "ordinal": operation["ordinal"],
                        "targetId": node.node_id,
                        "preimageSha256": node.preimage_sha256,
                        "text": payload.payload,
                    }
                )
            elif kind == "insert":
                slot = self._role(operation["slot_ref"], "slot")
                payload = self._role(operation["payload_ref"], "payload")
                if slot is None or payload is None:
                    raise BrainError("EDIT_PLAN_INVALID", 502, "insert host reference role differs")
                translated.append(
                    {
                        "kind": "insert",
                        "ordinal": operation["ordinal"],
                        "anchorId": slot.node_id,
                        "placement": slot.placement,
                        "text": payload.payload,
                    }
                )
            else:
                delete = self._role(operation["delete_ref"], "delete")
                if delete is None:
                    raise BrainError("EDIT_PLAN_INVALID", 502, "delete host reference role differs")
                translated.append(
                    {
                        "kind": "delete",
                        "ordinal": operation["ordinal"],
                        "targetId": delete.node_id,
                        "preimageSha256": delete.preimage_sha256,
                        "mode": delete.delete_mode,
                    }
                )
        return {
            "contract": LOSSLESS_PLAN_CONTRACT,
            "baseSha256": target.edit_source_revision,
            "operations": translated,
        }


@dataclass(frozen=True, slots=True)
class LosslessRenderResult:
    candidate: ModelCandidate
    proof: dict[str, Any] | None


def _opaque_ref() -> str:
    return "hostref:" + secrets.token_hex(20)


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _span(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "offset",
        "end",
        "byteOffset",
        "byteEnd",
    }:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless span is invalid")
    result = dict(value)
    if any(type(result[key]) is not int or result[key] < 0 for key in result):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless span is invalid")
    if result["end"] < result["offset"] or result["byteEnd"] < result["byteOffset"]:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless span is reversed")
    return result


def _source_boundaries(source: str) -> dict[int, int]:
    utf16 = 0
    byte = 0
    result = {0: 0}
    for character in source:
        utf16 += len(character.encode("utf-16-le")) // 2
        byte += len(character.encode("utf-8"))
        result[utf16] = byte
    return result


def _validate_inventory(
    envelope: Any,
    *,
    source: str,
    relative_path: str,
    endpoint: str,
    expected_toolchain: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    expected_envelope = {
        "schema_version",
        "operation",
        "status",
        "relative_path",
        "endpoint",
        "inventory",
        "target",
        "reasons",
    }
    if not isinstance(envelope, Mapping) or set(envelope) != expected_envelope:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory envelope is invalid")
    if (
        envelope.get("schema_version") != 1
        or envelope.get("operation") != "lossless-inventory"
        or envelope.get("relative_path") != relative_path
        or envelope.get("endpoint") != endpoint
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory identity differs")
    if envelope.get("status") == "rejected":
        reasons = envelope.get("reasons")
        if (
            envelope.get("inventory") is not None
            or envelope.get("target") is not None
            or not isinstance(reasons, list)
            or not 1 <= len(reasons) <= 32
            or any(
                not isinstance(item, Mapping)
                or set(item) not in ({"code", "message"}, {"code", "message", "ordinal"})
                or item.get("code") not in _REASON_CODES
                or not isinstance(item.get("message"), str)
                or not 1 <= len(item["message"]) <= 4096
                or (
                    "ordinal" in item
                    and (type(item["ordinal"]) is not int or not 0 <= item["ordinal"] < 32)
                )
                for item in reasons
            )
        ):
            raise BrainError(
                "LOSSLESS_INVALID",
                503,
                "rejected lossless inventory is invalid",
            )
        raise LosslessInapplicable("compiler inventory did not admit the target")
    if envelope.get("status") != "ok" or envelope.get("reasons") != []:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory status is invalid")
    inventory = envelope["inventory"]
    target = envelope["target"]
    if (
        not isinstance(inventory, Mapping)
        or set(inventory) != {"contract", "sourceSha256", "toolchain", "nodes"}
        or inventory.get("contract") != LOSSLESS_INVENTORY_CONTRACT
        or inventory.get("sourceSha256") != bytes_sha256(source.encode("utf-8"))
        or not isinstance(inventory.get("toolchain"), Mapping)
        or set(inventory["toolchain"])
        != {"toolingVersion", "langiumVersion", "metisLanguageVersion", "grammarSha256"}
        or any(
            not isinstance(inventory["toolchain"].get(key), str)
            for key in ("toolingVersion", "langiumVersion", "metisLanguageVersion")
        )
        or _HASH_RE.fullmatch(str(inventory["toolchain"].get("grammarSha256"))) is None
        or dict(inventory["toolchain"]) != dict(expected_toolchain)
        or not isinstance(inventory.get("nodes"), list)
        or not 1 <= len(inventory["nodes"]) <= MAX_LOSSLESS_NODES
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory is invalid")
    raw = source.encode("utf-8")
    boundaries = _source_boundaries(source)
    nodes: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(inventory["nodes"]):
        parent = item.get("parent") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or set(item) != {"id", "type", "span", "preimageSha256", "parent"}
            or not isinstance(item.get("id"), str)
            or _NODE_RE.fullmatch(item["id"]) is None
            or item["id"] in nodes
            or not isinstance(item.get("type"), str)
            or not item["type"]
            or _HASH_RE.fullmatch(str(item.get("preimageSha256"))) is None
            or (index == 0) != (parent is None)
            or (
                parent is not None
                and (
                    not isinstance(parent, str)
                    or _NODE_RE.fullmatch(parent) is None
                    or parent not in nodes
                )
            )
        ):
            raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory node is invalid")
        span = _span(item["span"])
        if (
            span["offset"] not in boundaries
            or span["end"] not in boundaries
            or boundaries[span["offset"]] != span["byteOffset"]
            or boundaries[span["end"]] != span["byteEnd"]
            or span["byteEnd"] > len(raw)
            or _sha(raw[span["byteOffset"] : span["byteEnd"]]) != item["preimageSha256"]
        ):
            raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory span is invalid")
        nodes[item["id"]] = {**dict(item), "span": span}
    if list(nodes)[0] != "$" or nodes["$"]["type"] != "Model":
        raise BrainError("LOSSLESS_INVALID", 503, "lossless inventory root is invalid")
    expected_target = {
        "endpoint_node_id",
        "take_node_id",
        "take_preimage_sha256",
        "take_span",
        "take_shape",
        "include_node_id",
        "include_preimage_sha256",
        "include_span",
    }
    if not isinstance(target, Mapping) or set(target) != expected_target:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless target projection is invalid")
    target_types = (
        ("endpoint", "Endpoint"),
        ("take", "Take"),
        ("include", "IncludeClause"),
    )
    for prefix, expected_type in target_types:
        node_id = target[f"{prefix}_node_id"]
        if not isinstance(node_id, str) or _NODE_RE.fullmatch(node_id) is None:
            raise BrainError("LOSSLESS_INVALID", 503, "lossless target node is invalid")
        node = nodes.get(node_id)
        if node is None or node["type"] != expected_type:
            raise BrainError("LOSSLESS_INVALID", 503, "lossless target node is invalid")
        if prefix != "endpoint" and (
            target[f"{prefix}_preimage_sha256"] != node["preimageSha256"]
            or _span(target[f"{prefix}_span"]) != node["span"]
        ):
            raise BrainError("LOSSLESS_INVALID", 503, "lossless target binding differs")
    endpoint_node = nodes[target["endpoint_node_id"]]
    take_node = nodes[target["take_node_id"]]
    include_node = nodes[target["include_node_id"]]
    if take_node["parent"] != endpoint_node["id"] or include_node["parent"] != take_node["id"]:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless target ancestry differs")

    def contains(parent: Mapping[str, int], child: Mapping[str, int]) -> bool:
        return (
            parent["offset"] <= child["offset"] <= child["end"] <= parent["end"]
            and parent["byteOffset"] <= child["byteOffset"] <= child["byteEnd"] <= parent["byteEnd"]
        )

    root_span = nodes["$"]["span"]
    endpoint_span = endpoint_node["span"]
    take_span = take_node["span"]
    include_span = include_node["span"]
    try:
        endpoint_blocks = [item for item in _endpoint_blocks(source) if item[0] == endpoint]
    except Exception as error:
        raise BrainError(
            "LOSSLESS_INVALID",
            503,
            "requested endpoint surface is invalid",
        ) from error
    if len(endpoint_blocks) != 1:
        raise BrainError("LOSSLESS_INVALID", 503, "requested endpoint is not unique")
    _, body_start, body_end = endpoint_blocks[0]
    body_span = {
        "offset": len(source[:body_start].encode("utf-16-le")) // 2,
        "end": len(source[:body_end].encode("utf-16-le")) // 2,
        "byteOffset": len(source[:body_start].encode("utf-8")),
        "byteEnd": len(source[:body_end].encode("utf-8")),
    }
    if not (
        contains(root_span, endpoint_span)
        and contains(endpoint_span, body_span)
        and contains(body_span, take_span)
        and contains(take_span, include_span)
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless target spans are not nested")
    take_shape = target["take_shape"]
    if (
        not isinstance(take_shape, Mapping)
        or set(take_shape) != {"mode", "value"}
        or take_shape.get("mode") not in {"count", "page"}
        or (
            take_shape.get("value") is not None
            and (type(take_shape["value"]) is not int or take_shape["value"] <= 0)
        )
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless take shape is invalid")
    current_take = source_take_contract(source, endpoint)
    expected_shape = (
        {"mode": "count", "value": current_take.value}
        if current_take is not None and current_take.mode == "count"
        else {
            "mode": "page",
            "value": current_take.value if current_take is not None else None,
        }
    )
    if current_take is None or dict(take_shape) != expected_shape:
        raise BrainError("LOSSLESS_INVALID", 503, "lossless take shape differs from source")
    return dict(inventory), dict(target), nodes


def _take_surface(value: TakeContract) -> str:
    if value.mode == "count" and value.value is not None:
        return str(value.value)
    if value.mode == "page":
        return "page" if value.value is None else f"page default {value.value}"
    raise LosslessInapplicable("output cardinality is not deterministic")


def _rewrite_include(text: str, predicates: Sequence[str]) -> str:
    include = _include_span(text, 0, len(text))
    if include is None or not predicates or "//" in text or "/*" in text or "*/" in text:
        raise LosslessInapplicable("include clause is outside the deterministic subset")
    start, end = include
    body = text[start:end]
    if "\r\n" in body:
        if "\n" in body.replace("\r\n", ""):
            raise LosslessInapplicable("include clause mixes line endings")
        newline = "\r\n"
    elif "\n" in body:
        newline = "\n"
    else:
        raise LosslessInapplicable("single-line include clause is not rewritten")
    closing_indent = body.rsplit(newline, 1)[-1]
    if not closing_indent.isspace() and closing_indent != "":
        raise LosslessInapplicable("include closing trivia is not whitespace")
    indentation: str | None = None
    for line in body.splitlines():
        if line.strip() and not line.lstrip().startswith(("//", "/*", "*")):
            indentation = line[: len(line) - len(line.lstrip())]
            break
    indentation = indentation if indentation is not None else closing_indent + "  "
    replacement = newline + newline.join(f"{indentation}{item}" for item in predicates)
    replacement += newline + closing_indent
    return text[:start] + replacement + text[end:]


def _rewrite_take_header(text: str, expected: TakeContract) -> str:
    if not text.startswith("take"):
        raise LosslessInapplicable("take node does not start at its keyword")
    start = len("take")
    while start < len(text) and text[start].isspace():
        start += 1
    directive, end = _scan_take_directive(text, len("take"))
    if directive is None:
        raise LosslessInapplicable("take cardinality is not recognized")
    cursor = end
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if not _word_at(text, cursor, "from"):
        raise LosslessInapplicable("take cardinality is not followed by from")
    return text[:start] + _take_surface(expected) + text[end:]


def _predicate_fields(body: str) -> tuple[str, ...] | None:
    """Return the exact finite fields of one conservative include body."""

    if not _strict_predicate_lines(body):
        return None
    fields: list[str] = []
    for line in (item.strip() for item in body.splitlines() if item.strip()):
        match = _PREDICATE.fullmatch(line)
        if match is None:
            return None
        fields.append(match.group(1))
    if len(fields) != len(set(fields)):
        return None
    return tuple(fields)


def _without_line_comments(body: str) -> str | None:
    """Remove only lexical line comments without interpreting string content."""

    if "/*" in body or "*/" in body:
        return None
    normalized: list[str] = []
    for line in body.splitlines():
        escaped = False
        quoted = False
        end = len(line)
        for index, character in enumerate(line):
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
                continue
            if character == '"':
                quoted = True
            elif character == "/" and index + 1 < len(line) and line[index + 1] == "/":
                end = index
                break
        if quoted or escaped:
            return None
        normalized.append(line[:end])
    return "\n".join(normalized)


def _desired_edit(
    *,
    source: str,
    endpoint: str,
    grounding: Mapping[str, Any],
    target: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[str, Mapping[str, Any], str]:
    selections = grounding.get("selections")
    if not isinstance(selections, list) or not selections:
        raise LosslessInapplicable("there are no reviewed finite selections")
    selection_refs = [item.get("selection_ref") for item in selections if isinstance(item, Mapping)]
    if len(selection_refs) != len(selections) or any(
        not isinstance(item, str) for item in selection_refs
    ):
        raise LosslessInapplicable("selection references are unavailable")
    surface = _selection_surface(selection_refs, grounding)
    if surface is None:
        raise LosslessInapplicable("reviewed finite grounding cannot be rendered")
    predicates = [line.strip() for line in surface.splitlines() if line.strip()]
    expected_take = take_contract(grounding)
    current_take = source_take_contract(source, endpoint)
    if expected_take is None or current_take is None:
        raise LosslessInapplicable("take contract is unavailable")
    raw = source.encode("utf-8")
    cardinality_changes = expected_take != current_take
    prefix = "take" if cardinality_changes else "include"
    node = nodes[target[f"{prefix}_node_id"]]
    span = node["span"]
    original = raw[span["byteOffset"] : span["byteEnd"]].decode("utf-8")
    include = _include_span(original, 0, len(original))
    if include is None:
        raise LosslessInapplicable("include clause is outside the deterministic subset")
    existing_body = original[include[0] : include[1]]
    existing_fields = _predicate_fields(existing_body)
    desired_fields = _predicate_fields("\n".join(predicates))
    uncommented = _without_line_comments(existing_body)
    preservation_fields = (
        ()
        if uncommented is not None and not uncommented.strip()
        else _predicate_fields(uncommented)
        if uncommented is not None
        else None
    )
    if preservation_fields is None:
        raise BrainError(
            "EDIT_PRESERVATION_CONFLICT",
            409,
            "existing predicate surface cannot be proven safe for model fallback",
        )
    if desired_fields is not None and frozenset(preservation_fields) - frozenset(desired_fields):
        raise BrainError(
            "EDIT_PRESERVATION_CONFLICT",
            409,
            "existing finite predicates require explicit preservation authority",
        )
    if (
        existing_fields is None
        or desired_fields is None
        or frozenset(existing_fields) != frozenset(desired_fields)
    ):
        raise LosslessInapplicable(
            "existing endpoint predicates are not exactly the grounded selection fields"
        )
    payload = _rewrite_include(original, predicates)
    if cardinality_changes:
        payload = _rewrite_take_header(payload, expected_take)
    rendered = raw[: span["byteOffset"]] + payload.encode("utf-8") + raw[span["byteEnd"] :]
    return rendered.decode("utf-8"), node, payload


def _record(
    *,
    role: RefRole,
    relative_path: str,
    context_revision: str,
    workspace_base_revision: str,
    edit_source_revision: str,
    toolchain_binding: str,
    **kwargs: Any,
) -> HostRefRecord:
    return HostRefRecord(
        ref=_opaque_ref(),
        role=role,
        relative_path=relative_path,
        context_revision=context_revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=toolchain_binding,
        **kwargs,
    )


def _replace_plan(
    *,
    relative_path: str,
    context_revision: str,
    workspace_base_revision: str,
    edit_source_revision: str,
    toolchain_binding: str,
    node: Mapping[str, Any],
    payload: str,
    basis_proposal_ref: str | None,
) -> tuple[HostRefRegistry, dict[str, Any]]:
    target = _record(
        role="target",
        relative_path=relative_path,
        context_revision=context_revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=toolchain_binding,
    )
    base = _record(
        role="base",
        relative_path=relative_path,
        context_revision=context_revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=toolchain_binding,
    )
    basis = (
        _record(
            role="basis",
            relative_path=relative_path,
            context_revision=context_revision,
            workspace_base_revision=workspace_base_revision,
            edit_source_revision=edit_source_revision,
            toolchain_binding=toolchain_binding,
            basis_proposal_ref=basis_proposal_ref,
        )
        if basis_proposal_ref is not None
        else None
    )
    node_record = _record(
        role="node",
        relative_path=relative_path,
        context_revision=context_revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=toolchain_binding,
        node_id=node["id"],
        preimage_sha256=node["preimageSha256"],
    )
    payload_record = _record(
        role="payload",
        relative_path=relative_path,
        context_revision=context_revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=toolchain_binding,
        payload=payload,
        payload_sha256=bytes_sha256(payload.encode("utf-8")),
    )
    records = [target, base, node_record, payload_record]
    if basis is not None:
        records.append(basis)
    registry = HostRefRegistry(
        records=records,
        target_ref=target.ref,
        base_ref=base.ref,
        basis_ref=basis.ref if basis is not None else None,
    )
    plan = {
        "schema_version": 2,
        "contract_id": EDIT_PLAN_CONTRACT,
        "context_revision": context_revision,
        "workspace_base_revision": workspace_base_revision,
        "edit_source_revision": edit_source_revision,
        "target_ref": target.ref,
        "base_ref": base.ref,
        "basis_ref": basis.ref if basis is not None else None,
        "operations": [
            {
                "ordinal": 0,
                "kind": "replace",
                "node_ref": node_record.ref,
                "payload_ref": payload_record.ref,
            }
        ],
    }
    return registry, plan


def _validate_apply_receipt(
    envelope: Any,
    *,
    original: str,
    expected_rendered: str,
    relative_path: str,
    endpoint: str,
    compiler_plan: Mapping[str, Any],
    inventory_toolchain: Mapping[str, Any],
    target_node: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(envelope, Mapping)
        or set(envelope)
        != {
            "schema_version",
            "operation",
            "status",
            "relative_path",
            "endpoint",
            "proof_mode",
            "receipt",
        }
        or envelope.get("schema_version") != 1
        or envelope.get("operation") != "lossless-apply"
        or envelope.get("status") != "ok"
        or envelope.get("relative_path") != relative_path
        or envelope.get("endpoint") != endpoint
        or envelope.get("proof_mode") != "validate"
    ):
        raise BrainError("LOSSLESS_REJECTED", 422, "compiler lossless edit was rejected")
    receipt = envelope["receipt"]
    if (
        not isinstance(receipt, Mapping)
        or set(receipt)
        != {
            "contract",
            "outcome",
            "toolchain",
            "shaBefore",
            "shaAfter",
            "touchedSpans",
            "diagnostics",
            "reasons",
            "renderedText",
        }
        or receipt.get("contract") != LOSSLESS_RECEIPT_CONTRACT
        or receipt.get("outcome") != "APPLIED"
        or receipt.get("toolchain") != inventory_toolchain
        or receipt.get("shaBefore") != compiler_plan["baseSha256"]
        or receipt.get("reasons") != []
        or receipt.get("diagnostics") != []
        or not isinstance(receipt.get("renderedText"), str)
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "compiler lossless receipt is invalid")
    rendered = bounded_source(receipt["renderedText"])
    rendered_raw = rendered.encode("utf-8")
    original_raw = original.encode("utf-8")
    if (
        len(rendered_raw) > MAX_SOURCE_BYTES
        or receipt.get("shaAfter") != bytes_sha256(rendered_raw)
        or rendered != expected_rendered
        or not isinstance(receipt.get("touchedSpans"), list)
        or len(receipt["touchedSpans"]) != 1
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "compiler lossless output differs")
    touched = receipt["touchedSpans"][0]
    expected_span = target_node["span"]
    operation = compiler_plan["operations"][0]
    if (
        not isinstance(touched, Mapping)
        or set(touched) != {"ordinal", "kind", "targetId", "before", "afterByteLength"}
        or type(touched.get("ordinal")) is not int
        or touched.get("ordinal") != 0
        or touched.get("kind") != "replace"
        or not isinstance(touched.get("targetId"), str)
        or touched.get("targetId") != operation["targetId"]
        or _span(touched.get("before")) != expected_span
        or type(touched.get("afterByteLength")) is not int
        or touched.get("afterByteLength") != len(operation["text"].encode("utf-8"))
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "compiler touched span differs")
    start = expected_span["byteOffset"]
    end = expected_span["byteEnd"]
    after_end = start + touched["afterByteLength"]
    if (
        original_raw[:start] != rendered_raw[:start]
        or original_raw[end:] != rendered_raw[after_end:]
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "untouched source bytes differ")
    return {
        "contract": LOSSLESS_RECEIPT_CONTRACT,
        "proof_mode": "validate",
        "receipt_sha256": canonical_sha256(dict(receipt)),
        "sha_before": receipt["shaBefore"],
        "sha_after": receipt["shaAfter"],
        "touched_count": 1,
    }


def render_lossless_existing(
    *,
    compiler: Any,
    lease: Any,
    request: Any,
    grounding: Mapping[str, Any],
    source: str | None,
) -> LosslessRenderResult | None:
    """Return one compiler-proven deterministic existing-endpoint edit, or decline."""

    target = request.target
    endpoint = target.get("endpoint")
    if (
        target.get("mode") != "existing"
        or not isinstance(endpoint, str)
        or source is None
        or grounding.get("status") != "resolved"
        or grounding.get("output_contract", {}).get("fallback") != {"mode": "none"}
        or not callable(getattr(compiler, "lossless_inventory", None))
        or not callable(getattr(compiler, "lossless_apply", None))
    ):
        return None
    source = bounded_source(source)
    edit_source_revision = bytes_sha256(source.encode("utf-8"))
    workspace_base_revision = target.get("base_sha256")
    if not isinstance(workspace_base_revision, str):
        return None
    expected_toolchain = getattr(compiler, "lossless_toolchain_identity", None)
    if not isinstance(expected_toolchain, Mapping):
        raise BrainError("LOSSLESS_INVALID", 503, "lossless toolchain identity is unavailable")
    try:
        envelope = compiler.lossless_inventory(
            lease=lease,
            source=source,
            filename=target["relative_path"],
            endpoint=endpoint,
        )
        inventory, target_projection, nodes = _validate_inventory(
            envelope,
            source=source,
            relative_path=target["relative_path"],
            endpoint=endpoint,
            expected_toolchain=expected_toolchain,
        )
        desired, node, payload = _desired_edit(
            source=source,
            endpoint=endpoint,
            grounding=grounding,
            target=target_projection,
            nodes=nodes,
        )
    except LosslessInapplicable:
        return None
    if desired == source:
        return LosslessRenderResult(
            ModelCandidate(source, "not_used", "not_used", "lossless_renderer"),
            None,
        )
    basis_proposal_ref = (
        request.basis.get("proposal_ref") if isinstance(request.basis, Mapping) else None
    )
    registry, host_plan = _replace_plan(
        relative_path=target["relative_path"],
        context_revision=lease.snapshot.revision,
        workspace_base_revision=workspace_base_revision,
        edit_source_revision=edit_source_revision,
        toolchain_binding=lease.snapshot.toolchain_binding,
        node=node,
        payload=payload,
        basis_proposal_ref=basis_proposal_ref,
    )
    compiler_plan = registry.translate(host_plan)
    response = compiler.lossless_apply(
        lease=lease,
        source=source,
        filename=target["relative_path"],
        endpoint=endpoint,
        plan=compiler_plan,
    )
    proof = _validate_apply_receipt(
        response,
        original=source,
        expected_rendered=desired,
        relative_path=target["relative_path"],
        endpoint=endpoint,
        compiler_plan=compiler_plan,
        inventory_toolchain=inventory["toolchain"],
        target_node=node,
    )
    return LosslessRenderResult(
        ModelCandidate(desired, "not_used", "not_used", "lossless_renderer"),
        proof,
    )


__all__ = [
    "HostRefRecord",
    "HostRefRegistry",
    "LosslessRenderResult",
    "render_lossless_existing",
]
