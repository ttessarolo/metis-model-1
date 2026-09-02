from __future__ import annotations

import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from metis_model1.brain_edit_plan import EDIT_PLAN_CONTRACT
from metis_model1.brain_lossless_edit import (
    HostRefRecord,
    HostRefRegistry,
    LosslessInapplicable,
    _validate_inventory,
    render_lossless_existing,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
PATH = "properties/demo/test.metis"
ENDPOINT = "demo.test"
TOOLCHAIN = {
    "toolingVersion": "0.23.97",
    "langiumVersion": "4.3.0",
    "metisLanguageVersion": "0.43",
    "grammarSha256": "sha256:" + "d" * 64,
}
SOURCE = """endpoint demo.test {
  take 20 from @play-demo.video {
    include where {
      @tipologia is \"Serie\"
    }
    order by @publication_date descending
    return response.expanded
  }
}
"""


def _sha(raw: bytes) -> str:
    return bytes_sha256(raw)


def _offsets(source: str, start: int, end: int) -> dict[str, int]:
    prefix = source[:start]
    body = source[start:end]
    return {
        "offset": len(prefix.encode("utf-16-le")) // 2,
        "end": len((prefix + body).encode("utf-16-le")) // 2,
        "byteOffset": len(prefix.encode("utf-8")),
        "byteEnd": len((prefix + body).encode("utf-8")),
    }


def _node(source: str, *, node_id: str, kind: str, start: int, end: int, parent: str | None):
    span = _offsets(source, start, end)
    raw = source.encode("utf-8")[span["byteOffset"] : span["byteEnd"]]
    return {
        "id": node_id,
        "type": kind,
        "span": span,
        "preimageSha256": _sha(raw),
        "parent": parent,
    }


def _inventory(source: str = SOURCE, *, projected_endpoint: str = ENDPOINT) -> dict[str, object]:
    newline = "\r\n" if "\r\n" in source else "\n"
    endpoint_start = source.index(f"endpoint {projected_endpoint}")
    endpoint_end = source.index(f"{newline}}}{newline}", endpoint_start) + len(f"{newline}}}")
    take_start = source.index("take", endpoint_start, endpoint_end)
    take_end = source.index(f"{newline}  }}", take_start, endpoint_end) + len(f"{newline}  }}")
    include_start = source.index("include", take_start, take_end)
    include_end = source.index(f"{newline}    }}", include_start) + len(f"{newline}    }}")
    endpoint_id = "$/elements@0"
    take_id = "$/elements@0/members@0"
    include_id = "$/elements@0/members@0/clauses@0"
    nodes = [
        _node(source, node_id="$", kind="Model", start=0, end=len(source), parent=None),
        _node(
            source,
            node_id=endpoint_id,
            kind="Endpoint",
            start=endpoint_start,
            end=endpoint_end,
            parent="$",
        ),
        _node(
            source,
            node_id=take_id,
            kind="Take",
            start=take_start,
            end=take_end,
            parent=endpoint_id,
        ),
        _node(
            source,
            node_id=include_id,
            kind="IncludeClause",
            start=include_start,
            end=include_end,
            parent=take_id,
        ),
    ]
    return {
        "schema_version": 1,
        "operation": "lossless-inventory",
        "status": "ok",
        "relative_path": PATH,
        "endpoint": ENDPOINT,
        "inventory": {
            "contract": "metis-lossless-inventory/v1",
            "sourceSha256": _sha(source.encode()),
            "toolchain": dict(TOOLCHAIN),
            "nodes": nodes,
        },
        "target": {
            "endpoint_node_id": endpoint_id,
            "take_node_id": take_id,
            "take_preimage_sha256": nodes[2]["preimageSha256"],
            "take_span": nodes[2]["span"],
            "take_shape": {"mode": "count", "value": 20},
            "include_node_id": include_id,
            "include_preimage_sha256": nodes[3]["preimageSha256"],
            "include_span": nodes[3]["span"],
        },
        "reasons": [],
    }


def _grounding(literal: str = "Film") -> dict[str, object]:
    value_ref = "value:tipologia-selected"
    return {
        "status": "resolved",
        "catalogs": ["play-demo.video"],
        "selections": [
            {
                "selection_ref": "selection:tipologia",
                "field_ref": "field:tipologia",
                "value_refs": [value_ref],
            }
        ],
        "refs": {
            "fields": {
                "field:tipologia": {
                    "name": "tipologia",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "enum"},
                }
            },
            "values": {
                value_ref: {
                    "literal": literal,
                    "field_ref": "field:tipologia",
                    "state": "reviewed",
                }
            },
        },
        "output_contract": {
            "take": {"mode": "count", "value": 20, "source": "operator_confirmed"},
            "fallback": {"mode": "none"},
        },
        "candidates": [],
        "unresolved": [],
    }


