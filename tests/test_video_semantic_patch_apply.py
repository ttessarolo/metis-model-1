from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from metis_model1 import video_semantic_patch_apply as patch_apply_module
from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantic_patch import render_candidate_patch
from metis_model1.video_semantic_patch_apply import (
    PROMOTION_RECEIPT_CONTRACT,
    SemanticPatchApplyError,
    apply_semantic_patch,
    atomic_replace_if_current,
    plan_semantic_patch_apply,
    plan_semantic_review_promotion,
    promote_semantic_patch_review,
)

COMMIT = "a" * 40
TREE = "b" * 40
CATALOG_PATH = "catalogs/video.metis"
VALUES_PATH = "catalogs/video.values.metis"


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _technical(
    *, type_name: str = "keyword", domain: str = "none", modifiers: list[str] | None = None
) -> dict:
    return {
        "type": type_name,
        "modifiers": modifiers or [],
        "domain_kind": domain,
        "declared_cardinality": None,
        "observed_cardinality": None,
    }


def _locator(
    *,
    commit: str,
    path: str,
    preimage: str,
    field: str | None,
    literal: str | None,
) -> dict:
    return {
        "repository_commit": commit,
        "path": path,
        "catalog": "demo.video",
        "field_path": field,
        "literal": literal,
        "preimage_sha256": preimage,
    }


def _row(
    *,
    commit: str,
    path: str,
    preimage: str,
    order: int,
    field: str | None,
    literal: str | None,
    technical: dict,
    source_line: int | None = None,
) -> dict:
    result = {
        "canonical_locator": _locator(
            commit=commit, path=path, preimage=preimage, field=field, literal=literal
        ),
        "technical": technical,
        "order": order,
    }
    if source_line is not None:
        result["source_line"] = source_line
    return result


def _work_item(
    row: dict,
    *,
    item_number: int,
    means: str,
    aliases: list[str] | None = None,
) -> dict:
    locator = row["canonical_locator"]
    if locator["field_path"] is None:
        node_kind = "catalog"
    elif locator["literal"] is None:
        node_kind = "field"
    else:
        node_kind = "value"
    return {
        "schema_version": 1,
        "work_item_id": "sha256:" + f"{item_number:064x}",
        "node_kind": node_kind,
        "canonical_locator": deepcopy(locator),
        "technical": deepcopy(row["technical"]),
        "candidate": {
            "means": means,
            "aka": aliases or [],
            "review_state": "draft",
        },
        "editorial_rules": {
            "include_when": [],
            "exclude_when": [],
            "scope": ["video"],
            "dependencies": [],
            "constraint_gaps": [],
        },
        "evidence_refs": [f"evidence-{item_number}"],
        "ambiguities": [],
        "author": "frontier-review",
        "reviewer": None,
    }


def _render(rows: list[dict], selected: list[int], *, means: list[str] | None = None) -> dict:
    items = [
        _work_item(
            rows[index],
            item_number=index + 1,
            means=(means or [f"Descrizione {number}." for number in range(len(selected))])[number],
            aliases=["tono monocromatico"] if number == 2 else [],
        )
        for number, index in enumerate(selected)
    ]
    aka_evidence = {
        item["work_item_id"]: list(item["evidence_refs"])
        for item in items
        if item["candidate"]["aka"]
    }
    return render_candidate_patch(
        items,
        rows,
        repository_commit=rows[0]["canonical_locator"]["repository_commit"],
        aka_evidence=aka_evidence or None,
    )


