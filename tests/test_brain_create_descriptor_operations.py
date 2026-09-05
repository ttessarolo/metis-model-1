"""Neutral descriptor operations preserve basis and reject forged authority."""

from __future__ import annotations

import copy
import os
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_brain_technical_authority import _bindings, _fixture, _hash

from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_descriptor_operations import (
    DescriptorOperationAuthority,
    build_descriptor_operation,
    validate_descriptor_operation,
)
from metis_model1.brain_create_plan_v2 import initial_create_endpoint_skeleton
from metis_model1.brain_create_structural_authority_v2 import (
    StructuralAnchor,
    StructuralLeafEvidence,
    reviewed_descriptor_filter_index,
)
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_semantic_retrieval import LoadedProjection, Schema2SnapshotRetriever
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_technical_authority import bind_technical_authority
from metis_model1.brain_tools import BrainCompiler

POLICY = _hash("generic-operations-policy")


def _setup(suffix="alpha", *, binding=None):
    snapshot, projection, raw = _fixture(suffix, binding=binding)
    sealed = bind_technical_authority(raw, projection=projection, **_bindings(snapshot))
    retriever = Schema2SnapshotRetriever(
        lambda current: LoadedProjection(
            projection, current.revision, current.semantic_source_revision(), sealed
        )
    )
    retrieved = retriever.retrieve(
        lease=SimpleNamespace(snapshot=snapshot),
        request=SimpleNamespace(instruction="storia artica"),
    )
    retriever.close()
    semantic = reviewed_descriptor_filter_index(
        retrieved=retrieved,
        context_revision=snapshot.revision,
        semantic_revision=snapshot.semantic_source_revision(),
        toolchain_binding=snapshot.toolchain_binding,
    )
    return SimpleNamespace(
        snapshot=snapshot,
        retrieved=retrieved,
        semantic=semantic,
        base=initial_create_endpoint_skeleton("demo.generic"),
        suffix=suffix,
    )


def _authority(state, operation, *, base=None, retrieved=None, semantic=True):
    return DescriptorOperationAuthority(
        base_spec=state.base if base is None else base,
        operation=operation,
        semantic=state.semantic if semantic else None,
        retrieved=state.retrieved if retrieved is None else retrieved,
        context_revision=state.snapshot.revision,
        semantic_revision=state.snapshot.semantic_source_revision(),
        toolchain_binding=state.snapshot.toolchain_binding,
        tenant_id=state.snapshot.tenant_id,
        decision_revision=canonical_sha256(operation),
    )


def _apply(state, operation):
    authority = _authority(state, operation)
    original = copy.deepcopy(state.base)
    intent = build_descriptor_operation(authority, policy_revision=POLICY)
    assert (
        validate_descriptor_operation(intent, authority=authority, policy_revision=POLICY) is intent
    )
    assert state.base == original
    for mutation in intent.mutations:
        target = state.base["endpoint"]
        if mutation.anchor is not None:
            for segment in mutation.anchor.path:
                target = target[segment]
            assert target == mutation.anchor.fragment
        if mutation.action == "attach":
            target[mutation.member].append(copy.deepcopy(mutation.fragment))
        else:
            target[mutation.member] = copy.deepcopy(mutation.fragment)
    return authority, intent


def _add(state, *, count=24, mode="total"):
    return _apply(state, {"kind": "add_filtered_block", "count": count, "mode": mode})


def _journey(state):
    _add(state)
    _add(state, count=8)
    _, count = _apply(
        state,
        {
            "kind": "set_cardinality",
            "block_index": 0,
            "fetch_index": 0,
            "count": 12,
            "mode": "total",
        },
    )
    assert count.mutations[0].anchor.path == ("blocks", 0, "fetches", 0)
    _apply(
        state,
        {
            "kind": "order_by_field",
            "block_index": 0,
            "fetch_index": 0,
            "field": f"key_{state.suffix}",
            "direction": "ascending",
        },
    )
    _apply(
        state,
        {"kind": "return_projection", "block_index": 0, "fetch_index": 0, "projection": "detail"},
    )
    _apply(
        state,
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "empty",
            "mode": "append",
        },
    )
    return render_create_endpoint(state.base).metis_text


