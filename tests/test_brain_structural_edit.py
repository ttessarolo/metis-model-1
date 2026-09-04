"""Deterministic contract tests for compiler-owned structural edits."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_delta_permit import DeltaPermitError, DeltaPermitTranslator
from metis_model1.brain_lossless_edit import LOSSLESS_RECEIPT_CONTRACT
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_structural_edit import (
    EDIT_SURFACE_CONTRACT,
    render_structural_existing,
    structural_edit_requested,
)

SOURCE = "endpoint demo {\n  first take 10;\n  second take 10;\n  result limit 5;\n}\n"


def _sha(value: bytes | str) -> str:
    return bytes_sha256(value.encode("utf-8") if isinstance(value, str) else value)


def _span(source: str, start: int, end: int) -> dict[str, dict[str, int]]:
    prefix = source[:start]
    text = source[start:end]
    return {
        "utf16": {
            "start": len(prefix.encode("utf-16-le")) // 2,
            "end": len((prefix + text).encode("utf-16-le")) // 2,
        },
        "utf8_bytes": {"start": len(prefix.encode()), "end": len((prefix + text).encode())},
    }


def _item(
    source: str,
    *,
    primitive: str,
    token: str,
    old_value: dict[str, Any],
    name: str,
    occurrence: int = 0,
    scope_name: str | None = None,
    scope_kind: str = "block",
    stage_name: str | None = None,
    stage_selectors: list[str] | None = None,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name_start = source.index(name)
    owner_start = source.rfind("\n", 0, name_start) + 1
    owner_end = source.find("\n", name_start)
    if owner_end < 0:
        owner_end = len(source)
    property_start = source.index(token, owner_start, owner_end)
    property_end = property_start + len(token)
    owner_node_id = f"$/container/{name}@{occurrence}"
    property_data = {
        "ast_node_id": f"{owner_node_id}/value",
        "path": f"{primitive}.value",
        "preimage_sha256": _sha(token),
        "span": _span(source, property_start, property_end),
    }
    owner_data = {
        "node_id": owner_node_id,
        "node_type": "Take" if primitive == "take_cardinality" else "Scalar",
        "preimage_sha256": _sha(source[owner_start:owner_end]),
        "span": _span(source, owner_start, owner_end),
    }
    scope_label = scope_name or name
    stage_kind = "take" if primitive == "take_cardinality" else "return_flow"
    scope = {
        "ancestors": [
            {"kind": "endpoint", "node_id": "$/endpoint", "name": "demo", "label": None},
            {
                "kind": scope_kind,
                "node_id": "$/container",
                "name": scope_label,
                "label": scope_label,
            },
        ],
        "stage": {
            "kind": stage_kind,
            "node_id": f"{owner_node_id}/stage",
            "identifier": stage_name or scope_label,
            "activation_sha256": None,
            "selectors": {"identifiers": stage_selectors or [], "string_literals": []},
        },
        "occurrence": occurrence,
    }
    item = {
        "ordinal": 0,
        "edit_ref": "pending",
        "primitive": primitive,
        "owner": owner_data,
        "property": property_data,
        "scope": scope,
        "old_value": old_value,
        "authority": authority,
    }
    item["edit_ref"] = canonical_sha256(
        {
            "contract": EDIT_SURFACE_CONTRACT,
            "source_sha256": _sha(source),
            "primitive": primitive,
            "owner_node_id": owner_data["node_id"],
            "property": property_data,
            "scope": scope,
            "authority": authority,
        }
    )
    return item


def _surface(source: str, specs: list[dict[str, Any]]) -> dict[str, Any]:
    items = [_item(source, **spec, occurrence=index) for index, spec in enumerate(specs)]
    # The compiler's source-order roster is authoritative.
    items.sort(key=lambda item: item["property"]["span"]["utf8_bytes"]["start"])
    for ordinal, item in enumerate(items):
        item["ordinal"] = ordinal
    counts = {"items": len(items)}
    counts.update(
        {
            primitive: sum(item["primitive"] == primitive for item in items)
            for primitive in {
                "take_cardinality",
                "output_limit",
                "display_label_or_title",
                "block_argument_list",
            }
        }
    )
    surface = {
        "contract": EDIT_SURFACE_CONTRACT,
        "relative_path": "demo.metis",
        "source_sha256": _sha(source),
        "endpoint": {
            "name": "demo",
            "node_id": "$/endpoint",
            "preimage_sha256": _sha(source),
            "span": _span(source, 0, len(source)),
        },
        "items": items,
        "counts": counts,
    }
    return {
        "schema_version": 1,
        "operation": "edit-surface",
        "status": "ok",
        "diagnostics": [],
        "relative_path": "demo.metis",
        "endpoint": "demo",
        "edit_surface": surface,
        "edit_surface_sha256": canonical_sha256(surface),
    }


def _retarget_surface(envelope: dict[str, Any], endpoint: str) -> dict[str, Any]:
    envelope["endpoint"] = endpoint
    surface = envelope["edit_surface"]
    surface["endpoint"]["name"] = endpoint
    for item in surface["items"]:
        item["scope"]["ancestors"][0]["name"] = endpoint
        item["edit_ref"] = canonical_sha256(
            {
                "contract": EDIT_SURFACE_CONTRACT,
                "source_sha256": surface["source_sha256"],
                "primitive": item["primitive"],
                "owner_node_id": item["owner"]["node_id"],
                "property": item["property"],
                "scope": item["scope"],
                "authority": item["authority"],
            }
        )
    envelope["edit_surface_sha256"] = canonical_sha256(surface)
    return envelope


@dataclass
class FakeCompiler:
    source: str
    envelope: dict[str, Any]
    envelope_tamper: Callable[[dict[str, Any]], None] | None = None
    receipt_tamper: Callable[[dict[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        self.edit_surface_calls = 0
        self.lossless_apply_calls = 0
        self.lossless_toolchain_identity = {"compiler": "synthetic", "version": "1"}

    def edit_surface(self, **_kwargs: Any) -> dict[str, Any]:
        self.edit_surface_calls += 1
        result = deepcopy(self.envelope)
        if self.envelope_tamper is not None:
            self.envelope_tamper(result)
        return result

    def lossless_apply(
        self, *, source: str, plan: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        self.lossless_apply_calls += 1
        by_id = {
            item["owner"]["node_id"]: item["owner"]
            for item in self.envelope["edit_surface"]["items"]
        }
        rendered = source.encode()
        touched: list[dict[str, Any]] = []
        replacements: list[tuple[int, int, bytes]] = []
        for operation in plan["operations"]:
            owner = by_id[operation["targetId"]]
            span = owner["span"]
            start, end = span["utf8_bytes"]["start"], span["utf8_bytes"]["end"]
            payload = operation["text"].encode()
            replacements.append((start, end, payload))
            touched.append(
                {
                    "ordinal": operation["ordinal"],
                    "kind": "replace",
                    "targetId": operation["targetId"],
                    "before": {
                        "offset": span["utf16"]["start"],
                        "end": span["utf16"]["end"],
                        "byteOffset": start,
                        "byteEnd": end,
                    },
                    "afterByteLength": len(payload),
                }
            )
        for start, end, payload in sorted(replacements, reverse=True):
            rendered = rendered[:start] + payload + rendered[end:]
        rendered_text = rendered.decode()
        receipt = {
            "contract": LOSSLESS_RECEIPT_CONTRACT,
            "outcome": "APPLIED",
            "toolchain": self.lossless_toolchain_identity,
            "shaBefore": plan["baseSha256"],
            "shaAfter": _sha(rendered_text),
            "touchedSpans": touched,
            "diagnostics": [],
            "reasons": [],
            "renderedText": rendered_text,
        }
        if self.receipt_tamper is not None:
            self.receipt_tamper(receipt)
        return {
            "schema_version": 1,
            "operation": "lossless-apply",
            "status": "ok",
            "relative_path": "demo.metis",
            "endpoint": "demo",
            "proof_mode": "validate",
            "receipt": receipt,
        }


def _request(
    instruction: str,
    source: str = SOURCE,
    *,
    base: str | None = None,
    basis: dict[str, str] | None = None,
) -> Any:
    target = {
        "mode": "existing",
        "relative_path": "demo.metis",
        "endpoint": "demo",
        "base_sha256": base or _sha(source),
    }
    return SimpleNamespace(
        instruction=instruction,
        target=target,
        basis=basis,
        payload_hash=_sha("request-payload"),
        expected_semantic_source_revision=_sha("semantic-source"),
    )


def _lease(workspace_source: str = SOURCE) -> Any:
    return SimpleNamespace(
        snapshot=SimpleNamespace(
            revision=_sha("snapshot"),
            toolchain_binding=_sha("toolchain"),
            source_map=lambda: {"demo.metis": workspace_source},
        )
    )


def _record(*, basis_source: str | None = None) -> Any:
    return SimpleNamespace(session_id="s" * 43, turn_id="t" * 32, basis_source=basis_source)


def _reviewed_grounding(catalog: str, field: str, literal: str) -> dict[str, Any]:
    return {
        "semantic_source_revision": _sha("semantic-source"),
        "catalogs": [catalog],
        "selections": [
            {
                "catalog": catalog,
                "field": field,
                "literal": literal,
            }
        ],
        "resolutions": [
            {
                "review_state": "reviewed",
                "catalog": catalog,
                "field": field,
                "literal": literal,
            }
        ],
    }


def _exact_resolver_from_grounding(grounding: Mapping[str, Any]) -> Any:
    def resolve(*, lease: Any, identities: tuple[tuple[str, str, str], ...]) -> dict[str, Any]:
        selections = tuple(
            dict(item)
            for item in grounding.get("selections", [])
            if isinstance(item, Mapping)
            and (item.get("catalog"), item.get("field"), item.get("literal")) in identities
        )
        resolutions = tuple(
            dict(item)
            for item in grounding.get("resolutions", [])
            if isinstance(item, Mapping)
            and (item.get("catalog"), item.get("field"), item.get("literal")) in identities
        )
        return {
            "contract": "metis-brain-exact-reviewed-value-authority/v1",
            "context_revision": lease.snapshot.revision,
            "semantic_source_revision": grounding.get("semantic_source_revision"),
            "toolchain_binding": lease.snapshot.toolchain_binding,
            "index_revision": _sha("test-index"),
            "outcomes": tuple(
                {
                    "catalog": catalog,
                    "field": field,
                    "literal": literal,
                    "status": "reviewed_exact",
                }
                for catalog, field, literal in identities
            ),
            "selections": selections,
            "resolutions": resolutions,
        }

    return resolve


def _compiler(specs: list[dict[str, Any]], source: str = SOURCE, **kwargs: Any) -> FakeCompiler:
    envelope = _surface(source, specs)
    return FakeCompiler(source, envelope, **kwargs)


def _takes_and_limit_specs() -> list[dict[str, Any]]:
    return [
        {
            "primitive": "take_cardinality",
            "token": "10",
            "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
            "name": "first",
        },
        {
            "primitive": "take_cardinality",
            "token": "10",
            "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
            "name": "second",
        },
        {
            "primitive": "output_limit",
            "token": "5",
            "old_value": {"type": "non_negative_integer", "unit": "items", "value": 5},
            "name": "result",
        },
    ]


def test_multi_take_and_limit_is_lossless_and_uses_no_model() -> None:
    compiler = _compiler(_takes_and_limit_specs())
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request("porta entrambe le take da 10 a 20 e il limite da 5 a 8."),
        record=_record(),
        grounding={},
        source=SOURCE,
    )

    assert result is not None
    assert result.candidate.generator == "lossless_renderer"
    assert result.candidate.model_revision == "not_used"
    assert result.candidate.adapter_sha256 == "not_used"
    assert result.candidate.source == (
        SOURCE.replace("take 10", "take 20").replace("limit 5", "limit 8")
    )
    assert result.proof is not None and result.proof["touched_count"] == 3
    assert compiler.edit_surface_calls == compiler.lossless_apply_calls == 1


def test_entrambe_cannot_authorize_three_occurrences() -> None:
    source = "endpoint demo {\n  one take 10;\n  two take 10;\n  three take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": name,
                "scope_name": "same",
            }
            for name in ("one", "two", "three")
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request("porta entrambe le take da 10 a 20.", source),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"
    assert compiler.lossless_apply_calls == 0


def test_entrambe_cannot_authorize_one_occurrence() -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request("porta entrambe le take da 10 a 20."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )

    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"
    assert compiler.lossless_apply_calls == 0


def test_exact_string_label_edit() -> None:
    source = 'endpoint demo {\n  title "Vecchio Titolo";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Vecchio Titolo"',
                "old_value": {"type": "string", "value": "Vecchio Titolo"},
                "name": "title",
            }
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request("sostituisci `Vecchio Titolo` con `Nuovo Titolo`.", source),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("Vecchio Titolo", "Nuovo Titolo")


def test_exact_string_evidence_is_case_sensitive() -> None:
    source = 'endpoint demo {\n  upper "Film";\n  lower "film";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "upper",
            },
            {
                "primitive": "display_label_or_title",
                "token": '"film"',
                "old_value": {"type": "string", "value": "film"},
                "name": "lower",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request("sostituisci `Film` con `Nuovo`.", source),
        record=_record(),
        grounding={},
        source=source,
    )

    assert result is not None
    assert result.candidate.source == source.replace('"Film"', '"Nuovo"')
    assert 'lower "film"' in result.candidate.source


@pytest.mark.parametrize("new_value", [" Film in evidenza", "Film in evidenza ", " Film "])
def test_backtick_replacement_rejects_boundary_whitespace(new_value: str) -> None:
    source = 'endpoint demo {\n  title "Film";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "title",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(f"sostituisci `Film` con `{new_value}`.", source),
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_INVALID"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "modifica foo.bar: porta la take da 10 a 20.",
        "modifica foo.bar, porta la take da 10 a 20.",
        "modifica demo e foo.bar: porta la take da 10 a 20.",
    ],
)
def test_qualified_endpoint_mismatch_fails_before_edit_surface(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )

    assert error.value.code == "STRUCTURAL_EDIT_TARGET_MISMATCH"
    assert compiler.edit_surface_calls == compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "porta la take da 10 a 20. Modifica foo.bar:",
        "Modifica foo.bar: porta la take da 10 a 20. Modifica foo.bar:",
    ],
)
def test_matching_qualified_endpoint_is_only_a_single_leading_header(instruction: str) -> None:
    source = SOURCE
    envelope = _retarget_surface(_surface(source, _takes_and_limit_specs()[:1]), "foo.bar")
    compiler = FakeCompiler(source, envelope)
    target = {
        "mode": "existing",
        "relative_path": "demo.metis",
        "endpoint": "foo.bar",
        "base_sha256": _sha(source),
    }
    request = SimpleNamespace(
        instruction=instruction,
        target=target,
        basis=None,
        payload_hash=_sha("request-payload"),
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=request,
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


def test_duplicate_string_transitions_are_each_bound_to_their_scope() -> None:
    source = 'endpoint demo {\n  alpha "Film";\n  beta "Film";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "alpha",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "beta",
                "scope_name": "beta",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per l'etichetta della variante alpha sostituisci `Film` con `Nuovo`; "
            "per l'etichetta della variante beta sostituisci `Film` con `Nuovo`.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source.count('"Nuovo"') == 2


def test_block_argument_addition_requires_reviewed_literal() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
            }
        ],
        source,
    )
    grounding = _reviewed_grounding("catalog.video", "genres", "Documentario")
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per la lista args modifica: sostituisci `Film,Serie` con `Film,Serie,Documentario`.",
            source,
        ),
        record=_record(),
        grounding=grounding,
        source=source,
        reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
    )
    assert result is not None
    assert result.candidate.source == source.replace("Film,Serie", "Film,Serie,Documentario")


def test_block_argument_add_action_is_bound_to_exact_delimited_transition() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
            }
        ],
        source,
    )
    grounding = _reviewed_grounding("catalog.video", "genres", "Documentario")
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "aggiungi Documentario alla lista genres: da `Film,Serie` a `Film,Serie,Documentario`.",
            source,
        ),
        record=_record(),
        grounding=grounding,
        source=source,
        reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
    )

    assert result is not None
    assert result.candidate.source == source.replace("Film,Serie", "Film,Serie,Documentario")


def test_block_argument_add_action_must_match_exact_added_literal_and_argument() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    spec = {
        "primitive": "block_argument_list",
        "token": '"Film,Serie"',
        "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
        "name": "args",
        "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
    }
    grounding = {
        "resolutions": [
            {
                "review_state": "reviewed",
                "catalog": "catalog.video",
                "field": "genres",
                "literal": "Documentario",
            }
        ]
    }
    for instruction in (
        "aggiungi Serie alla lista genres: da `Film,Serie` a `Film,Serie,Documentario`.",
        "aggiungi Documentario alla lista other: da `Film,Serie` a `Film,Serie,Documentario`.",
    ):
        compiler = _compiler([spec], source)
        with pytest.raises(BrainError) as error:
            render_structural_existing(
                compiler=compiler,
                lease=_lease(source),
                request=_request(instruction, source),
                record=_record(),
                grounding=grounding,
                source=source,
            )
        assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
        assert compiler.lossless_apply_calls == 0


def test_block_argument_authority_must_cover_every_compiler_binding() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {
                    "bindings": [
                        {"catalog": "catalog.video", "field": "genre_a"},
                        {"catalog": "catalog.video", "field": "genre_b"},
                    ]
                },
            }
        ],
        source,
    )
    grounding = _reviewed_grounding("catalog.video", "genre_a", "Documentario")
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista args sostituisci `Film,Serie` con `Film,Serie,Documentario`.",
                source,
            ),
            record=_record(),
            grounding=grounding,
            source=source,
            reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
        )
    assert error.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize("mutation", ["missing_selection", "duplicate_selection", "stale_revision"])
def test_block_argument_review_roster_fails_before_apply(mutation: str) -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
            }
        ],
        source,
    )
    grounding = _reviewed_grounding("catalog.video", "genres", "Documentario")
    if mutation == "missing_selection":
        grounding["selections"] = []
    elif mutation == "duplicate_selection":
        grounding["selections"] = grounding["selections"] * 2
    else:
        grounding["semantic_source_revision"] = _sha("stale-semantic-source")

    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista args sostituisci `Film,Serie` con `Film,Serie,Documentario`.",
                source,
            ),
            record=_record(),
            grounding=grounding,
            source=source,
            reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
        )
    assert error.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"
    assert compiler.lossless_apply_calls == 0


def test_block_argument_requires_and_retains_every_reviewed_compiler_binding() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {
                    "bindings": [
                        {"catalog": "catalog.video", "field": "genre_primary"},
                        {"catalog": "catalog.video", "field": "genre_secondary"},
                    ]
                },
            }
        ],
        source,
    )
    first = _reviewed_grounding("catalog.video", "genre_primary", "Documentario")
    second = _reviewed_grounding("catalog.video", "genre_secondary", "Documentario")
    grounding = {
        "semantic_source_revision": first["semantic_source_revision"],
        "catalogs": ["catalog.video"],
        "selections": first["selections"] + second["selections"],
        "resolutions": first["resolutions"] + second["resolutions"],
    }

    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per la lista args sostituisci `Film,Serie` con `Film,Serie,Documentario`.",
            source,
        ),
        record=_record(),
        grounding=grounding,
        source=source,
        reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
    )

    assert result is not None
    assert result.semantic_delta is not None
    assert result.semantic_delta["reviewed_selection_identities"] == (
        ("catalog.video", "genre_primary", "Documentario"),
        ("catalog.video", "genre_secondary", "Documentario"),
    )
    assert compiler.lossless_apply_calls == 1


def test_string_object_cue_prevents_label_and_argument_collision() -> None:
    source = 'endpoint demo {\n  title "Azione";\n  args "Azione";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Azione"',
                "old_value": {"type": "string", "value": "Azione"},
                "name": "title",
            },
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "args",
                "scope_kind": "use_instance",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genre"}]},
            },
        ],
        source,
    )
    grounding = _reviewed_grounding("catalog.video", "genre", "Avventura")
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per la lista genere sostituisci `Azione` con `Azione,Avventura` nell'istanza args.",
            source,
        ),
        record=_record(),
        grounding=grounding,
        source=source,
        reviewed_value_resolver=_exact_resolver_from_grounding(grounding),
    )
    assert result is not None
    assert 'title "Azione"' in result.candidate.source
    assert 'args "Azione,Avventura"' in result.candidate.source


def test_block_argument_uses_compiler_derived_exact_reviewed_resolver_before_apply() -> None:
    source = 'endpoint demo {\n  args "Azione";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "args",
                "scope_kind": "use_instance",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genre"}]},
            }
        ],
        source,
    )
    grounding = {
        "semantic_source_revision": _sha("semantic-source"),
        "catalogs": ["catalog.video"],
        "selections": [],
        "resolutions": [],
    }
    observed: list[tuple[tuple[str, str, str], ...]] = []

    def resolve(*, lease: Any, identities: tuple[tuple[str, str, str], ...]) -> dict[str, Any]:
        observed.append(identities)
        assert lease.snapshot.revision == _sha("snapshot")
        return {
            "contract": "metis-brain-exact-reviewed-value-authority/v1",
            "context_revision": lease.snapshot.revision,
            "semantic_source_revision": _sha("semantic-source"),
            "toolchain_binding": lease.snapshot.toolchain_binding,
            "index_revision": _sha("index"),
            "outcomes": (
                {
                    "catalog": "catalog.video",
                    "field": "genre",
                    "literal": "Avventura",
                    "status": "reviewed_exact",
                },
            ),
            "selections": (
                {
                    "catalog": "catalog.video",
                    "field": "genre",
                    "literal": "Avventura",
                    "type": "keyword",
                    "modifiers": [],
                },
            ),
            "resolutions": (
                {
                    "concept": "Avventura",
                    "catalog": "catalog.video",
                    "field": "genre",
                    "literal": "Avventura",
                    "review_state": "reviewed",
                },
            ),
        }

    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per la lista genere sostituisci `Azione` con `Azione,Avventura` nell'istanza args.",
            source,
        ),
        record=_record(),
        grounding=grounding,
        source=source,
        reviewed_value_resolver=resolve,
    )

    assert result is not None
    assert observed == [(("catalog.video", "genre", "Avventura"),)]
    assert result.semantic_delta is not None
    assert result.semantic_delta["compiler_binding_identities"] == (
        ("catalog.video", "genre", "Avventura"),
    )
    assert result.semantic_delta["reviewed_selection_identities"] == (
        ("catalog.video", "genre", "Avventura"),
    )
    assert result.semantic_delta["exact_authority"]["index_revision"] == _sha("index")
    assert compiler.lossless_apply_calls == 1
    assert grounding["selections"] == []


def test_block_argument_rejects_raw_reviewed_grounding_without_exact_resolver() -> None:
    source = 'endpoint demo {\n  args "Azione";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "args",
                "scope_kind": "use_instance",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genre"}]},
            }
        ],
        source,
    )

    with pytest.raises(BrainError) as raised:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista genere sostituisci `Azione` con "
                "`Azione,Avventura` nell'istanza args.",
                source,
            ),
            record=_record(),
            grounding=_reviewed_grounding("catalog.video", "genre", "Avventura"),
            source=source,
        )

    assert raised.value.code == "STRUCTURAL_EDIT_AUTHORITY_UNAVAILABLE"
    assert compiler.lossless_apply_calls == 0


def test_exact_reviewed_resolver_failure_happens_before_permit_and_apply() -> None:
    source = 'endpoint demo {\n  args "Azione";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "args",
                "scope_kind": "use_instance",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genre"}]},
            }
        ],
        source,
    )

    def missing(**_kwargs: Any) -> dict[str, Any]:
        return {
            "contract": "metis-brain-exact-reviewed-value-authority/v1",
            "context_revision": _sha("snapshot"),
            "semantic_source_revision": _sha("semantic-source"),
            "toolchain_binding": _sha("toolchain"),
            "index_revision": _sha("index"),
            "outcomes": (
                {
                    "catalog": "catalog.video",
                    "field": "genre",
                    "literal": "Avventura",
                    "status": "reviewed_exact",
                },
            ),
            "selections": (),
            "resolutions": (),
        }

    with pytest.raises(BrainError) as raised:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista genere sostituisci `Azione` con "
                "`Azione,Avventura` nell'istanza args.",
                source,
            ),
            record=_record(),
            grounding={
                "semantic_source_revision": _sha("semantic-source"),
                "catalogs": ["catalog.video"],
                "selections": [],
                "resolutions": [],
            },
            source=source,
            reviewed_value_resolver=missing,
        )
    assert raised.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"
    assert compiler.lossless_apply_calls == 0


def test_nonsemantic_structural_edit_never_calls_exact_value_resolver() -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])

    def unexpected(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("numeric edit must not resolve a catalog value")

    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request("porta la take da 10 a 20."),
        record=_record(),
        grounding={},
        source=SOURCE,
        reviewed_value_resolver=unexpected,
    )
    assert result is not None
    assert compiler.lossless_apply_calls == 1


def test_stale_base_hash_fails_closed() -> None:
    compiler = _compiler(_takes_and_limit_specs())
    with pytest.raises(BrainError, match="stale") as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request("porta la take da 10 a 20.", base=_sha("different")),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STALE_CONTEXT"
    assert compiler.edit_surface_calls == 0


@pytest.mark.parametrize("tamper", ["surface", "preimage", "edit_ref"])
def test_tampered_surface_preimage_or_edit_ref_is_rejected(tamper: str) -> None:
    specs = _takes_and_limit_specs()[:1]

    def mutate(envelope: dict[str, Any]) -> None:
        item = envelope["edit_surface"]["items"][0]
        if tamper == "surface":
            envelope["edit_surface"]["counts"]["items"] = 9
        elif tamper == "preimage":
            item["property"]["preimage_sha256"] = _sha("tampered")
        else:
            item["edit_ref"] = _sha("tampered")
        # Keep the outer seal valid so each mutation reaches the intended check.
        envelope["edit_surface_sha256"] = canonical_sha256(envelope["edit_surface"])

    compiler = _compiler(specs, envelope_tamper=mutate)
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request("porta la take da 10 a 20."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "EDIT_SURFACE_INVALID"


def test_ambiguous_same_occurrence_shape_fails_closed() -> None:
    source = 'endpoint demo {\n  one "Vecchio Titolo";\n  two "Vecchio Titolo";\n}\n'
    specs = [
        {
            "primitive": "display_label_or_title",
            "token": '"Vecchio Titolo"',
            "old_value": {"type": "string", "value": "Vecchio Titolo"},
            "name": "one",
            "scope_name": "card",
        },
        {
            "primitive": "display_label_or_title",
            "token": '"Vecchio Titolo"',
            "old_value": {"type": "string", "value": "Vecchio Titolo"},
            "name": "two",
            "scope_name": "card",
        },
    ]
    compiler = _compiler(specs, source)

    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "sostituisci `Vecchio Titolo` con `Nuovo Titolo` per la card etichetta.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"


def test_missing_reviewed_authority_fails_closed() -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista args modifica: sostituisci `Film,Serie` con "
                "`Film,Serie,Documentario`.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"


@pytest.mark.parametrize(
    ("catalog", "field"),
    [("catalog.other", "genres"), ("catalog.video", "other_field")],
)
def test_reviewed_same_literal_with_wrong_catalog_or_field_fails_closed(
    catalog: str, field: str
) -> None:
    source = 'endpoint demo {\n  args "Film,Serie";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "args",
                "authority": {"bindings": [{"catalog": "catalog.video", "field": "genres"}]},
            }
        ],
        source,
    )
    grounding = {
        "resolutions": [
            {
                "review_state": "reviewed",
                "catalog": catalog,
                "field": field,
                "literal": "Documentario",
            }
        ]
    }
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista args modifica: sostituisci `Film,Serie` con "
                "`Film,Serie,Documentario`.",
                source,
            ),
            record=_record(),
            grounding=grounding,
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"


def test_second_structural_refinement_uses_proposal_source_and_workspace_base() -> None:
    proposal = SOURCE.replace("first take 10", "first take 12")
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "12",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 12},
                "name": "first",
            }
        ],
        proposal,
    )
    request = _request(
        "porta la take da 12 a 20.",
        proposal,
        base=_sha(SOURCE),
        basis={"kind": "proposal", "proposal_ref": "hostref:basis:proposal-1"},
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(SOURCE),
        request=request,
        record=_record(basis_source=proposal),
        grounding={},
        source=proposal,
    )
    assert result is not None
    assert result.candidate.source == proposal.replace("first take 12", "first take 20")
    assert request.target["base_sha256"] == _sha(SOURCE)
    assert compiler.edit_surface_calls == compiler.lossless_apply_calls == 1


def test_delta_permit_is_single_use_when_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    original = DeltaPermitTranslator.consume
    replay_observed = False

    def consume_once(self: Any, value: Any, *, current_binding: Any, now_ms: int) -> Any:
        nonlocal replay_observed
        result = original(self, value, current_binding=current_binding, now_ms=now_ms)
        with pytest.raises(DeltaPermitError) as replay:
            original(self, value, current_binding=current_binding, now_ms=now_ms)
        replay_observed = replay.value.code == "DELTA_PERMIT_REPLAY"
        return result

    monkeypatch.setattr(DeltaPermitTranslator, "consume", consume_once)
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(),
        request=_request("porta la take da 10 a 20."),
        record=_record(),
        grounding={},
        source=SOURCE,
    )
    assert result is not None and replay_observed


@pytest.mark.parametrize("kind", ["receipt", "toolchain"])
def test_tampered_receipt_or_toolchain_is_rejected(kind: str) -> None:
    def mutate(receipt: dict[str, Any]) -> None:
        if kind == "receipt":
            receipt["reasons"] = ["tampered"]
        else:
            receipt["toolchain"] = {"compiler": "tampered"}

    compiler = _compiler(_takes_and_limit_specs()[:1], receipt_tamper=mutate)
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request("porta la take da 10 a 20."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code in {"LOSSLESS_INVALID", "LOSSLESS_REJECTED"}


def test_vague_instruction_is_inapplicable() -> None:
    compiler = _compiler(_takes_and_limit_specs())
    request = _request("sistema il catalogo e aggiorna i contenuti.")
    assert not structural_edit_requested(request.instruction)
    assert (
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=request,
            record=_record(),
            grounding={},
            source=SOURCE,
        )
        is None
    )
    assert compiler.edit_surface_calls == 0


def test_mixed_semantic_request_is_fail_closed() -> None:
    """An edit operator must not absorb an unrelated semantic request."""

    compiler = _compiler(_takes_and_limit_specs())
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request("porta la take da 10 a 20 e filtra per genere Azione."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"


@pytest.mark.parametrize(
    "extra_request",
    [
        "e aggiungi view-all",
        "e aggiungi la paginazione",
        "e filtra per genere",
        "e modifica il catalogo utenti",
        "e includi film italiani",
        "e modifica la response",
        "e aggiungi deduplicate",
        "e rimuovi il fallback",
    ],
)
def test_each_unsupported_mixed_addition_fails_before_lossless_apply(
    extra_request: str,
) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(f"porta la take da 10 a 20 {extra_request}."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize("scope", ["ramo inesistente", "variante inesistente"])
def test_explicit_unknown_scope_fails_closed(scope: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(f"porta la take da 10 a 20 nel {scope}."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    ("old_mode", "instruction"),
    [
        (
            "page_default",
            "porta la take da 10 a 20 nel totale",
        ),
        (
            "count",
            "porta la take da 10 a 20 per pagina",
        ),
    ],
)
def test_take_mode_mismatch_cannot_cross_count_and_page_default(
    old_mode: str, instruction: str
) -> None:
    source = "endpoint demo {\n  first take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": old_mode, "value": 10},
                "name": "first",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(instruction + ".", source),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


def test_page_default_has_one_bounded_positive_form() -> None:
    source = "endpoint demo {\n  page take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {
                    "type": "positive_integer",
                    "mode": "page_default",
                    "value": 10,
                },
                "name": "page",
            }
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request("porta la take da 10 a 20 per pagina.", source),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("take 10", "take 20")


@pytest.mark.parametrize(
    ("unit", "instruction"),
    [
        ("percent", "porta il limite da 5 a 8 elementi"),
        ("items", "porta il limite da 5 a 8 percentuale"),
    ],
)
def test_output_limit_unit_mismatch_fails_closed(unit: str, instruction: str) -> None:
    source = "endpoint demo {\n  result limit 5;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "output_limit",
                "token": "5",
                "old_value": {"type": "non_negative_integer", "unit": unit, "value": 5},
                "name": "result",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(instruction + ".", source),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


def test_string_label_scope_suffix_is_trimmed_from_replacement() -> None:
    source = 'endpoint demo {\n  title "Vecchio Titolo";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Vecchio Titolo"',
                "old_value": {"type": "string", "value": "Vecchio Titolo"},
                "name": "title",
                "scope_name": "film",
                "scope_kind": "variant",
            }
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "sostituisci `Vecchio Titolo` con `Nuovo Titolo` nella variante film.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("Vecchio Titolo", "Nuovo Titolo")
    assert "nella variante" not in result.candidate.source
    assert compiler.lossless_apply_calls == 1


def test_independent_numeric_clauses_remain_bound_to_their_scopes() -> None:
    source = "endpoint demo {\n  alpha take 10;\n  beta limit 5;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha",
            },
            {
                "primitive": "output_limit",
                "token": "5",
                "old_value": {"type": "non_negative_integer", "unit": "items", "value": 5},
                "name": "beta",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request("porta la take alpha da 10 a 20 e il limite beta da 5 a 8.", source),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("take 10", "take 20").replace(
        "limit 5", "limit 8"
    )
    assert compiler.lossless_apply_calls == 1


@pytest.mark.parametrize("separator", ["; ", " e "])
def test_repeated_old_values_cannot_cross_numeric_clause_scopes(separator: str) -> None:
    source = (
        "endpoint demo {\n"
        "  alpha_one take 10;\n"
        "  alpha_two take 10;\n"
        "  alpha_other take 5;\n"
        "  beta take 5;\n"
        "}\n"
    )
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha_one",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha_two",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "5",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 5},
                "name": "alpha_other",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "5",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 5},
                "name": "beta",
                "scope_name": "beta",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "Nella variante alpha porta entrambe le take da 10 a 20"
            + separator
            + "nella variante beta porta la take da 5 a 8.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == (
        "endpoint demo {\n"
        "  alpha_one take 20;\n"
        "  alpha_two take 20;\n"
        "  alpha_other take 5;\n"
        "  beta take 8;\n"
        "}\n"
    )


def test_duplicate_numeric_transition_evidence_is_not_collapsed() -> None:
    source = "endpoint demo {\n  alpha take 10;\n  beta take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "beta",
                "scope_name": "beta",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "nella variante alpha porta la take da 10 a 20 e "
            "nella variante beta porta la take da 10 a 20.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source.count("take 20") == 2


def test_limit_of_results_cannot_bleed_into_take_cardinality() -> None:
    source = "endpoint demo {\n  row take 10;\n  result limit 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "row",
            },
            {
                "primitive": "output_limit",
                "token": "10",
                "old_value": {"type": "non_negative_integer", "unit": "items", "value": 10},
                "name": "result",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request("Porta il limite dei risultati da 10 a 20.", source),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("limit 10", "limit 20")
    assert "take 10" in result.candidate.source


@pytest.mark.parametrize(
    "preservation",
    [
        "il limite resta invariato",
        "non toccare il limite",
        "preservando il limite",
    ],
)
def test_preserved_limit_cannot_become_positive_numeric_authority(preservation: str) -> None:
    source = "endpoint demo {\n  row take 10;\n  result limit 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "row",
            },
            {
                "primitive": "output_limit",
                "token": "10",
                "old_value": {"type": "non_negative_integer", "unit": "items", "value": 10},
                "name": "result",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(f"porta la take da 10 a 20, {preservation}.", source),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert "take 20" in result.candidate.source
    assert "limit 10" in result.candidate.source


def test_real_and_nonexistent_explicit_scopes_fail_closed() -> None:
    source = "endpoint demo {\n  alpha take 10;\n  beta take 5;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha",
            },
            {
                "primitive": "take_cardinality",
                "token": "5",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 5},
                "name": "beta",
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "porta la take da 10 a 20 nel ramo alpha e la take da 5 a 8 nel ramo inesistente.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


def test_every_scope_phrase_must_resolve_even_when_one_real_scope_scores() -> None:
    source = "endpoint demo {\n  row take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "row",
                "scope_name": "real_variant",
                "scope_kind": "variant",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "Porta la take da 10 a 20 nel ramo inesistente della variante real_variant.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "fake_scope",
    ["fakereal_variant", "prefixreal_variant", "real_variantzzz"],
)
def test_scope_matching_rejects_identifier_substrings(fake_scope: str) -> None:
    source = "endpoint demo {\n  row take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "row",
                "scope_name": "real_variant",
                "scope_kind": "variant",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                f"nella variante {fake_scope} porta la take da 10 a 20.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize("kind", ["variante", "ramo", "istanza", "riga"])
def test_scope_kind_cannot_bind_homonymous_block(kind: str) -> None:
    source = "endpoint demo {\n  row take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "row",
                "scope_name": "film",
                "scope_kind": "block",
                "stage_name": "other",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(f"nella {kind} film porta la take da 10 a 20.", source),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "porta la take da 10 a 20 e senza dubbio aggiungi un filtro",
        "porta la take da 10 a 20 e non solo aggiungi un fallback",
        "porta la take da 10 a 20; senza esitazioni usa il catalogo utenti",
    ],
)
def test_negation_words_cannot_bypass_mixed_intent_guard(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction + "."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "porta la take da 10 a 20. Mantieni il titolo ma aggiungi un fallback",
        "porta la take da 10 a 20, senza modificare il titolo ma usa il catalogo utenti",
        "porta la take da 10 a 20 e conserva il blocco, poi inserisci un filtro",
        "porta la take da 10 a 20 e cambia lo shuffle",
        "porta la take da 10 a 20 e modifica lo smart-order",
        "porta la take da 10 a 20 e cambia il template POSTER",
        "porta la take da 10 a 20 e cambia il seed",
        "porta la take da 10 a 20 e modifica la finestra a 14 giorni",
        "porta la take da 10 a 20 e cambia la guardia HDR",
        "porta la take da 10 a 20 e modifica le sorgenti candidate",
        "porta la take da 10 a 20 e cambia le alternative",
        "porta la take da 10 a 20 e aumenta il pool candidati",
        "porta la take da 10 a 20 e seleziona solo commedie",
        "porta la take da 10 a 20 e azzera il limite",
        "porta la take da 10 a 20 e dimezza il limite",
        "porta la take da 10 a 20 e raddoppia il limite",
        "porta la take da 10 a 20 e togli il limite",
        "configura lo shuffle e porta la take da 10 a 20",
        "riusa la sorgente candidate e porta la take da 10 a 20",
        "combina le alternative e porta la take da 10 a 20",
        "definisci una finestra di 14 giorni e porta la take da 10 a 20",
        "togli il template e porta la take da 10 a 20",
        "disattiva HDR e porta la take da 10 a 20",
        "raddoppia il pool e porta la take da 10 a 20",
        "azzera il seed e porta la take da 10 a 20",
    ],
)
def test_every_unconsumed_action_fails_closed(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction + "."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "voglio il titolo visibile e 20 risultati invece dei 10 attuali.",
        "voglio la lista genere e 20 risultati invece dei 10 attuali.",
    ],
)
def test_mentioned_structural_object_without_transition_cannot_be_partially_applied(
    instruction: str,
) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )

    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "mixed_synonym",
    [
        "crea un fallback",
        "imposta un filtro",
        "limita ai film italiani",
        "abilita il view-all",
        "collega il fallback",
        "sostituisci il catalogo video con utenti",
    ],
)
def test_mixed_intent_synonyms_fail_closed_before_apply(mixed_synonym: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(f"porta la take da 10 a 20 e {mixed_synonym}."),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "pubblica subito questo endpoint e porta la take da 10 a 20.",
        "invia la bozza e porta la take da 10 a 20.",
        "resetta tutto e porta la take da 10 a 20.",
        "riscrivi il resto e porta la take da 10 a 20.",
        "salva tutto e porta la take da 10 a 20.",
        "include il primo risultato e porta la take da 10 a 20.",
    ],
)
def test_unknown_prefix_action_cannot_hide_before_numeric_edit(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "porta la take da 10 e pubblica il resto a 20.",
        "porta la take da 10 poi invia la bozza a 20.",
        "porta la take da 10 e resetta tutto a 20.",
    ],
)
def test_unknown_action_cannot_be_swallowed_inside_numeric_evidence(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises((BrainError, ValueError)):
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert compiler.lossless_apply_calls == 0


def test_embedded_numeric_selector_must_be_compiler_owned() -> None:
    source = "endpoint demo {\n  first take 5;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "5",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 5},
                "name": "first",
                "stage_selectors": ["subbrand_title", "clip_trame"],
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "modifica il take che oggi prende 5 elementi e include "
                "selector_inventato: portalo a 4.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0

    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "modifica il take che oggi prende 5 elementi e include "
            "subbrand_title clip_trame: portalo a 4.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )
    assert result is not None
    assert result.candidate.source == source.replace("take 5", "take 4")


@pytest.mark.parametrize(
    "instruction",
    [
        "porta la take da 10 a 20. Non cambiare il titolo e pubblica questo endpoint.",
        "porta la take da 10 a 20, mantieni il titolo e invia la bozza.",
        "porta la take da 10 a 20, conserva il blocco e resetta tutto.",
        "porta la take da 10 a 20, senza modificare il titolo e riscrivi il resto.",
    ],
)
def test_preservation_clause_cannot_swallow_unknown_action(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "non portare la take da 10 a 20.",
        "non voglio portare la take da 10 a 20.",
        "evita di portare la take da 10 a 20.",
    ],
)
def test_negated_numeric_transition_never_authorizes_edit(instruction: str) -> None:
    compiler = _compiler(_takes_and_limit_specs()[:1])
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(),
            request=_request(instruction),
            record=_record(),
            grounding={},
            source=SOURCE,
        )
    assert error.value.code == "STRUCTURAL_EDIT_MIXED_INTENT"
    assert compiler.lossless_apply_calls == 0


def test_string_fast_path_requires_delimited_values_and_rejects_trailing_action() -> None:
    source = 'endpoint demo {\n  title "Film";\n}\n'
    spec = {
        "primitive": "display_label_or_title",
        "token": '"Film"',
        "old_value": {"type": "string", "value": "Film"},
        "name": "title",
    }
    for instruction in (
        "sostituisci Film con Nuovo Film.",
        "sostituisci `Film` con `Nuovo Film` e pubblicalo.",
        "non sostituisci `Film` con `Nuovo Film`.",
    ):
        compiler = _compiler([spec], source)
        with pytest.raises(BrainError):
            render_structural_existing(
                compiler=compiler,
                lease=_lease(source),
                request=_request(instruction, source),
                record=_record(),
                grounding={},
                source=source,
            )
        assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "Mantieni il filtro per regista e aggiungi un filtro per i film italiani.",
        "Mantieni gli attori attuali e aggiungi un filtro per i film italiani.",
        "Aggiungi un filtro per i film italiani.",
    ],
)
def test_non_structural_semantic_edits_do_not_enter_closed_fast_path(instruction: str) -> None:
    assert structural_edit_requested(instruction) is False


def test_numeric_scopes_are_bound_to_each_transition_not_global_union() -> None:
    source = "endpoint demo {\n  alpha take 10;\n  beta take 5;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha",
                "scope_name": "alpha",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "5",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 5},
                "name": "beta",
                "scope_name": "beta",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "nella variante alpha porta la take da 5 a 8; "
                "nella variante beta porta la take da 10 a 20.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


@pytest.mark.parametrize("query", ["alpha", "beta alpha"])
def test_explicit_scope_requires_exact_compiler_owned_name(query: str) -> None:
    source = "endpoint demo {\n  alpha_beta take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "alpha_beta",
                "scope_name": "alpha beta",
                "scope_kind": "variant",
            }
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(f"nella variante {query} porta la take da 10 a 20.", source),
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_SCOPE_UNRESOLVED"
    assert compiler.lossless_apply_calls == 0


def test_incidental_scope_token_cannot_break_an_unscoped_tie() -> None:
    source = "endpoint demo {\n  one take 10;\n  two take 10;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "one",
                "scope_name": "featured_take",
                "scope_kind": "variant",
            },
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "two",
                "scope_name": "other",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request("porta la take da 10 a 20.", source),
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"
    assert compiler.lossless_apply_calls == 0


def test_old_string_literal_cannot_be_reused_as_implicit_scope_authority() -> None:
    source = 'endpoint demo {\n  movie "Film";\n  series "Film";\n}\n'
    compiler = _compiler(
        [
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "movie",
                "scope_name": "film",
                "scope_kind": "variant",
            },
            {
                "primitive": "display_label_or_title",
                "token": '"Film"',
                "old_value": {"type": "string", "value": "Film"},
                "name": "series",
                "scope_name": "series",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request("sostituisci `Film` con `Nuovo`.", source),
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"
    assert compiler.lossless_apply_calls == 0


def test_plural_hdr_sdr_scope_is_disjunctive_per_item_and_exhaustive_as_a_set() -> None:
    source = "endpoint demo {\n  hdr take 30;\n  sdr take 30;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "30",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 30},
                "name": "hdr",
                "scope_name": "target",
                "scope_kind": "variant",
                "stage_selectors": ["4K HDR"],
            },
            {
                "primitive": "take_cardinality",
                "token": "30",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 30},
                "name": "sdr",
                "scope_name": "target",
                "scope_kind": "variant",
                "stage_selectors": ["4K SDR"],
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "nella variante target porta entrambe le righe HDR e SDR da 30 a 24 risultati.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )

    assert result is not None
    assert result.candidate.source == source.replace("take 30", "take 24")


def test_plural_hdr_sdr_scope_requires_one_exact_item_per_named_branch() -> None:
    source = "endpoint demo {\n  first take 30;\n  second take 30;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "30",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 30},
                "name": name,
                "scope_name": "target",
                "scope_kind": "variant",
                "stage_selectors": ["4K HDR", "4K SDR"],
            }
            for name in ("first", "second")
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "nella variante target porta entrambe le righe HDR e SDR da 30 a 24 risultati.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )

    assert error.value.code == "STRUCTURAL_EDIT_AMBIGUOUS"
    assert compiler.lossless_apply_calls == 0


def test_plural_rows_can_share_one_exact_relative_output_limit_transition() -> None:
    source = "endpoint demo {\n  hdr take 30;\n  sdr take 30;\n  result limit 30;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "30",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 30},
                "name": "hdr",
                "scope_name": "target",
                "scope_kind": "variant",
                "stage_selectors": ["4K HDR"],
            },
            {
                "primitive": "take_cardinality",
                "token": "30",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 30},
                "name": "sdr",
                "scope_name": "target",
                "scope_kind": "variant",
                "stage_selectors": ["4K SDR"],
            },
            {
                "primitive": "output_limit",
                "token": "30",
                "old_value": {"type": "non_negative_integer", "unit": "items", "value": 30},
                "name": "result",
                "scope_name": "target",
                "scope_kind": "variant",
            },
        ],
        source,
    )
    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "nella variante target porta entrambe le righe HDR e SDR da 30 a 24 risultati "
            "e il relativo limite finale a 24.",
            source,
        ),
        record=_record(),
        grounding={},
        source=source,
    )

    assert result is not None
    assert result.candidate.source == source.replace("30", "24")
    assert result.proof is not None and result.proof["touched_count"] == 3


def test_block_argument_source_witness_cannot_replace_reviewed_authority() -> None:
    source = 'endpoint demo {\n  target "Film,Serie";\n  witness "Film,Serie,Documentario";\n}\n'
    authority = {"bindings": [{"catalog": "catalog.video", "field": "genres"}]}
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie"',
                "old_value": {"type": "string", "argument": "genres", "value": "Film,Serie"},
                "name": "target",
                "authority": authority,
            },
            {
                "primitive": "block_argument_list",
                "token": '"Film,Serie,Documentario"',
                "old_value": {
                    "type": "string",
                    "argument": "genres",
                    "value": "Film,Serie,Documentario",
                },
                "name": "witness",
                "authority": authority,
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista target modifica: sostituisci `Film,Serie` "
                "con `Film,Serie,Documentario`.",
                source,
            ),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "STRUCTURAL_EDIT_AUTHORITY_MISSING"
    assert compiler.lossless_apply_calls == 0


def test_block_argument_source_witness_covers_only_reviewed_none_domain_binding() -> None:
    source = 'endpoint demo {\n  target "Azione";\n  witness "Azione,Avventura";\n}\n'
    bindings = [
        {"catalog": "catalog.video", "field": "genre"},
        {"catalog": "catalog.video", "field": "primary_genre"},
    ]
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "target",
                "authority": {"bindings": bindings},
            },
            {
                "primitive": "block_argument_list",
                "token": '"Azione,Avventura"',
                "old_value": {
                    "type": "string",
                    "argument": "genre",
                    "value": "Azione,Avventura",
                },
                "name": "witness",
                "authority": {"bindings": bindings},
            },
        ],
        source,
    )

    def resolve(*, lease: Any, identities: tuple[tuple[str, str, str], ...]) -> dict[str, Any]:
        assert identities == (
            ("catalog.video", "genre", "Avventura"),
            ("catalog.video", "primary_genre", "Avventura"),
        )
        reviewed = {
            "catalog": "catalog.video",
            "field": "genre",
            "literal": "Avventura",
        }
        return {
            "contract": "metis-brain-exact-reviewed-value-authority/v1",
            "context_revision": lease.snapshot.revision,
            "semantic_source_revision": _sha("semantic-source"),
            "toolchain_binding": lease.snapshot.toolchain_binding,
            "index_revision": _sha("index"),
            "outcomes": (
                {**reviewed, "status": "reviewed_exact"},
                {
                    "catalog": "catalog.video",
                    "field": "primary_genre",
                    "literal": "Avventura",
                    "status": "witness_eligible_absent",
                },
            ),
            "selections": ({**reviewed, "type": "keyword", "modifiers": []},),
            "resolutions": ({**reviewed, "review_state": "reviewed"},),
        }

    result = render_structural_existing(
        compiler=compiler,
        lease=_lease(source),
        request=_request(
            "per la lista target sostituisci `Azione` con `Azione,Avventura`.",
            source,
        ),
        record=_record(),
        grounding={
            "semantic_source_revision": _sha("semantic-source"),
            "catalogs": ["catalog.video"],
            "selections": [],
            "resolutions": [],
        },
        source=source,
        reviewed_value_resolver=resolve,
    )

    assert result is not None
    assert 'target "Azione,Avventura"' in result.candidate.source
    assert result.semantic_delta is not None
    assert result.semantic_delta["compiler_binding_identities"] == (
        ("catalog.video", "genre", "Avventura"),
        ("catalog.video", "primary_genre", "Avventura"),
    )
    assert result.semantic_delta["reviewed_selection_identities"] == (
        ("catalog.video", "genre", "Avventura"),
    )
    assert compiler.lossless_apply_calls == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("different_argument", "STRUCTURAL_EDIT_AUTHORITY_MISSING"),
        ("partial_roster", "STRUCTURAL_EDIT_AUTHORITY_MISSING"),
        ("reordered_roster", "EDIT_SURFACE_INVALID"),
        ("literal_substring", "STRUCTURAL_EDIT_AUTHORITY_MISSING"),
    ],
)
def test_block_argument_source_witness_requires_exact_contract(
    mutation: str,
    expected_code: str,
) -> None:
    witness_value = "Azione,Avventurale" if mutation == "literal_substring" else "Azione,Avventura"
    source = f'endpoint demo {{\n  target "Azione";\n  witness "{witness_value}";\n}}\n'
    bindings = [
        {"catalog": "catalog.video", "field": "genre"},
        {"catalog": "catalog.video", "field": "primary_genre"},
    ]
    witness_bindings = (
        bindings[:1]
        if mutation == "partial_roster"
        else list(reversed(bindings))
        if mutation == "reordered_roster"
        else bindings
    )
    witness_argument = "other_genre" if mutation == "different_argument" else "genre"
    compiler = _compiler(
        [
            {
                "primitive": "block_argument_list",
                "token": '"Azione"',
                "old_value": {"type": "string", "argument": "genre", "value": "Azione"},
                "name": "target",
                "authority": {"bindings": bindings},
            },
            {
                "primitive": "block_argument_list",
                "token": f'"{witness_value}"',
                "old_value": {
                    "type": "string",
                    "argument": witness_argument,
                    "value": witness_value,
                },
                "name": "witness",
                "authority": {"bindings": witness_bindings},
            },
        ],
        source,
    )

    def resolve(*, lease: Any, identities: tuple[tuple[str, str, str], ...]) -> dict[str, Any]:
        assert identities == (
            ("catalog.video", "genre", "Avventura"),
            ("catalog.video", "primary_genre", "Avventura"),
        )
        reviewed = {
            "catalog": "catalog.video",
            "field": "genre",
            "literal": "Avventura",
        }
        return {
            "contract": "metis-brain-exact-reviewed-value-authority/v1",
            "context_revision": lease.snapshot.revision,
            "semantic_source_revision": _sha("semantic-source"),
            "toolchain_binding": lease.snapshot.toolchain_binding,
            "index_revision": _sha("index"),
            "outcomes": (
                {**reviewed, "status": "reviewed_exact"},
                {
                    "catalog": "catalog.video",
                    "field": "primary_genre",
                    "literal": "Avventura",
                    "status": "witness_eligible_absent",
                },
            ),
            "selections": ({**reviewed, "type": "keyword", "modifiers": []},),
            "resolutions": ({**reviewed, "review_state": "reviewed"},),
        }

    with pytest.raises(BrainError) as raised:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request(
                "per la lista target sostituisci `Azione` con `Azione,Avventura`.",
                source,
            ),
            record=_record(),
            grounding={
                "semantic_source_revision": _sha("semantic-source"),
                "catalogs": ["catalog.video"],
                "selections": [],
                "resolutions": [],
            },
            source=source,
            reviewed_value_resolver=resolve,
        )

    assert raised.value.code == expected_code
    assert compiler.lossless_apply_calls == 0


def test_overlapping_compiler_property_spans_fail_closed() -> None:
    source = "endpoint demo {\n  first take 100;\n}\n"
    compiler = _compiler(
        [
            {
                "primitive": "take_cardinality",
                "token": "10",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 10},
                "name": "first",
            },
            {
                "primitive": "take_cardinality",
                "token": "100",
                "old_value": {"type": "positive_integer", "mode": "count", "value": 100},
                "name": "first",
            },
        ],
        source,
    )
    with pytest.raises(BrainError) as error:
        render_structural_existing(
            compiler=compiler,
            lease=_lease(source),
            request=_request("porta la take da 10 a 20.", source),
            record=_record(),
            grounding={},
            source=source,
        )
    assert error.value.code == "EDIT_SURFACE_INVALID"
    assert compiler.lossless_apply_calls == 0
