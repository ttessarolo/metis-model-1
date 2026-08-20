from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1.dataset import (
    build_dataset,
    build_split_manifest,
    dataset_manifest,
    load_schema,
    validate_dataset,
    validate_example,
    write_dataset_jsonl,
)
from metis_model1.provenance import (
    NonJsonValueError,
    canonical_json_bytes,
    canonical_json_hash,
    derived_asset_id,
    example_id,
    source_asset_id,
)

ROOT = Path(__file__).resolve().parents[1]


def fixture() -> dict:
    return json.loads(
        (ROOT / "examples/dataset-example.synthetic.json").read_text(encoding="utf-8")
    )


def test_synthetic_fixture_is_exact_schema_and_semantically_valid() -> None:
    row = fixture()
    assert Draft202012Validator(load_schema()).is_valid(row)
    assert validate_example(row) == []
    assert validate_dataset([row]) == []


def test_canonical_hash_and_asset_ids_are_deterministic() -> None:
    value = {"z": ["é", 2], "a": True}
    assert canonical_json_bytes(value) == b'{"a":true,"z":["\xc3\xa9",2]}'
    assert canonical_json_hash(value) == canonical_json_hash({"a": True, "z": ["é", 2]})
    source = source_asset_id("synthetic/repo", "a" * 40, "fixtures/a.metis", b"hello")
    content_hash = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert source == source_asset_id(
        "synthetic/repo", "a" * 40, "fixtures/a.metis", "sha256:" + content_hash
    )
    assert source != source_asset_id("synthetic/repo", "a" * 40, "fixtures/a.metis", content_hash)
    assert source != source_asset_id("synthetic/repo", "b" * 40, "fixtures/a.metis", b"hello")
    derived = derived_asset_id("fixture-generator", "1", {"mode": "safe"}, [source])
    assert derived == derived_asset_id("fixture-generator", "1", {"mode": "safe"}, [source])
    assert example_id(1, {"request": "x"}, {"source": "y"}) == example_id(
        1, {"request": "x"}, {"source": "y"}
    )


def test_canonical_codec_rejects_nan_and_non_json_values() -> None:
    with pytest.raises(NonJsonValueError):
        canonical_json_bytes({"value": math.nan})
    with pytest.raises(NonJsonValueError):
        canonical_json_bytes({"value": {"not": "a", "set": {1, 2}}})


def test_dataset_rejects_duplicate_id_and_cross_split_parent_or_group() -> None:
    first = fixture()
    duplicate = deepcopy(first)
    assert any("duplicate example_id" in error for error in validate_dataset([first, duplicate]))

    second = deepcopy(first)
    second["split"] = "dev"
    second["input"] = {"request": "different"}
    second["output"] = {"source": "different"}
    second["example_id"] = example_id(1, second["input"], second["output"])
    errors = validate_dataset([first, second])
    assert any("provenance parent crosses split" in error for error in errors)
    assert any("leakage_group crosses split" in error for error in errors)


def test_example_parent_must_stay_with_child_split_regardless_of_row_order() -> None:
    parent = fixture()
    child = deepcopy(parent)
    child["input"] = {"request": "child synthetic request"}
    child["output"] = {
        "assistant_content": 'property child { value: "sunny" }',
        "source": 'property child { value: "sunny" }',
    }
    child["messages"][-1]["content"] = child["output"]["assistant_content"]
    child["example_id"] = example_id(1, child["input"], child["output"])
    child["provenance"] = {
        **child["provenance"],
        "parents": [parent["example_id"]],
        "leakage_group": "synthetic/child",
    }
    child["split"] = "dev"

    for rows in ([child, parent], [parent, child]):
        errors = validate_dataset(rows)
        assert any("provenance parent crosses split" in error for error in errors)
        assert any("parent example" in error for error in errors)
        assert any("share the child leakage_group" in error for error in errors)

    child["split"] = parent["split"]
    for rows in ([child, parent], [parent, child]):
        errors = validate_dataset(rows)
        assert not any("crosses split" in error for error in errors)
        assert any("share the child leakage_group" in error for error in errors)

    child["provenance"]["leakage_group"] = parent["provenance"]["leakage_group"]
    assert validate_dataset([child, parent]) == []
    assert validate_dataset([parent, child]) == []


def test_positive_example_rejects_pending_or_missing_semantic_oracle() -> None:
    pending = fixture()
    pending["oracles"][4]["result"] = "pending"
    assert any("pending" in error for error in validate_example(pending))

    missing = fixture()
    missing["oracles"] = [oracle for oracle in missing["oracles"] if oracle["name"] != "semantic"]
    assert any("semantic or human" in error for error in validate_example(missing))


def test_oracle_polarity_and_family_registry_are_fail_closed() -> None:
    failed = fixture()
    failed["oracles"][0]["result"] = "fail"
    assert any("every applicable oracle" in error for error in validate_example(failed))

    undeclared = fixture()
    evidence_hash = "sha256:" + "9" * 64
    undeclared["oracles"].append(
        {
            "name": "human",
            "applicable": True,
            "result": "pass",
            "evidence_hash": evidence_hash,
        }
    )
    assert any("undeclared" in error for error in validate_example(undeclared))


def test_non_applicable_oracle_rejects_evidence_and_wrong_result() -> None:
    with_evidence = fixture()
    with_evidence["oracles"][0] = {
        "name": "parse",
        "applicable": False,
        "result": "not_applicable",
        "evidence_hash": "sha256:" + "1" * 64,
    }
    assert any("must not have evidence" in error for error in validate_example(with_evidence))

    wrong_result = fixture()
    wrong_result["oracles"][0] = {
        "name": "parse",
        "applicable": False,
        "result": "pass",
        "evidence_hash": None,
    }
    assert any("must be not_applicable" in error for error in validate_example(wrong_result))