@pytest.mark.parametrize("suffix", ["alpha", "beta", "north", "south"])
def test_all_five_operations_are_descriptor_native_and_preserve_prior_structure(suffix):
    state = _setup(suffix)
    source = _journey(state)
    assert f"take 12 from @archive_{suffix}" in source
    assert f"order by @key_{suffix} ascending" in source
    assert "return response.detail" in source
    assert "return response fallback to block.block_1 when empty append" in source
    assert f"take 8 from @archive_{suffix}" in source
    first, second = state.base["endpoint"]["blocks"]
    assert first["fetches"][0]["clauses"] == second["fetches"][0]["clauses"]
    assert second["output"] is None
    assert [block["name"] for block in state.base["endpoint"]["blocks"]] == ["main", "block_1"]


def test_isomorphic_renaming_preserves_canonical_operation_structure():
    left, right = _setup("alpha"), _setup("beta")
    assert _journey(left).replace("alpha", "renamed") == _journey(right).replace("beta", "renamed")


def test_new_block_names_avoid_existing_names_and_do_not_rewrite_them():
    state = _setup()
    _add(state)
    _add(state)
    before = copy.deepcopy(state.base["endpoint"]["blocks"])
    _add(state)
    assert state.base["endpoint"]["blocks"][:2] == before
    assert state.base["endpoint"]["blocks"][2]["name"] == "block_2"


def test_order_append_and_projection_replace_preserve_prior_criteria_steps_and_fallbacks():
    state = _setup()
    _add(state)
    _add(state)
    _apply(
        state,
        {
            "kind": "order_by_field",
            "block_index": 0,
            "fetch_index": 0,
            "field": "key_alpha",
            "direction": "ascending",
        },
    )
    _apply(
        state,
        {
            "kind": "order_by_field",
            "block_index": 0,
            "fetch_index": 0,
            "field": "tag_alpha",
            "direction": "descending",
        },
    )
    fetch = state.base["endpoint"]["blocks"][0]["fetches"][0]
    assert fetch["order"] == [
        {"by": "field", "field": "key_alpha", "direction": "ascending"},
        {"by": "field", "field": "tag_alpha", "direction": "descending"},
    ]
    _apply(
        state,
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "below",
            "mode": "substitute",
            "threshold": 5,
        },
    )
    original = copy.deepcopy(state.base["endpoint"]["blocks"][0]["output"])
    fetch["output"] = copy.deepcopy(original)
    _apply(
        state,
        {"kind": "return_projection", "block_index": 0, "fetch_index": 0, "projection": "detail"},
    )
    assert state.base["endpoint"]["blocks"][0]["output"] == original
    assert fetch["output"] == {**original, "projection": "detail"}


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "add_filtered_block", "count": 0, "mode": "total"},
        {"kind": "add_filtered_block", "count": True, "mode": "total"},
        {"kind": "add_filtered_block", "count": 10001, "mode": "total"},
        {"kind": "add_filtered_block", "count": 12, "mode": []},
        {"kind": "add_filtered_block", "count": 12, "mode": "total", "field": "forged"},
        {
            "kind": "order_by_field",
            "block_index": 0,
            "fetch_index": 0,
            "field": "key_alpha",
            "direction": [],
        },
        {"kind": "return_projection", "block_index": 0, "fetch_index": 0, "projection": []},
        {"kind": "return_projection", "block_index": -1, "fetch_index": 0, "projection": "default"},
        {
            "kind": "return_projection",
            "block_index": True,
            "fetch_index": 0,
            "projection": "default",
        },
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "empty",
            "mode": "append",
            "threshold": 5,
        },
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "below",
            "mode": "append",
        },
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "error",
            "mode": "append",
        },
        {
            "kind": "similarity_from_input",
            "block_index": 0,
            "fetch_index": 0,
            "profile": [],
        },
    ],
)
def test_operation_rosters_and_scalar_contracts_fail_closed(operation):
    with pytest.raises(BrainError):
        _authority(_setup(), operation)


