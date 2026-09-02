from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from metis_model1.brain_candidate_grounding import adjudicate_candidate
from metis_model1.brain_grounded_renderer import render_grounded_create


def _fixture() -> tuple[SimpleNamespace, SimpleNamespace]:
    request = SimpleNamespace(
        intent="create",
        expected_context_revision="sha256:" + "a" * 64,
        expected_semantic_source_revision="sha256:" + "b" * 64,
        target={
            "mode": "create",
            "relative_path": "brain-drafts/film_italiani.metis",
            "endpoint": "demo.film_italiani",
            "base_sha256": None,
        },
    )
    selections = [
        {
            "catalog": "play-demo.video",
            "field": "tipologia",
            "type": "keyword",
            "modifiers": [],
            "domain": {"kind": "inline", "size": 9},
            "literal": "Film",
        },
        {
            "catalog": "play-demo.video",
            "field": "paesiorigine",
            "type": "keyword",
            "modifiers": [],
            "domain": {"kind": "enum", "size": 3, "nature": "editorial"},
            "literal": None,
            "literals": ["ITALIA", "Italia", "italia"],
            "value_mode": "any_of",
        },
    ]
    fields = []
    for selection in selections:
        literals = (
            [selection["literal"]]
            if selection.get("literal") is not None
            else list(selection["literals"])
        )
        fields.append(
            {
                "name": selection["field"],
                "type": selection["type"],
                "modifiers": selection["modifiers"],
                "domain": selection["domain"],
                "semantic": {"state": "reviewed"},
                "values": [
                    {"literal": literal, "semantic": {"state": "reviewed"}} for literal in literals
                ],
            }
        )
    grounding = {
        "status": "resolved",
        "catalogs": ["play-demo.video"],
        "selections": selections,
        "candidates": [],
        "unresolved": [],
        "output_contract": {
            "take": {"mode": "count", "value": 24, "source": "operator_confirmed"},
            "fallback": {"mode": "none"},
        },
    }
    retrieved = SimpleNamespace(
        context={
            "language_version": "0.43",
            "semantic_schema": 2,
            "context_revision": "sha256:" + "a" * 64,
            "semantic_source_revision": "sha256:" + "b" * 64,
            "toolchain_binding": "sha256:" + "c" * 64,
            "catalog": {
                "name": "play-demo.video",
                "semantic": {"state": "reviewed"},
            },
            "fields": fields,
        },
        grounding=grounding,
    )
    return request, retrieved


def test_reviewed_finite_create_renders_exact_fast_candidate() -> None:
    request, retrieved = _fixture()
    candidate = render_grounded_create(
        request=request,
        retrieved=retrieved,
        model_revision="model-revision",
        adapter_sha256="sha256:" + "a" * 64,
    )

    assert candidate is not None
    assert candidate.generator == "grounded_renderer"
    assert (
        candidate.source
        == """metis 0.43

endpoint demo.film_italiani {
  take 24 from @play-demo.video {
    include where {
      @tipologia is "Film"
      @paesiorigine in ["ITALIA", "Italia", "italia"]
    }
    return response.default
  }
}
"""
    )
    assert adjudicate_candidate(candidate.source, retrieved.grounding).ok


def test_reviewed_create_renders_requested_endpoint_reference_losslessly() -> None:
    request, retrieved = _fixture()
    request.target["reference"] = "videoFilmItaliani"

    candidate = render_grounded_create(
        request=request,
        retrieved=retrieved,
        model_revision="model-revision",
        adapter_sha256="sha256:" + "a" * 64,
    )

    assert candidate is not None
    assert 'endpoint demo.film_italiani as "videoFilmItaliani" {' in candidate.source


def test_fast_renderer_declines_unreviewed_open_edit_and_incomplete_surfaces() -> None:
    request, retrieved = _fixture()
    mutations = []

    edit_request = deepcopy(request)
    edit_request.intent = "edit"
    mutations.append((edit_request, deepcopy(retrieved)))

    unreviewed = deepcopy(retrieved)
    unreviewed.context["fields"][0]["semantic"]["state"] = "draft"
    mutations.append((deepcopy(request), unreviewed))

    open_domain = deepcopy(retrieved)
    open_domain.grounding["selections"][0]["domain"] = {"kind": "open"}
    open_domain.context["fields"][0]["domain"] = {"kind": "open"}
    mutations.append((deepcopy(request), open_domain))

    unresolved = deepcopy(retrieved)
    unresolved.grounding["unresolved"] = ["ordina per rilevanza"]
    mutations.append((deepcopy(request), unresolved))

    for changed_request, changed_retrieved in mutations:
        assert (
            render_grounded_create(
                request=changed_request,
                retrieved=changed_retrieved,
                model_revision="model-revision",
                adapter_sha256="adapter",
            )
            is None
        )
