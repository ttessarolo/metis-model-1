import json
from pathlib import Path

import pytest

from metis_model1.closure import (
    PINNED_REVISION,
    ClosureError,
    build_manifest,
    compute_build_input_inventory,
    inventory_from_ls_tree,
    validate_manifest,
)

ROOT = Path(__file__).parents[1]
METIS = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
requires_metis_checkout = pytest.mark.skipif(
    not (METIS / ".git").exists(),
    reason="pinned Metis checkout is required for the Git-object anchor",
)


def test_synthetic_inventory_rejects_duplicate_paths_and_oids() -> None:
    row = "a" * 40 + "\texamples/play-prod-v2/a.metis"
    assert len(inventory_from_ls_tree([row])) == 1
    with pytest.raises(ClosureError, match="duplicate paths"):
        inventory_from_ls_tree([row, row])
    with pytest.raises(ClosureError, match="duplicate blob oids"):
        inventory_from_ls_tree(
            [
                row,
                "a" * 40 + "\texamples/play-prod-v2/b.metis",
            ]
        )


@requires_metis_checkout
def test_manifest_denominators_fail_closed_on_mutation() -> None:
    manifest = build_manifest(METIS, ROOT / "manifests/benchmark-plan.json")
    validate_manifest(manifest)
    mutated = json.loads(json.dumps(manifest))
    mutated["counts"]["gaps"] = 1
    with pytest.raises(ClosureError, match="incomplete"):
        validate_manifest(mutated)
    mutated = json.loads(json.dumps(manifest))
    mutated["tasks"][0]["closure_ref"] = "task-local"
    with pytest.raises(ClosureError, match="shared whole-tenant"):
        validate_manifest(mutated)
    mutated = json.loads(json.dumps(manifest))
    inputs = mutated["shared_closures"][0]["inputs"]
    inputs[1]["path"] = inputs[0]["path"]
    with pytest.raises(ClosureError, match="duplicate paths"):
        validate_manifest(mutated)
    mutated = json.loads(json.dumps(manifest))
    inputs = mutated["shared_closures"][0]["inputs"]
    inputs[1]["blob_oid"] = inputs[0]["blob_oid"]
    with pytest.raises(ClosureError, match="duplicate blob oids"):
        validate_manifest(mutated)
    mutated = json.loads(json.dumps(manifest))
    mutated["tasks"][0]["leakage_group_id"] = "sha256:" + "b" * 64
    with pytest.raises(ClosureError, match="leakage-group drift"):
        validate_manifest(mutated)
    mutated = json.loads(json.dumps(manifest))
    task_paths = {task["source_path"] for task in mutated["tasks"]}
    non_task = next(
        entry
        for entry in mutated["shared_closures"][0]["inputs"]
        if entry["path"] not in task_paths
    )
    non_task["blob_oid"] = "f" * 40
    with pytest.raises(ClosureError, match="identity is not content-derived"):
        validate_manifest(mutated)


@requires_metis_checkout
def test_manifest_rejects_poisoned_plan_source_oid(tmp_path: Path) -> None:
    plan = json.loads((ROOT / "manifests/benchmark-plan.json").read_text(encoding="utf-8"))
    plan["slice_30"]["tasks"][0]["source_blob_oid"] = "0" * 40
    poisoned = tmp_path / "benchmark-plan.json"
    poisoned.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ClosureError, match="source_blob_oid mismatch"):
        build_manifest(METIS, poisoned, PINNED_REVISION)


@requires_metis_checkout
def test_tracked_manifest_recomputes_against_pinned_git_objects() -> None:
    manifest_path = ROOT / "manifests/slice-30-closure.json"
    tracked = json.loads(manifest_path.read_text(encoding="utf-8"))
    recomputed = build_manifest(METIS, ROOT / "manifests/benchmark-plan.json", PINNED_REVISION)
    assert tracked == recomputed
    assert len(compute_build_input_inventory(METIS, PINNED_REVISION)) == 201