def test_original_authority_is_deeply_immutable_and_defensively_detached():
    state = _setup()
    operation = {"kind": "add_filtered_block", "count": 12, "mode": "total"}
    authority = _authority(state, operation)
    expected = build_descriptor_operation(authority, policy_revision=POLICY)
    operation["count"] = 99
    state.base["endpoint"]["name"] = "changed.other"
    state.retrieved.context["technical_authority"]["catalogs"][0]["id_field"] = "forged"
    assert build_descriptor_operation(authority, policy_revision=POLICY) == expected
    with pytest.raises(TypeError):
        authority.base_spec["endpoint"]["name"] = "forged"
    with pytest.raises(TypeError):
        authority.operation["count"] = 99


def test_candidate_literal_leaf_origin_anchor_and_decision_tampering_are_rejected():
    state = _setup()
    _add(state)
    operation = {
        "kind": "set_cardinality",
        "block_index": 0,
        "fetch_index": 0,
        "count": 12,
        "mode": "total",
    }
    authority = _authority(state, operation)
    intent = build_descriptor_operation(authority, policy_revision=POLICY)
    mutation = intent.mutations[0]
    forged = [
        replace(mutation, fragment={"mode": "total", "value": 13}),
        replace(
            mutation,
            leaf_evidence=(
                StructuralLeafEvidence("/mode", "policy", {"policy_revision": POLICY}),
                *mutation.leaf_evidence[1:],
            ),
        ),
        replace(
            mutation,
            anchor=StructuralAnchor(("blocks", 1, "fetches", 0), "fetch", mutation.anchor.fragment),
        ),
    ]
    for changed in forged:
        with pytest.raises(BrainError):
            validate_descriptor_operation(
                replace(intent, mutations=(changed,)), authority=authority, policy_revision=POLICY
            )
    with pytest.raises(BrainError):
        validate_descriptor_operation(
            intent,
            authority=replace(authority, decision_revision=_hash("new-decision")),
            policy_revision=POLICY,
        )


def test_original_semantic_index_must_be_reopened_against_retrieval():
    state = _setup()
    authority = _authority(state, {"kind": "add_filtered_block", "count": 12, "mode": "total"})
    with pytest.raises(BrainError):
        build_descriptor_operation(
            replace(
                authority, semantic=replace(authority.semantic, proof_revision=_hash("forged"))
            ),
            policy_revision=POLICY,
        )
    with pytest.raises(BrainError):
        build_descriptor_operation(replace(authority, semantic=None), policy_revision=POLICY)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda context: context.pop("technical_authority"),
        lambda context: context["fields"][0]["semantic"].update(state="draft"),
        lambda context: context["catalog"]["semantic"].update(state="draft"),
        lambda context: context["fields"][0].update(type="number"),
        lambda context: context["technical_authority"].update(sha256=_hash("forged")),
    ],
)
def test_sort_requires_independent_reviewed_and_technical_authority(mutation):
    state = _setup()
    _add(state)
    changed = replace(state.retrieved, context=copy.deepcopy(state.retrieved.context))
    mutation(changed.context)
    authority = _authority(
        state,
        {
            "kind": "order_by_field",
            "block_index": 0,
            "fetch_index": 0,
            "field": "key_alpha",
            "direction": "ascending",
        },
        retrieved=changed,
    )
    with pytest.raises(BrainError):
        build_descriptor_operation(authority, policy_revision=POLICY)


