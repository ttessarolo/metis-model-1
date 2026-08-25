from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import metis_model1.grammar_stdlib_coverage as coverage

ROOT = Path(__file__).resolve().parents[1]
GIT_DIR = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis/.git")


def test_manifest_contract_is_exact_and_nonpromotable() -> None:
    assert coverage.validate_pin_contract(ROOT) == []
    manifest = coverage.load_pin(ROOT)

    assert manifest["revision"] == "5e112f9148f40e7e792052e896c5a9efe8eaf0a2"
    assert manifest["tree"] == "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af"
    assert manifest["grammar"]["production_count"] == 172
    assert manifest["grammar"]["top_level_alternatives"] == [
        "Tenant",
        "Catalog",
        "Property",
        "Endpoint",
        "Preset",
        "List",
        "Transformer",
        "NamedBlock<true>",
        "SettingsDecl",
        "ValueSet",
    ]
    assert manifest["stdlib"]["module_count"] == 3
    assert manifest["stdlib"]["member_count"] == 12
    assert manifest["stdlib"]["setting_count"] == 1
    assert manifest["policy"]["git_objects_only"] is True
    assert "no_accuracy_claim" in manifest["nonclaims"]
    assert "nonpromotable" in manifest["nonclaims"]


@pytest.mark.skipif(not GIT_DIR.exists(), reason="external Metis Git object store is unavailable")
def test_census_recomputes_pinned_objects_and_current_blob_identity() -> None:
    result = coverage.census(GIT_DIR, ROOT)

    assert result["status"] == "valid"
    assert result["revision"] == "5e112f9148f40e7e792052e896c5a9efe8eaf0a2"
    assert result["comparison_revision"] == "c1aca0f629ec96a5ea1f52eea5b4561d0c41f6b5"
    assert result["grammar"]["production_count"] == 172
    assert result["grammar"]["returns_count"] == 17
    assert result["grammar"]["infers_count"] == 15
    assert len(result["grammar"]["top_level_alternatives"]) == 10
    assert result["stdlib"]["module_count"] == 3
    assert result["stdlib"]["member_count"] == 12
    assert result["stdlib"]["setting_count"] == 1
    assert {item["id"] for item in result["evidence"]} == {
        "grammar",
        "generated_grammar",
        "stdlib",
        "version",
        "guard_eval",
        "corpus_validation_test",
        "time_test",
        "compiler_regression_test",
    }
    assert all(len(item["blob_oid"]) == 40 for item in result["evidence"])


def test_manifest_roster_mutation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    mutated = deepcopy(coverage.load_pin(ROOT))
    mutated["grammar"]["production_names"].pop()
    monkeypatch.setattr(coverage, "load_pin", lambda _root=ROOT: mutated)

    assert "grammar production count/list mismatch" in coverage.validate_pin_contract(ROOT)


def test_evidence_path_roster_mutation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    mutated = deepcopy(coverage.load_pin(ROOT))
    mutated["evidence"][-1]["path"] = "tooling/test/not-the-compiler-regression.ts"
    monkeypatch.setattr(coverage, "load_pin", lambda _root=ROOT: mutated)

    assert "evidence ID/path roster mismatch" in coverage.validate_pin_contract(ROOT)


def test_git_reader_uses_object_database_without_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: dict[str, object] = {}
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    class Completed:
        stdout = ""

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        observed["command"] = command
        observed.update(kwargs)
        return Completed()

    monkeypatch.setattr(coverage.subprocess, "run", fake_run)
    coverage._run_git(git_dir, "cat-file", "-e", "deadbeef")

    command = observed["command"]
    assert isinstance(command, list)
    assert command[:3] == ["/usr/bin/git", "--git-dir", str(git_dir)]
    assert "-C" not in command
    assert observed["env"]["GIT_TERMINAL_PROMPT"] == "0"  # type: ignore[index]