class _Compiler:
    lossless_toolchain_identity = TOOLCHAIN

    def __init__(self, inventory: dict[str, object] | None = None) -> None:
        self.inventory = inventory or _inventory()
        self.plans: list[dict[str, object]] = []

    def lossless_inventory(self, **_kwargs: object) -> dict[str, object]:
        return deepcopy(self.inventory)

    def lossless_apply(self, *, source: str, plan: dict[str, object], **_kwargs: object):
        self.plans.append(deepcopy(plan))
        operation = plan["operations"][0]
        assert isinstance(operation, dict)
        node_id = operation["targetId"]
        node = next(item for item in self.inventory["inventory"]["nodes"] if item["id"] == node_id)
        span = node["span"]
        original = source.encode()
        replacement = operation["text"].encode()
        rendered = original[: span["byteOffset"]] + replacement + original[span["byteEnd"] :]
        receipt = {
            "contract": "metis-lossless-receipt/v1",
            "outcome": "APPLIED",
            "toolchain": dict(TOOLCHAIN),
            "shaBefore": plan["baseSha256"],
            "shaAfter": _sha(rendered),
            "touchedSpans": [
                {
                    "ordinal": 0,
                    "kind": "replace",
                    "targetId": node_id,
                    "before": span,
                    "afterByteLength": len(replacement),
                }
            ],
            "diagnostics": [],
            "reasons": [],
            "renderedText": rendered.decode(),
        }
        return {
            "schema_version": 1,
            "operation": "lossless-apply",
            "status": "ok",
            "relative_path": PATH,
            "endpoint": ENDPOINT,
            "proof_mode": "validate",
            "receipt": receipt,
        }


def _request(source: str = SOURCE):
    return SimpleNamespace(
        target={
            "mode": "existing",
            "relative_path": PATH,
            "endpoint": ENDPOINT,
            "base_sha256": _sha(source.encode()),
        },
        basis=None,
    )


def _lease():
    return SimpleNamespace(
        snapshot=SimpleNamespace(revision=HASH_A, toolchain_binding=HASH_B),
        cancellation=threading.Event(),
    )


def test_reviewed_existing_edit_is_compiler_proven_and_public_proof_is_redacted() -> None:
    compiler = _Compiler()
    result = render_lossless_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request(),
        grounding=_grounding(),
        source=SOURCE,
    )

    assert result is not None
    assert result.candidate.generator == "lossless_renderer"
    assert '@tipologia is "Film"' in result.candidate.source
    assert '@tipologia is "Serie"' not in result.candidate.source
    assert result.proof is not None
    assert set(result.proof) == {
        "contract",
        "proof_mode",
        "receipt_sha256",
        "sha_before",
        "sha_after",
        "touched_count",
    }
    assert "targetId" not in str(result.proof)
    assert compiler.plans[0]["baseSha256"] == _sha(SOURCE.encode())


def test_exact_rejection_declines_but_tampered_envelope_fails_closed() -> None:
    rejected = _inventory()
    rejected.update(status="rejected", inventory=None, target=None)
    rejected["reasons"] = [{"code": "PARSER_LIMIT", "message": "not representable"}]
    assert (
        render_lossless_existing(
            compiler=_Compiler(rejected),
            lease=_lease(),
            request=_request(),
            grounding=_grounding(),
            source=SOURCE,
        )
        is None
    )

    invented_reason = deepcopy(rejected)
    invented_reason["reasons"][0]["code"] = "UNSUPPORTED"
    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=_Compiler(invented_reason),
            lease=_lease(),
            request=_request(),
            grounding=_grounding(),
            source=SOURCE,
        )
    assert raised.value.code == "LOSSLESS_INVALID"

    tampered = deepcopy(rejected)
    tampered["relative_path"] = "properties/demo/other.metis"
    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=_Compiler(tampered),
            lease=_lease(),
            request=_request(),
            grounding=_grounding(),
            source=SOURCE,
        )
    assert raised.value.code == "LOSSLESS_INVALID"


def test_comments_in_target_clause_decline_without_deleting_editorial_trivia() -> None:
    source = SOURCE.replace(
        '      @tipologia is "Serie"',
        '      // scelta editoriale\n      @tipologia is "Serie"',
    )
    compiler = _Compiler(_inventory(source))

    result = render_lossless_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request(source),
        grounding=_grounding(),
        source=source,
    )

    assert result is None
    assert compiler.plans == []