def _two_file_fixture(commit: str = COMMIT) -> tuple[dict[str, bytes], list[dict], dict]:
    catalog = (
        b"metis 0.43\n\n// untouched header\ncatalog demo.video {\n"
        b'  index "video"\n'
        b"  fields {\n"
        b'    visual keyword multi values ["Bianco e \\"nero\\"", "Azione"] // keep me\n'
        b"    genre keyword enum(2)\n"
        b"  }\n"
        b"}\n"
    )
    values = b'metis 0.43\n\nvalues demo.video {\n  genre reflected ["Vendetta", "Altro"]\n}\n'
    files = {CATALOG_PATH: catalog, VALUES_PATH: values}
    catalog_hash = _sha(catalog)
    values_hash = _sha(values)
    rows = [
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=catalog_hash,
            order=0,
            field=None,
            literal=None,
            technical=_technical(type_name="catalog"),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=catalog_hash,
            order=1,
            field="visual",
            literal=None,
            technical=_technical(domain="inline", modifiers=["multi"]),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=catalog_hash,
            order=2,
            field="visual",
            literal='Bianco e "nero"',
            technical=_technical(domain="inline", modifiers=["multi"]),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=catalog_hash,
            order=3,
            field="visual",
            literal="Azione",
            technical=_technical(domain="inline", modifiers=["multi"]),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=catalog_hash,
            order=4,
            field="genre",
            literal=None,
            technical=_technical(domain="enum"),
        ),
        _row(
            commit=commit,
            path=VALUES_PATH,
            preimage=values_hash,
            order=5,
            field="genre",
            literal="Vendetta",
            technical=_technical(domain="enum"),
        ),
        _row(
            commit=commit,
            path=VALUES_PATH,
            preimage=values_hash,
            order=6,
            field="genre",
            literal="Altro",
            technical=_technical(domain="enum"),
        ),
    ]
    patch = _render(
        rows,
        [0, 1, 2, 5],
        means=[
            "Catalogo dei contenuti video.",
            "Aspetto visivo curato dalla redazione.",
            "Opera in bianco e nero, inclusi i restauri.",
            "Tema della rivalsa e della vendetta — verifica editoriale.",
        ],
    )
    return files, rows, patch


def test_pure_plan_handles_catalog_field_inline_and_reflected_values() -> None:
    files, rows, patch = _two_file_fixture()
    plan = plan_semantic_patch_apply(
        source_files=files,
        patch=patch,
        technical_roster=rows,
        repository_commit=COMMIT,
        repository_tree=TREE,
        allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
    )
    assert plan.operation_count == 4
    assert [item.path for item in plan.files] == [CATALOG_PATH, VALUES_PATH]
    outputs = {item.path: item.postimage.decode() for item in plan.files}
    catalog = outputs[CATALOG_PATH]
    values = outputs[VALUES_PATH]
    assert 'catalog demo.video {\n  means draft "Catalogo dei contenuti video."\n' in catalog
    assert (
        'visual keyword multi values ["Bianco e \\"nero\\"" means draft '
        '"Opera in bianco e nero, inclusi i restauri." aka ["tono monocromatico"]'
    ) in catalog
    assert '] means draft "Aspetto visivo curato dalla redazione." // keep me' in catalog
    assert (
        '"Vendetta" means draft "Tema della rivalsa e della vendetta — verifica editoriale."'
    ) in values
    assert "// untouched header" in catalog and "// keep me" in catalog
    for file_plan in plan.files:
        assert file_plan.preimage == files[file_plan.path]
        assert file_plan.preimage_sha256 == _sha(files[file_plan.path])
        assert file_plan.postimage_sha256 == _sha(file_plan.postimage)