def test_count_and_fallback_refuse_unbound_targets_implicit_deletions_and_cycles():
    state = _setup()
    _add(state)
    _add(state)
    for operation in (
        {
            "kind": "set_cardinality",
            "block_index": 0,
            "fetch_index": 3,
            "count": 10,
            "mode": "total",
        },
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 0,
            "trigger": "empty",
            "mode": "append",
        },
    ):
        with pytest.raises(BrainError):
            build_descriptor_operation(_authority(state, operation), policy_revision=POLICY)
    _apply(
        state,
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "empty",
            "mode": "append",
        },
    )
    for operation in (
        {
            "kind": "same_draft_fallback",
            "block_index": 1,
            "target_index": 0,
            "trigger": "below",
            "mode": "substitute",
            "threshold": 5,
        },
        {
            "kind": "same_draft_fallback",
            "block_index": 0,
            "target_index": 1,
            "trigger": "empty",
            "mode": "substitute",
        },
    ):
        with pytest.raises(BrainError):
            build_descriptor_operation(_authority(state, operation), policy_revision=POLICY)
    state.base["endpoint"]["blocks"][0]["fetches"][0]["over_fetch"] = 2
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(
                state,
                {
                    "kind": "set_cardinality",
                    "block_index": 0,
                    "fetch_index": 0,
                    "count": 10,
                    "mode": "page_default",
                },
            ),
            policy_revision=POLICY,
        )


@pytest.mark.parametrize("suffix", ["alpha", "beta", "north", "south"])
def test_filtered_page_is_an_explicit_emitted_variant_without_rewriting_pools(suffix):
    state = _setup(suffix)
    _add(state)
    # A pre-existing source may contain helper pools only. It is not the output
    # of the new add-block operation, which always binds an emitted response.
    state.base["endpoint"]["variants"] = []
    original_blocks = copy.deepcopy(state.base["endpoint"]["blocks"])
    authority, intent = _apply(state, {"kind": "add_filtered_page", "count": 24})
    assert len(intent.mutations) == 1
    mutation = intent.mutations[0]
    assert (mutation.member, mutation.fragment_type, mutation.anchor) == (
        "variants",
        "variant",
        None,
    )
    assert state.base["endpoint"]["blocks"] == original_blocks
    page = state.base["endpoint"]["variants"][0]
    assert page["name"] == "page_1" and page["activation"] is None and page["empty"] is False
    assert page["fetches"][0]["cardinality"] == {"mode": "page_default", "value": 24}
    assert page["fetches"][0]["clauses"] == original_blocks[0]["fetches"][0]["clauses"]
    source = render_create_endpoint(state.base).metis_text
    assert f"take page default 24 from @archive_{suffix}" in source
    assert f"take 24 from @archive_{suffix}" in source
    assert (
        validate_descriptor_operation(intent, authority=authority, policy_revision=POLICY) is intent
    )
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(state, {"kind": "add_filtered_page", "count": 12}), policy_revision=POLICY
        )


@pytest.mark.parametrize("pagination", ["snapshot", "windowed"])
def test_filtered_page_refuses_incompatible_existing_pagination_modes(pagination):
    state = _setup()
    state.base["endpoint"]["params"]["paginate"] = pagination
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(state, {"kind": "add_filtered_page", "count": 24}), policy_revision=POLICY
        )


def test_page_names_are_collision_free_and_named_block_page_is_not_authorized():
    state = _setup()
    _add(state)
    state.base["endpoint"]["variants"] = []  # Explicit pre-existing pool-only fixture.
    state.base["endpoint"]["blocks"][0]["name"] = "page_1"
    for operation in (
        {"kind": "add_filtered_block", "count": 24, "mode": "page_default"},
        {
            "kind": "set_cardinality",
            "block_index": 0,
            "fetch_index": 0,
            "count": 24,
            "mode": "page_default",
        },
        {"kind": "add_filtered_page", "count": 24, "mode": "page_default"},
    ):
        with pytest.raises(BrainError):
            build_descriptor_operation(_authority(state, operation), policy_revision=POLICY)
    _apply(state, {"kind": "add_filtered_page", "count": 24})
    assert state.base["endpoint"]["variants"][0]["name"] == "page_2"