@pytest.mark.parametrize("mutation", ["toolchain", "ancestry", "span", "take_shape"])
def test_inventory_authority_drift_fails_closed(mutation: str) -> None:
    envelope = _inventory()
    if mutation == "toolchain":
        envelope["inventory"]["toolchain"]["langiumVersion"] = "999.0.0"
    elif mutation == "ancestry":
        envelope["inventory"]["nodes"][3]["parent"] = "$/elements@0"
    elif mutation == "span":
        span = _offsets(SOURCE, 0, len("endpoint"))
        node = envelope["inventory"]["nodes"][3]
        node["span"] = span
        node["preimageSha256"] = _sha(SOURCE[: len("endpoint")].encode())
        envelope["target"]["include_span"] = span
        envelope["target"]["include_preimage_sha256"] = node["preimageSha256"]
    else:
        envelope["target"]["take_shape"]["value"] = 99
    with pytest.raises(BrainError, match="lossless"):
        _validate_inventory(
            envelope,
            source=SOURCE,
            relative_path=PATH,
            endpoint=ENDPOINT,
            expected_toolchain=TOOLCHAIN,
        )


def test_projection_from_another_endpoint_is_rejected() -> None:
    other = SOURCE.replace(ENDPOINT, "demo.other", 1)
    source = other + SOURCE
    envelope = _inventory(source, projected_endpoint="demo.other")

    with pytest.raises(BrainError, match="spans"):
        _validate_inventory(
            envelope,
            source=source,
            relative_path=PATH,
            endpoint=ENDPOINT,
            expected_toolchain=TOOLCHAIN,
        )


@pytest.mark.parametrize(
    ("surface", "replacement"),
    [
        ("inventory_parent", []),
        ("target_endpoint", []),
        ("target_take", {}),
        ("target_include", ["$/elements@0/members@0/clauses@0"]),
    ],
)
def test_unhashable_inventory_identifiers_fail_as_brain_errors(
    surface: str,
    replacement: object,
) -> None:
    envelope = _inventory()
    if surface == "inventory_parent":
        envelope["inventory"]["nodes"][1]["parent"] = replacement
    else:
        prefix = surface.removeprefix("target_")
        envelope["target"][f"{prefix}_node_id"] = replacement

    with pytest.raises(BrainError) as raised:
        _validate_inventory(
            envelope,
            source=SOURCE,
            relative_path=PATH,
            endpoint=ENDPOINT,
            expected_toolchain=TOOLCHAIN,
        )
    assert raised.value.code == "LOSSLESS_INVALID"


def test_unrelated_technical_predicate_fails_before_model_fallback() -> None:
    source = SOURCE.replace(
        '      @tipologia is "Serie"',
        '      @tipologia is "Serie"\n      @content_channels is "PLAY"',
    )
    compiler = _Compiler(_inventory(source))

    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(source),
            grounding=_grounding("Film"),
            source=source,
        )

    assert raised.value.code == "EDIT_PRESERVATION_CONFLICT"
    assert compiler.plans == []


def test_inline_comment_cannot_hide_an_unreviewed_existing_field() -> None:
    source = SOURCE.replace(
        '      @tipologia is "Serie"',
        '      @tipologia is "Serie"\n'
        '      @content_channels is "PLAY" // vincolo tecnico da preservare',
    )
    compiler = _Compiler(_inventory(source))

    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(source),
            grounding=_grounding("Film"),
            source=source,
        )

    assert raised.value.code == "EDIT_PRESERVATION_CONFLICT"
    assert compiler.plans == []


def test_block_comment_cannot_bypass_preservation_conflict() -> None:
    source = SOURCE.replace(
        '      @tipologia is "Serie"',
        '      @tipologia is "Serie"\n'
        '      @content_channels is "PLAY" /* vincolo tecnico da preservare */',
    )
    compiler = _Compiler(_inventory(source))

    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(source),
            grounding=_grounding("Film"),
            source=source,
        )

    assert raised.value.code == "EDIT_PRESERVATION_CONFLICT"
    assert compiler.plans == []


def _record(ref: str, role: str, **kwargs: object) -> HostRefRecord:
    return HostRefRecord(
        ref=ref,
        role=role,
        relative_path=PATH,
        context_revision=HASH_A,
        workspace_base_revision=HASH_B,
        edit_source_revision=HASH_C,
        toolchain_binding="sha256:" + "d" * 64,
        **kwargs,
    )