def test_duplicate_literals_and_existing_semantics_fail_closed() -> None:
    raw = b'metis 0.43\ncatalog demo.video { fields { tone keyword ["A", "A"] } }\n'
    preimage = _sha(raw)
    row = _row(
        commit=COMMIT,
        path=CATALOG_PATH,
        preimage=preimage,
        order=0,
        field="tone",
        literal=None,
        technical=_technical(domain="inline"),
    )
    patch = _render([row], [0])
    with pytest.raises(SemanticPatchApplyError, match="METIS_DUPLICATE_VALUE_LITERAL"):
        plan_semantic_patch_apply(
            source_files={CATALOG_PATH: raw},
            patch=patch,
            technical_roster=[row],
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH],
        )

    annotated = (
        b'metis 0.43\ncatalog demo.video { fields { tone keyword means draft "existing" } }\n'
    )
    annotated_rows = [
        _row(
            commit=COMMIT,
            path=CATALOG_PATH,
            preimage=_sha(annotated),
            order=0,
            field=None,
            literal=None,
            technical=_technical(type_name="catalog"),
        ),
        _row(
            commit=COMMIT,
            path=CATALOG_PATH,
            preimage=_sha(annotated),
            order=1,
            field="tone",
            literal=None,
            technical=_technical(),
        ),
    ]
    annotated_patch = _render(annotated_rows, [1])
    with pytest.raises(SemanticPatchApplyError, match="PATCH_TARGET_ALREADY_ANNOTATED"):
        plan_semantic_patch_apply(
            source_files={CATALOG_PATH: annotated},
            patch=annotated_patch,
            technical_roster=annotated_rows,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH],
        )


def test_stale_source_location_order_and_preimage_are_rejected() -> None:
    files, rows, patch = _two_file_fixture()
    stale = deepcopy(rows)
    stale[0]["source_line"] = 999
    stale_patch = _render(stale, [0])
    with pytest.raises(SemanticPatchApplyError, match="ROSTER_SOURCE_LOCATION_STALE"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=stale_patch,
            technical_roster=stale,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )

    reordered = deepcopy(rows)
    reordered[0]["order"], reordered[1]["order"] = 1, 0
    reordered_patch = _render(reordered, [1])
    with pytest.raises(SemanticPatchApplyError, match="ROSTER_SOURCE_ORDER_DRIFT"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=reordered_patch,
            technical_roster=reordered,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )

    drifted_files = {**files, CATALOG_PATH: files[CATALOG_PATH] + b"// drift\n"}
    with pytest.raises(SemanticPatchApplyError, match="FILE_PREIMAGE_DRIFT"):
        plan_semantic_patch_apply(
            source_files=drifted_files,
            patch=patch,
            technical_roster=rows,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )


def test_patch_tampering_and_non_metis_or_traversal_paths_are_rejected() -> None:
    files, rows, patch = _two_file_fixture()
    tampered = deepcopy(patch)
    tampered["operations"][0]["grammar"] = 'means draft "tampered"'
    with pytest.raises(SemanticPatchApplyError, match="CANDIDATE_PATCH_INVALID"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=tampered,
            technical_roster=rows,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )
    with pytest.raises(SemanticPatchApplyError, match="APPLY_PATH_INVALID"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=patch,
            technical_roster=rows,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=["../outside.metis", VALUES_PATH],
        )
    with pytest.raises(SemanticPatchApplyError, match="APPLY_PATH_INVALID"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=patch,
            technical_roster=rows,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=["catalogs/video.txt", VALUES_PATH],
        )


def test_partial_technical_roster_is_rejected() -> None:
    files, rows, _ = _two_file_fixture()
    partial = [rows[0]]
    patch = _render(partial, [0])
    with pytest.raises(SemanticPatchApplyError, match="TECHNICAL_ROSTER_COVERAGE_GAP"):
        plan_semantic_patch_apply(
            source_files=files,
            patch=patch,
            technical_roster=partial,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str, bytes]:
    root = tmp_path / "tenant"
    (root / "catalogs").mkdir(parents=True)
    raw = b'metis 0.43\ncatalog demo.video { fields { tone keyword ["A"] } }\n'
    target = root / CATALOG_PATH
    target.write_bytes(raw)
    os.chmod(target, 0o640)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}"), raw