def test_add_filtered_block_binds_first_and_subsequent_blocks_to_the_only_response_root():
    state = _setup()
    _, first = _add(state)
    assert len(first.mutations) == 2
    assert [item.member for item in first.mutations] == ["blocks", "variants"]
    variant = state.base["endpoint"]["variants"][0]
    assert variant["activation"] is None and variant["empty"] is False
    assert variant["uses"] == [{"kind": "direct", "block": "main"}]
    original_variant = copy.deepcopy(variant)
    authority, second = _add(state, count=12)
    assert len(second.mutations) == 2
    assert [item.member for item in second.mutations] == ["blocks", "uses"]
    assert second.mutations[1].anchor == StructuralAnchor(
        ("variants", 0), "variant", original_variant
    )
    assert variant["uses"] == [
        {"kind": "direct", "block": "main"},
        {"kind": "direct", "block": "block_1"},
    ]
    forged = copy.deepcopy(second.mutations[1].fragment)
    forged["block"] = "main"
    with pytest.raises(BrainError):
        validate_descriptor_operation(
            replace(
                second,
                mutations=(second.mutations[0], replace(second.mutations[1], fragment=forged)),
            ),
            authority=authority,
            policy_revision=POLICY,
        )


@pytest.mark.parametrize(
    "change", ["multiple", "conditional", "empty", "parametric_use", "parametric_pool"]
)
def test_add_filtered_block_never_guesses_an_ambiguous_or_parametric_response_target(change):
    state = _setup()
    _add(state)
    variant = state.base["endpoint"]["variants"][0]
    if change == "multiple":
        alternate = copy.deepcopy(variant)
        alternate["name"] = "alternate"
        state.base["endpoint"]["variants"].append(alternate)
    elif change == "conditional":
        variant["activation"] = {
            "kind": "compare",
            "left": {"kind": "input", "name": "flag"},
            "op": "not_empty",
        }
    elif change == "empty":
        variant["empty"] = True
        variant["uses"] = []
    elif change == "parametric_pool":
        state.base["endpoint"]["blocks"][0]["parameters"] = [
            {
                "name": "choice",
                "required": False,
                "type": "keyword",
                "default": None,
            }
        ]
    else:
        variant["uses"] = [{"kind": "instance", "block": "main", "alias": "instance", "args": []}]
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(state, {"kind": "add_filtered_block", "count": 12, "mode": "total"}),
            policy_revision=POLICY,
        )


def _similarity_operation(suffix="alpha"):
    return {
        "kind": "similarity_from_input",
        "block_index": 0,
        "fetch_index": 0,
        "profile": f"related_{suffix}",
    }


@pytest.mark.parametrize("profile", ["expanded", "other_tenant_profile", "everything"])
def test_return_projection_never_invents_a_profile_name(profile):
    state = _setup()
    _add(state)
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(
                state,
                {
                    "kind": "return_projection",
                    "block_index": 0,
                    "fetch_index": 0,
                    "projection": profile,
                },
            ),
            policy_revision=POLICY,
        )


def test_return_projection_needs_current_technical_roster_and_preserves_take_steps():
    state = _setup()
    _add(state)
    fetch = state.base["endpoint"]["blocks"][0]["fetches"][0]
    fetch["output"] = {"projection": "default", "steps": [{"kind": "shuffle"}], "fallbacks": []}
    original = copy.deepcopy(fetch["output"])
    op = {"kind": "return_projection", "block_index": 0, "fetch_index": 0, "projection": "detail"}
    context = copy.deepcopy(state.retrieved.context)
    context.pop("technical_authority")
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(state, op, retrieved=replace(state.retrieved, context=context)),
            policy_revision=POLICY,
        )
    _, intent = _apply(state, op)
    assert fetch["output"] == {**original, "projection": "detail"}
    assert intent.mutations[0].anchor.path == ("blocks", 0, "fetches", 0)
    evidence = {leaf.json_pointer: leaf for leaf in intent.mutations[0].leaf_evidence}
    assert evidence["/projection"].origin == "pinned_technical"
    assert evidence["/steps/0/kind"].origin == "basis"
    _apply(state, {**op, "projection": "default"})
    assert fetch["output"] == original


