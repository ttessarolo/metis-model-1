from __future__ import annotations

from copy import deepcopy

from metis_model1.brain_bounded_edit import render_bounded_edit
from metis_model1.brain_candidate_grounding import adjudicate_candidate
from metis_model1.brain_protocol import bytes_sha256

SOURCE = """metis 0.43

// untouched header
endpoint demo.target as target_label {
  take 24 from @play-demo.video {
    include where {
      @old_field is \"old\"
    }
    order by @publication_date descending
    return response.expanded
  }
}

"""


def _grounding() -> dict:
    return {
        "status": "resolved",
        "catalogs": ["play-demo.video"],
        "context_revision": "sha256:" + "a" * 64,
        "semantic_source_revision": "sha256:" + "b" * 64,
        "output_contract": {
            "take": {"mode": "count", "value": 24, "source": "existing_source"},
            "fallback": {"mode": "none"},
        },
        "selections": [
            {
                "selection_ref": "selection:country",
                "field_ref": "field:country",
                "value_refs": ["value:italy"],
                "catalog": "play-demo.video",
                "field": "paesiorigine",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "enum", "size": 2},
                "literal": "ITALIA",
            },
            {
                "selection_ref": "selection:mood",
                "field_ref": "field:mood",
                "value_refs": ["value:romantic"],
                "catalog": "play-demo.video",
                "field": "mood",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "inline", "size": 2},
                "literal": "Romantico",
            },
        ],
        "refs": {
            "fields": {
                "field:country": {
                    "name": "paesiorigine",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "enum", "size": 2},
                },
                "field:mood": {
                    "name": "mood",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "inline", "size": 2},
                },
            },
            "values": {
                "value:italy": {
                    "field_ref": "field:country",
                    "literal": "ITALIA",
                    "state": "reviewed",
                },
                "value:romantic": {
                    "field_ref": "field:mood",
                    "literal": "Romantico",
                    "state": "reviewed",
                },
            },
        },
    }


def _plan(source: str = SOURCE) -> dict:
    return {
        "schema_version": 1,
        "operation": "edit",
        "target_endpoint": "demo.target",
        "base_sha256": bytes_sha256(source.encode()),
        "context_revision": "sha256:" + "a" * 64,
        "semantic_source_revision": "sha256:" + "b" * 64,
        "selection_refs": ["selection:country", "selection:mood"],
    }


def test_complex_edit_replaces_only_finite_body_and_preserves_order_response() -> None:
    candidate = render_bounded_edit(
        plan=_plan(),
        source=SOURCE,
        grounding=_grounding(),
        expected_context_revision="sha256:" + "a" * 64,
        expected_semantic_source_revision="sha256:" + "b" * 64,
        model_revision="model",
        adapter_sha256="adapter",
    )
    assert candidate is not None
    assert "// untouched header" in candidate.source
    assert "order by @publication_date descending" in candidate.source
    assert "return response.expanded" in candidate.source
    assert '@paesiorigine is "ITALIA"' in candidate.source
    assert '@mood is "Romantico"' in candidate.source
    assert adjudicate_candidate(candidate.source, _grounding()).ok


def test_renderer_declines_unsafe_or_unprovable_surfaces() -> None:
    cases: list[tuple[str, dict]] = []
    duplicate = SOURCE + "\nendpoint demo.target { take 1 from @play-demo.video }\n"
    cases.append((duplicate, _plan(duplicate)))
    commented = SOURCE.replace('@old_field is "old"', '// do not edit\n      @old_field is "old"')
    cases.append((commented, _plan(commented)))
    unknown_predicate = SOURCE.replace('@old_field is "old"', '@old_field matches "old"')
    cases.append((unknown_predicate, _plan(unknown_predicate)))
    wrong_response = SOURCE.replace("return response.expanded", "return response.default")
    cases.append((wrong_response, _plan(wrong_response)))
    wrong_order = SOURCE.replace(
        "order by @publication_date descending", "order by @publication_date nonsense"
    )
    cases.append((wrong_order, _plan(wrong_order)))
    for source, plan in cases:
        assert (
            render_bounded_edit(
                plan=plan,
                source=source,
                grounding=_grounding(),
                expected_context_revision="sha256:" + "a" * 64,
                expected_semantic_source_revision="sha256:" + "b" * 64,
            )
            is None
        )


def test_renderer_declines_stale_hash_revision_open_domain_and_arbitrary_refs() -> None:
    grounding = _grounding()
    plan = _plan()
    stale = deepcopy(plan)
    stale["base_sha256"] = "sha256:" + "f" * 64
    assert (
        render_bounded_edit(
            plan=stale,
            source=SOURCE,
            grounding=grounding,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_source_revision="sha256:" + "b" * 64,
        )
        is None
    )

    open_grounding = deepcopy(grounding)
    open_grounding["refs"]["fields"]["field:mood"]["domain"] = {"kind": "open", "size": 1}
    assert (
        render_bounded_edit(
            plan=plan,
            source=SOURCE,
            grounding=open_grounding,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_source_revision="sha256:" + "b" * 64,
        )
        is None
    )

    arbitrary = deepcopy(plan)
    arbitrary["selection_refs"] = ["selection:invented"]
    assert (
        render_bounded_edit(
            plan=arbitrary,
            source=SOURCE,
            grounding=grounding,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_source_revision="sha256:" + "b" * 64,
        )
        is None
    )

    stale = deepcopy(plan)
    stale["context_revision"] = "sha256:" + "c" * 64
    assert (
        render_bounded_edit(
            plan=stale,
            source=SOURCE,
            grounding=grounding,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_source_revision="sha256:" + "b" * 64,
        )
        is None
    )


def test_renderer_requires_grounding_revisions_and_bounds_rendered_source() -> None:
    for revision in ("context_revision", "semantic_source_revision"):
        grounding = _grounding()
        grounding.pop(revision)
        assert (
            render_bounded_edit(
                plan=_plan(),
                source=SOURCE,
                grounding=grounding,
                expected_context_revision="sha256:" + "a" * 64,
                expected_semantic_source_revision="sha256:" + "b" * 64,
            )
            is None
        )

    grounding = _grounding()
    grounding["refs"]["values"]["value:italy"]["literal"] = "x" * 600_000
    assert (
        render_bounded_edit(
            plan=_plan(),
            source=SOURCE,
            grounding=grounding,
            expected_context_revision="sha256:" + "a" * 64,
            expected_semantic_source_revision="sha256:" + "b" * 64,
        )
        is None
    )