def test_registry_enforces_roles_and_is_single_use() -> None:
    with pytest.raises(BrainError):
        _record(
            "hostref:evil",
            "evil",
            payload="include where {}",
            payload_sha256=_sha(b"include where {}"),
        )
    with pytest.raises(BrainError):
        _record(
            "hostref:bad-node",
            "node",
            node_id="$/elements@0",
            preimage_sha256=HASH_A,
            placement="bogus",
        )

    target = _record("hostref:target", "target")
    base = _record("hostref:base", "base")
    node = _record(
        "hostref:node",
        "node",
        node_id="$/elements@0",
        preimage_sha256=HASH_A,
    )
    payload_text = "include where {}"
    payload = _record(
        "hostref:payload",
        "payload",
        payload=payload_text,
        payload_sha256=_sha(payload_text.encode()),
    )
    registry = HostRefRegistry(
        records=[target, base, node, payload],
        target_ref=target.ref,
        base_ref=base.ref,
        basis_ref=None,
    )
    plan = {
        "schema_version": 2,
        "contract_id": EDIT_PLAN_CONTRACT,
        "context_revision": HASH_A,
        "workspace_base_revision": HASH_B,
        "edit_source_revision": HASH_C,
        "target_ref": target.ref,
        "base_ref": base.ref,
        "basis_ref": None,
        "operations": [
            {
                "ordinal": 0,
                "kind": "replace",
                "node_ref": node.ref,
                "payload_ref": payload.ref,
            }
        ],
    }
    translated = registry.translate(plan)
    assert translated["operations"][0]["text"] == payload_text
    with pytest.raises(BrainError) as raised:
        registry.translate(plan)
    assert raised.value.code == "EDIT_PLAN_STALE"


def test_receipt_hash_is_bound_to_complete_private_receipt() -> None:
    compiler = _Compiler()
    result = render_lossless_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request(),
        grounding=_grounding(),
        source=SOURCE,
    )
    assert result is not None and result.proof is not None
    assert result.proof["receipt_sha256"].startswith("sha256:")
    assert result.proof["receipt_sha256"] != canonical_sha256(result.proof)


@pytest.mark.parametrize(
    "mutation",
    ["extra_field", "sha_after", "bool_ordinal", "span", "untouched_prefix"],
)
def test_any_receipt_tamper_fails_closed(mutation: str) -> None:
    compiler = _Compiler()
    valid_apply = compiler.lossless_apply

    def tampered_apply(**kwargs: object):
        envelope = valid_apply(**kwargs)
        receipt = envelope["receipt"]
        touched = receipt["touchedSpans"][0]
        if mutation == "extra_field":
            receipt["unexpected"] = True
        elif mutation == "sha_after":
            receipt["shaAfter"] = HASH_A
        elif mutation == "bool_ordinal":
            touched["ordinal"] = False
        elif mutation == "span":
            touched["before"]["byteOffset"] += 1
        else:
            receipt["renderedText"] = "X" + receipt["renderedText"][1:]
            receipt["shaAfter"] = _sha(receipt["renderedText"].encode())
        return envelope

    compiler.lossless_apply = tampered_apply
    with pytest.raises(BrainError) as raised:
        render_lossless_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(),
            grounding=_grounding(),
            source=SOURCE,
        )
    assert raised.value.code in {"LOSSLESS_INVALID", "LOSSLESS_REJECTED"}


def test_crlf_and_unicode_offsets_preserve_all_untouched_bytes() -> None:
    source = ("/// Préambule 🎬\n" + SOURCE + "/// Coda è — intatta 📚\n").replace("\n", "\r\n")
    compiler = _Compiler(_inventory(source))
    result = render_lossless_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request(source),
        grounding=_grounding("Film d'autore"),
        source=source,
    )

    assert result is not None
    assert "\r\n" in result.candidate.source
    assert '"Film d\'autore"' in result.candidate.source
    assert result.candidate.source.startswith("/// Préambule 🎬\r\n")
    assert result.candidate.source.endswith("/// Coda è — intatta 📚\r\n")


def test_utf16_mid_surrogate_inventory_offset_fails_closed() -> None:
    source = SOURCE + "/// Coda 🎬"
    envelope = _inventory(source)
    envelope["inventory"]["nodes"][0]["span"]["end"] -= 1

    with pytest.raises(BrainError) as raised:
        _validate_inventory(
            envelope,
            source=source,
            relative_path=PATH,
            endpoint=ENDPOINT,
            expected_toolchain=TOOLCHAIN,
        )
    assert raised.value.code == "LOSSLESS_INVALID"


def test_refine_binds_compiler_plan_to_draft_not_workspace_base() -> None:
    draft = SOURCE.replace('"Serie"', '"Commedia"')
    compiler = _Compiler(_inventory(draft))
    request = _request(draft)
    request.target["base_sha256"] = _sha(SOURCE.encode())

    result = render_lossless_existing(
        compiler=compiler,
        lease=_lease(),
        request=request,
        grounding=_grounding("Film"),
        source=draft,
    )

    assert result is not None
    assert compiler.plans[0]["baseSha256"] == _sha(draft.encode())
    assert compiler.plans[0]["baseSha256"] != request.target["base_sha256"]


def test_inapplicable_class_is_not_a_public_brain_failure() -> None:
    assert issubclass(LosslessInapplicable, ValueError)