def test_f2_generic_structural_and_semantic_oracles_are_rejected() -> None:
    row = fixture()
    row["task_family"] = "F-2"
    row["input"] = {"request": "Edit the synthetic weather property minimally"}
    row["output"] = {
        "assistant_content": "replace sunny with cloudy",
        "patch": "replace sunny with cloudy",
    }
    row["example_id"] = example_id(1, row["input"], row["output"])
    row["oracles"] = [
        oracle for oracle in row["oracles"] if oracle["name"] in {"parse", "semantic"}
    ]
    errors = validate_example(row)
    assert any("patch_minimality" in error for error in errors)
    assert any("compile" in error for error in errors)


def test_prohibited_sensitivity_and_non_pass_structural_oracle_are_fail_closed() -> None:
    row = fixture()
    row["sensitivity"] = "prohibited"
    assert validate_example(row)
    row = fixture()
    row["oracles"][0]["result"] = "fail"
    assert any("every applicable oracle" in error for error in validate_example(row))


def test_manifest_counts_and_jsonl_hash_are_deterministic() -> None:
    first = fixture()
    second = deepcopy(first)
    second["input"] = {"request": "second synthetic request"}
    second["output"] = {
        "assistant_content": 'property second { value: "sunny" }',
        "source": 'property second { value: "sunny" }',
    }
    second["messages"][-1]["content"] = second["output"]["assistant_content"]
    second["example_id"] = example_id(1, second["input"], second["output"])
    rows, manifest = build_dataset([second, first])
    assert [row["example_id"] for row in rows] == sorted(row["example_id"] for row in rows)
    assert manifest["example_count"] == 2
    assert manifest["counts_by_split"]["train"] == 2
    assert validate_dataset(rows, manifest) == []
    assert manifest == dataset_manifest(list(reversed(rows)))
    split = build_split_manifest(rows)
    assert split["splits"]["train"]["example_ids"] == manifest["example_ids"]


def test_dataset_manifest_rejects_wrong_split_manifest_id_and_accepts_exact_id() -> None:
    row = fixture()
    split_manifest_id = build_split_manifest([row])["split_manifest_id"]
    manifest = dataset_manifest([row], split_manifest_id=split_manifest_id)
    assert manifest["split_manifest_id"] == split_manifest_id

    with pytest.raises(ValueError, match="does not match the deterministic split manifest"):
        dataset_manifest([row], split_manifest_id="sha256:" + "0" * 64)


def test_atomic_writer_rejects_destination_escape_and_symlink(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    with pytest.raises(ValueError, match="escapes"):
        write_dataset_jsonl([fixture()], "../escape.jsonl", artifact_root=artifact_root)

    target = artifact_root / "linked.jsonl"
    artifact_root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.jsonl"
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        write_dataset_jsonl([fixture()], target, artifact_root=artifact_root)

    linked_component = artifact_root / "linked-component"
    linked_component.symlink_to(tmp_path / "outside-directory", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        write_dataset_jsonl(
            [fixture()], "linked-component/dataset.jsonl", artifact_root=artifact_root
        )

    output = write_dataset_jsonl([fixture()], "dataset.jsonl", artifact_root=artifact_root)
    assert output.read_bytes().endswith(b"\n")
    repeat = write_dataset_jsonl([fixture()], "dataset.jsonl", artifact_root=artifact_root)
    assert output.read_bytes() == repeat.read_bytes()


def test_atomic_writer_rejects_tracked_repository_destination_and_non_jsonl_suffix(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="tracked repository paths"):
        write_dataset_jsonl([fixture()], "tracked.jsonl", artifact_root=ROOT)

    with pytest.raises(ValueError, match=r"must be a \.jsonl file"):
        write_dataset_jsonl([fixture()], "dataset.json", artifact_root=tmp_path)


def test_accepted_positive_output_must_match_final_assistant_target() -> None:
    drifted_output = fixture()
    drifted_output["output"]["assistant_content"] = 'property weather { value: "cloudy" }'
    drifted_output["example_id"] = example_id(1, drifted_output["input"], drifted_output["output"])
    assert any("assistant_content" in error for error in validate_example(drifted_output))

    drifted_message = fixture()
    drifted_message["messages"][-1]["content"] = 'property weather { value: "cloudy" }'
    assert any("assistant_content" in error for error in validate_example(drifted_message))


def test_sft_materialization_rejects_negative_and_draft_candidates(tmp_path: Path) -> None:
    for status, positive in (("accepted", False), ("draft", True)):
        candidate = fixture()
        candidate["status"] = status
        candidate["positive"] = positive
        assert validate_dataset([candidate]) == []
        with pytest.raises(ValueError, match="materializable SFT"):
            dataset_manifest([candidate])
        manifest = {
            "schema_version": 1,
            "example_count": 1,
            "counts_by_split": {
                "dev": 0,
                "frozen": 0,
                "internal_test": 0,
                "train": 1,
            },
            "counts_by_family": {
                "F-1": 1,
                "F-2": 0,
                "F-3": 0,
                "F-4": 0,
                "F-5": 0,
                "F-6": 0,
            },
            "example_ids": [candidate["example_id"]],
            "jsonl_sha256": "sha256:" + "0" * 64,
        }
        assert any(
            "materializable SFT" in error for error in validate_dataset([candidate], manifest)
        )
        with pytest.raises(ValueError, match="materializable SFT"):
            build_dataset([candidate])
        with pytest.raises(ValueError, match="materializable SFT"):
            write_dataset_jsonl([candidate], "candidate.jsonl", artifact_root=tmp_path)