@pytest.mark.parametrize("suffix", ["alpha", "beta", "north", "south"])
def test_similarity_declares_exact_seed_producer_without_materialized_values(suffix):
    state = _setup(suffix)
    _add(state)
    original_fetch = copy.deepcopy(state.base["endpoint"]["blocks"][0]["fetches"][0])
    authority, intent = _apply(state, _similarity_operation(suffix))
    assert len(intent.mutations) == 3
    assert [item.member for item in intent.mutations] == ["inputs", "context", "clauses"]
    endpoint = state.base["endpoint"]
    assert endpoint["inputs"] == [
        {
            "name": "seed_id_1",
            "type": "keyword",
            "required": True,
            "not_empty": True,
            "default": None,
        }
    ]
    seed = endpoint["context"][0]
    assert seed["name"] == "seed_record_1"
    assert seed["fetch"]["cardinality"] == {"mode": "total", "value": 1}
    assert seed["fetch"]["from"] == {"kind": "catalog", "catalog": f"archive_{suffix}"}
    assert seed["fetch"]["clauses"][0]["where"] == [
        {
            "op": "eq",
            "field": f"key_{suffix}",
            "value": {"kind": "input", "name": "seed_id_1"},
        }
    ]
    fetch = endpoint["blocks"][0]["fetches"][0]
    assert fetch["clauses"][:-1] == original_fetch["clauses"]
    assert fetch["order"] == original_fetch["order"]
    assert fetch["clauses"][-1] == {
        "intent": "include",
        "where": [
            {
                "op": "similar",
                "form": "record",
                "profile": f"related_{suffix}",
                "target": {"kind": "ctx", "segments": ["seed_record_1"]},
            }
        ],
    }
    technical_leaves = [
        leaf
        for mutation in intent.mutations
        for leaf in mutation.leaf_evidence
        if leaf.origin == "pinned_technical"
    ]
    assert len(technical_leaves) == 4
    assert all(
        leaf.identity["decision_revision"] == authority.decision_revision
        for leaf in technical_leaves
    )
    assert (
        f"similar related_{suffix} to context.seed_record_1"
        in render_create_endpoint(state.base).metis_text
    )


def test_similarity_symbols_avoid_prior_declarations_and_validation_binds_every_dependency():
    state = _setup()
    _add(state)
    state.base["endpoint"]["inputs"].append(
        {
            "name": "seed_id_1",
            "type": "keyword",
            "required": False,
            "not_empty": False,
            "default": None,
        }
    )
    state.base["endpoint"]["context"].append(
        {
            "kind": "fetch",
            "name": "seed_record_1",
            "fetch": copy.deepcopy(state.base["endpoint"]["blocks"][0]["fetches"][0]),
        }
    )
    authority, intent = _apply(state, _similarity_operation())
    assert intent.mutations[0].fragment["name"] == "seed_id_2"
    assert intent.mutations[1].fragment["name"] == "seed_record_2"
    for index, mutate in (
        (
            0,
            lambda item: item.update(default={"kind": "lit", "lexical": "text", "value": "forged"}),
        ),
        (1, lambda item: item["fetch"]["cardinality"].update(value=2)),
        (1, lambda item: item["fetch"]["from"].update(catalog="other.archive")),
        (2, lambda item: item["where"][0]["target"].update(segments=["seed_record_1"])),
    ):
        mutation = intent.mutations[index]
        forged_fragment = copy.deepcopy(mutation.fragment)
        mutate(forged_fragment)
        mutations = list(intent.mutations)
        mutations[index] = replace(mutation, fragment=forged_fragment)
        with pytest.raises(BrainError):
            validate_descriptor_operation(
                replace(intent, mutations=tuple(mutations)),
                authority=authority,
                policy_revision=POLICY,
            )
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(state, _similarity_operation()), policy_revision=POLICY
        )