def _repository_patch(commit: str, raw: bytes) -> tuple[list[dict], dict]:
    rows = [
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=_sha(raw),
            order=0,
            field=None,
            literal=None,
            technical=_technical(type_name="catalog"),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=_sha(raw),
            order=1,
            field="tone",
            literal=None,
            technical=_technical(domain="inline"),
        ),
        _row(
            commit=commit,
            path=CATALOG_PATH,
            preimage=_sha(raw),
            order=2,
            field="tone",
            literal="A",
            technical=_technical(domain="inline"),
        ),
    ]
    return rows, _render(rows, [2], means=["Valore di prova verificabile."])


def test_production_apply_is_clean_scoped_atomic_and_mode_preserving(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    calls: list[tuple[Path, int, str]] = []

    def writer(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        calls.append((target, mode, preimage))
        atomic_replace_if_current(target, postimage, mode, preimage)

    receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
        atomic_writer=writer,
    )
    target = root / CATALOG_PATH
    assert len(calls) == 1
    assert calls[0][0] == target and calls[0][1] == 0o640
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert b'means draft "Valore di prova verificabile."' in target.read_bytes()
    assert receipt["counts"] == {
        "files_in": 1,
        "files_written": 1,
        "operations": 1,
        "gaps": 0,
    }
    assert receipt["payload_redacted"] is True
    assert _git(root, "status", "--porcelain=v1") == f"M {CATALOG_PATH}"


def test_production_rejects_dirty_checkout_and_symlink_root(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    (root / "untracked.txt").write_text("dirty")
    with pytest.raises(SemanticPatchApplyError, match="TENANT_WORKTREE_NOT_CLEAN"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
        )
    (root / "untracked.txt").unlink()
    linked = tmp_path / "tenant-link"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(SemanticPatchApplyError, match="TENANT_ROOT_INVALID"):
        apply_semantic_patch(
            tenant_root=linked,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
        )


def test_multi_file_failure_rolls_back_every_published_postimage(tmp_path: Path) -> None:
    root = tmp_path / "tenant"
    (root / "catalogs").mkdir(parents=True)
    fixture_files, _, _ = _two_file_fixture()
    for relative, raw in fixture_files.items():
        (root / relative).write_bytes(raw)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    files, rows, patch = _two_file_fixture(commit)
    calls = 0

    def fail_second_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SemanticPatchApplyError("INJECTED_SECOND_FILE_FAILURE")
        atomic_replace_if_current(target, postimage, mode, preimage)

    with pytest.raises(SemanticPatchApplyError, match="INJECTED_SECOND_FILE_FAILURE"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
            atomic_writer=fail_second_write,
        )
    assert calls == 3  # first publish, second failure, first rollback
    assert {path: (root / path).read_bytes() for path in files} == files
    assert _git(root, "status", "--porcelain=v1") == ""


def test_write_then_error_is_detected_and_rolled_back(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    calls = 0

    def publish_then_fail(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        nonlocal calls
        calls += 1
        atomic_replace_if_current(target, postimage, mode, preimage)
        if calls == 1:
            raise SemanticPatchApplyError("INJECTED_POST_PUBLISH_FAILURE")

    with pytest.raises(SemanticPatchApplyError, match="INJECTED_POST_PUBLISH_FAILURE"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=publish_then_fail,
        )
    assert calls == 2
    assert (root / CATALOG_PATH).read_bytes() == raw
    assert _git(root, "status", "--porcelain=v1") == ""


def test_post_write_dirty_gate_rolls_back_apply_and_preserves_unrelated_work(
    tmp_path: Path,
) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)

    def dirty_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        atomic_replace_if_current(target, postimage, mode, preimage)
        (root / "unrelated.txt").write_text("keep this work")

    with pytest.raises(SemanticPatchApplyError, match="POST_APPLY_WORKTREE_SCOPE_DRIFT"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=dirty_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == raw
    assert (root / "unrelated.txt").read_text() == "keep this work"


def _move_head_after_write(root: Path) -> None:
    old = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    replacement = _git(root, "commit-tree", tree, "-p", old, "-m", "post-write head drift")
    _git(root, "update-ref", "HEAD", replacement)


def test_post_write_head_drift_rolls_back_apply_owned_file(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)

    def drift_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        atomic_replace_if_current(target, postimage, mode, preimage)
        _move_head_after_write(root)

    with pytest.raises(SemanticPatchApplyError, match="APPLY_ROLLBACK_FAILED"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=drift_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == raw


def test_post_write_tree_drift_rolls_back_apply_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    drift = False
    real_git = patch_apply_module._git

    def tree_drifting_git(git_root: Path, *args: str) -> bytes:
        output = real_git(git_root, *args)
        if drift and args == ("rev-parse", "HEAD^{tree}"):
            return b"f" * 40
        return output

    monkeypatch.setattr(patch_apply_module, "_git", tree_drifting_git)

    def drift_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        nonlocal drift
        atomic_replace_if_current(target, postimage, mode, preimage)
        drift = True

    with pytest.raises(SemanticPatchApplyError, match="APPLY_ROLLBACK_FAILED"):
        apply_semantic_patch(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=drift_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == raw


def test_review_promotion_recomputes_draft_postimage_not_receipt_only() -> None:
    files, rows, patch = _two_file_fixture()
    expected = plan_semantic_patch_apply(
        source_files=files,
        patch=patch,
        technical_roster=rows,
        repository_commit=COMMIT,
        repository_tree=TREE,
        allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
    )
    draft = {item.path: item.postimage for item in expected.files}
    forged = dict(draft)
    forged[CATALOG_PATH] = draft[CATALOG_PATH].replace(b"visual keyword", b"visual text")
    receipt = {
        "schema_version": 1,
        "contract_id": "video-semantics/semantic-patch-apply-receipt-v1",
        "repository_commit": COMMIT,
        "repository_tree": TREE,
        "patch_sha256": patch["patch_sha256"],
        "counts": {"files_in": 2, "files_written": 2, "operations": 4, "gaps": 0},
        "files": [
            {
                "path": path,
                "preimage_sha256": _sha(files[path]),
                "postimage_sha256": _sha(forged[path]),
            }
            for path in (CATALOG_PATH, VALUES_PATH)
        ],
        "payload_redacted": True,
    }
    receipt["receipt_sha256"] = "sha256:" + canonical_json_hash(receipt)
    with pytest.raises(SemanticPatchApplyError, match="DRAFT_POSTIMAGE_BINDING_DRIFT"):
        plan_semantic_review_promotion(
            source_files=forged,
            preimage_files=files,
            patch=patch,
            technical_roster=rows,
            draft_apply_receipt=receipt,
            repository_commit=COMMIT,
            repository_tree=TREE,
            allowlisted_paths=[CATALOG_PATH, VALUES_PATH],
        )


def test_post_write_head_drift_rolls_back_review_promotion_owned_file(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    draft_receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
    )
    draft = (root / CATALOG_PATH).read_bytes()

    def drift_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        atomic_replace_if_current(target, postimage, mode, preimage)
        _move_head_after_write(root)

    with pytest.raises(SemanticPatchApplyError, match="APPLY_ROLLBACK_FAILED"):
        promote_semantic_patch_review(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            draft_apply_receipt=draft_receipt,
            review_receipt_sha256="sha256:" + "c" * 64,
            reviewer="l0-frontier",
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=drift_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == draft


def test_post_write_tree_drift_rolls_back_review_promotion_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    draft_receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
    )
    draft = (root / CATALOG_PATH).read_bytes()
    drift = False
    real_git = patch_apply_module._git

    def tree_drifting_git(git_root: Path, *args: str) -> bytes:
        output = real_git(git_root, *args)
        if drift and args == ("rev-parse", "HEAD^{tree}"):
            return b"f" * 40
        return output

    monkeypatch.setattr(patch_apply_module, "_git", tree_drifting_git)

    def drift_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        nonlocal drift
        atomic_replace_if_current(target, postimage, mode, preimage)
        drift = True

    with pytest.raises(SemanticPatchApplyError, match="APPLY_ROLLBACK_FAILED"):
        promote_semantic_patch_review(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            draft_apply_receipt=draft_receipt,
            review_receipt_sha256="sha256:" + "c" * 64,
            reviewer="l0-frontier",
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=drift_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == draft


def test_review_promotion_is_exact_and_receipted(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    draft_receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
    )
    draft = (root / CATALOG_PATH).read_bytes()
    plan = plan_semantic_review_promotion(
        source_files={CATALOG_PATH: draft},
        preimage_files={CATALOG_PATH: raw},
        patch=patch,
        technical_roster=rows,
        draft_apply_receipt=draft_receipt,
        repository_commit=commit,
        repository_tree=tree,
        allowlisted_paths=[CATALOG_PATH],
    )
    assert plan.operation_count == 1
    assert b'means "Valore di prova verificabile."' in plan.files[0].postimage
    assert b"means draft " not in plan.files[0].postimage

    review_receipt = "sha256:" + "c" * 64
    receipt = promote_semantic_patch_review(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        draft_apply_receipt=draft_receipt,
        review_receipt_sha256=review_receipt,
        reviewer="l0-frontier",
        allowlisted_paths=[CATALOG_PATH],
    )
    assert receipt["contract_id"] == PROMOTION_RECEIPT_CONTRACT
    assert receipt["review_receipt_sha256"] == review_receipt
    assert receipt["counts"] == {
        "files_in": 1,
        "files_written": 1,
        "reviewed_operations": 1,
        "gaps": 0,
    }
    assert (root / CATALOG_PATH).read_bytes() == plan.files[0].postimage
    assert _git(root, "status", "--porcelain=v1") == f"M {CATALOG_PATH}"


def test_review_promotion_rejects_tampered_draft_receipt(tmp_path: Path) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    draft_receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
    )
    attacked = deepcopy(draft_receipt)
    attacked["files"][0]["postimage_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(SemanticPatchApplyError, match="DRAFT_APPLY_RECEIPT_INVALID"):
        plan_semantic_review_promotion(
            source_files={CATALOG_PATH: (root / CATALOG_PATH).read_bytes()},
            preimage_files={CATALOG_PATH: raw},
            patch=patch,
            technical_roster=rows,
            draft_apply_receipt=attacked,
            repository_commit=commit,
            repository_tree=tree,
            allowlisted_paths=[CATALOG_PATH],
        )


def test_post_write_dirty_gate_rolls_back_review_promotion(
    tmp_path: Path,
) -> None:
    root, commit, tree, raw = _repository(tmp_path)
    rows, patch = _repository_patch(commit, raw)
    draft_receipt = apply_semantic_patch(
        tenant_root=root,
        repository_commit=commit,
        repository_tree=tree,
        patch=patch,
        technical_roster=rows,
        allowlisted_paths=[CATALOG_PATH],
    )
    draft = (root / CATALOG_PATH).read_bytes()

    def dirty_after_write(target: Path, postimage: bytes, mode: int, preimage: str) -> None:
        atomic_replace_if_current(target, postimage, mode, preimage)
        (root / "unrelated.txt").write_text("keep this work")

    with pytest.raises(SemanticPatchApplyError, match="POST_APPLY_WORKTREE_SCOPE_DRIFT"):
        promote_semantic_patch_review(
            tenant_root=root,
            repository_commit=commit,
            repository_tree=tree,
            patch=patch,
            technical_roster=rows,
            draft_apply_receipt=draft_receipt,
            review_receipt_sha256="sha256:" + "c" * 64,
            reviewer="l0-frontier",
            allowlisted_paths=[CATALOG_PATH],
            atomic_writer=dirty_after_write,
        )
    assert (root / CATALOG_PATH).read_bytes() == draft
    assert (root / "unrelated.txt").read_text() == "keep this work"