@pytest.mark.parametrize(
    "change", ["missing", "capability", "identity", "identity_type", "profile", "digest"]
)
def test_similarity_requires_exact_current_technical_roles(change):
    state = _setup()
    _add(state)
    context = copy.deepcopy(state.retrieved.context)
    technical = context["technical_authority"]
    declaration = technical["catalogs"][0]
    if change == "missing":
        context.pop("technical_authority")
    elif change == "capability":
        declaration["capabilities"].remove("record-similarity")
    elif change == "identity":
        declaration["id_field"] = None
    elif change == "identity_type":
        declaration["fields"][0]["type"] = "text"
    elif change == "profile":
        declaration["similarity_profiles"] = []
    else:
        technical["sha256"] = _hash("forged")
    if change not in {"missing", "digest"}:
        technical["sha256"] = canonical_sha256(
            {key: value for key, value in technical.items() if key != "sha256"}
        )
    with pytest.raises(BrainError):
        build_descriptor_operation(
            _authority(
                state, _similarity_operation(), retrieved=replace(state.retrieved, context=context)
            ),
            policy_revision=POLICY,
        )


@pytest.mark.parametrize("suffix", ["north", "south"])
def test_first_and_added_block_have_real_emitted_root_bindings_in_the_pinned_ir(suffix):
    root, node = (
        os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT"),
        os.environ.get("METIS_MODEL1_NODE"),
    )
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    compiler = BrainCompiler(metis_root=Path(root), node_path=Path(node))
    try:
        state = _setup(suffix, binding=compiler.toolchain_binding)
        for count, expected in ((24, ["main"]), (12, ["main", "block_1"])):
            _add(state, count=count)
            result = compiler.compile_candidate(
                lease=OperationLease(
                    session_id="s" * 43,
                    client_id="generic-emission-test",
                    tenant_alias=state.snapshot.tenant_alias,
                    capabilities=frozenset({"compile"}),
                    snapshot=state.snapshot,
                    cancellation=threading.Event(),
                ),
                source=render_create_endpoint(state.base).metis_text,
                filename="brain-drafts/generic.metis",
                endpoint="demo.generic",
            )
            assert result.receipt["status"] == result.receipt["compiler"]["status"] == "ok", (
                result.receipt["compiler"]
            )
            assert result.ir is not None
            assert len(result.ir["variants"]) == 1, result.ir
            assert [use["ref"] for use in result.ir["variants"][0]["uses"]] == expected
            assert [block["name"] for block in result.ir["blocks"]] == expected
            assert all(block["takes"] for block in result.ir["blocks"])
    finally:
        compiler.close()


@pytest.mark.parametrize("suffix", ["north", "south"])
def test_filtered_page_is_an_emitted_root_in_the_real_pinned_ir(suffix):
    root, node = (
        os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT"),
        os.environ.get("METIS_MODEL1_NODE"),
    )
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    compiler = BrainCompiler(metis_root=Path(root), node_path=Path(node))
    try:
        state = _setup(suffix, binding=compiler.toolchain_binding)
        _apply(state, {"kind": "add_filtered_page", "count": 24})
        result = compiler.compile_candidate(
            lease=OperationLease(
                session_id="s" * 43,
                client_id="generic-page-test",
                tenant_alias=state.snapshot.tenant_alias,
                capabilities=frozenset({"compile"}),
                snapshot=state.snapshot,
                cancellation=threading.Event(),
            ),
            source=render_create_endpoint(state.base).metis_text,
            filename="brain-drafts/generic.metis",
            endpoint="demo.generic",
        )
        assert result.receipt["status"] == result.receipt["compiler"]["status"] == "ok", (
            result.receipt["compiler"]
        )
        assert result.ir is not None
        assert len(result.ir["variants"]) == 1, result.ir
        assert result.ir["variants"][0]["name"] == "page_1"
        assert len(result.ir["variants"][0]["takes"]) == 1
        assert result.ir["blocks"] == []
    finally:
        compiler.close()


def test_named_block_page_default_is_explicitly_rejected_by_the_real_pin():
    root, node = (
        os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT"),
        os.environ.get("METIS_MODEL1_NODE"),
    )
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    compiler = BrainCompiler(metis_root=Path(root), node_path=Path(node))
    try:
        state = _setup("negative_page", binding=compiler.toolchain_binding)
        _add(state)
        # Reproduce the former bug as a negative compiler probe, not an allowed operation.
        state.base["endpoint"]["blocks"][0]["fetches"][0]["cardinality"]["mode"] = "page_default"
        result = compiler.compile_candidate(
            lease=OperationLease(
                session_id="s" * 43,
                client_id="invalid-named-block-page-test",
                tenant_alias=state.snapshot.tenant_alias,
                capabilities=frozenset({"compile"}),
                snapshot=state.snapshot,
                cancellation=threading.Event(),
            ),
            source=render_create_endpoint(state.base).metis_text,
            filename="brain-drafts/generic.metis",
            endpoint="demo.generic",
        )
        assert result.receipt["status"] == result.receipt["compiler"]["status"] == "invalid", (
            result.receipt["compiler"]
        )
        assert any(
            "root endpoint/variant" in diagnostic["message"]
            for diagnostic in result.receipt["compiler"]["diagnostics"]
        ), result.receipt["compiler"]["diagnostics"]
    finally:
        compiler.close()


@pytest.mark.parametrize("suffix", ["north", "south"])
def test_similarity_seed_producer_compiles_with_the_real_pin_on_renamed_tenants(suffix):
    root, node = (
        os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT"),
        os.environ.get("METIS_MODEL1_NODE"),
    )
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    compiler = BrainCompiler(metis_root=Path(root), node_path=Path(node))
    try:
        state = _setup(suffix, binding=compiler.toolchain_binding)
        _add(state)
        _apply(state, _similarity_operation(suffix))
        result = compiler.compile_candidate(
            lease=OperationLease(
                session_id="s" * 43,
                client_id="generic-similarity-test",
                tenant_alias=state.snapshot.tenant_alias,
                capabilities=frozenset({"compile"}),
                snapshot=state.snapshot,
                cancellation=threading.Event(),
            ),
            source=render_create_endpoint(state.base).metis_text,
            filename="brain-drafts/generic.metis",
            endpoint="demo.generic",
        )
        assert result.receipt["status"] == result.receipt["compiler"]["status"] == "ok", (
            result.receipt["compiler"]
        )
        assert result.manifest is not None and result.ir is not None
    finally:
        compiler.close()


@pytest.mark.parametrize("suffix", ["north", "south"])
def test_five_operation_journey_compiles_with_the_real_pin_on_renamed_tenants(suffix):
    root, node = (
        os.environ.get("METIS_MODEL1_BRAIN_METIS_ROOT"),
        os.environ.get("METIS_MODEL1_NODE"),
    )
    if root is None or node is None:
        pytest.skip("isolated pinned Metis test authority is unavailable")
    metis_root, node_path = Path(root), Path(node)
    assert metis_root.is_dir() and node_path.is_file(), "configured test authority is unavailable"
    compiler = BrainCompiler(metis_root=metis_root, node_path=node_path)
    try:
        state = _setup(suffix, binding=compiler.toolchain_binding)
        source = _journey(state)
        result = compiler.compile_candidate(
            lease=OperationLease(
                session_id="s" * 43,
                client_id="generic-operations-test",
                tenant_alias=state.snapshot.tenant_alias,
                capabilities=frozenset({"compile"}),
                snapshot=state.snapshot,
                cancellation=threading.Event(),
            ),
            source=source,
            filename="brain-drafts/generic.metis",
            endpoint="demo.generic",
        )
        assert result.receipt["status"] == result.receipt["compiler"]["status"] == "ok", (
            result.receipt["compiler"]
        )
        assert result.manifest is not None and result.ir is not None
        assert len(result.ir["variants"]) == 1
        assert [use["ref"] for use in result.ir["variants"][0]["uses"]] == ["main", "block_1"]
    finally:
        compiler.close()
