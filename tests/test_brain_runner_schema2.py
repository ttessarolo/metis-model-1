from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import metis_model1.brain_tools as brain_tools
from metis_model1.brain_protocol import bytes_sha256

METIS_ROOT = Path(
    os.environ.get(
        "METIS_MODEL1_BRAIN_METIS_ROOT",
        "/Users/tommasotessarolo/Developer/ares-matioska/metis",
    )
).resolve()
METIS_TOOLING = METIS_ROOT / "tooling"
PLAY_PROD_ROOT = Path(
    os.environ.get(
        "METIS_MODEL1_PLAY_PROD_ROOT",
        "/Users/tommasotessarolo/Developer/metis-tenant-play-prod",
    )
).resolve()


def _runner(tmp_path: Path, operation: str) -> subprocess.CompletedProcess[str]:
    node = os.environ.get("METIS_MODEL1_NODE") or shutil.which("node")
    if node is None or not (METIS_TOOLING / "node_modules/tsx").exists():
        pytest.skip("local pinned Metis tooling is unavailable")
    authority = tmp_path / "authority"
    runner = authority / "runtime/metis_brain/runner.mts"
    runner.parent.mkdir(parents=True)
    shutil.copy2(brain_tools.RUNNER_PATH, runner)
    (authority / "tooling").symlink_to(METIS_TOOLING, target_is_directory=True)
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    (tenant / "metis.toml").write_text(
        '[tenant]\nid = "demo"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (tenant / "source.metis").write_text(
        "metis 0.43\ncatalog demo.video { fields { genre keyword } }\n",
        encoding="utf-8",
    )
    (tenant / "target.metis").write_text(
        (
            "metis 0.43\n"
            "catalog demo.video_pg {\n"
            "  semantics from @video\n"
            "  fields { genre text }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    request = {
        "schema_version": 1,
        "operation": operation,
        "tenant_root": str(tenant.resolve()),
    }
    if operation == "compile":
        request["endpoint"] = None
    return subprocess.run(
        [node, "--import", "tsx", str(runner)],
        cwd=authority / "tooling",
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _candidate_runner(
    tmp_path: Path,
    *,
    endpoint: str = "demo.target",
    endpoint_prelude: str = "",
    block_prelude: str = "",
) -> subprocess.CompletedProcess[str]:
    node = os.environ.get("METIS_MODEL1_NODE") or shutil.which("node")
    if node is None or not (METIS_TOOLING / "node_modules/tsx").exists():
        pytest.skip("local pinned Metis tooling is unavailable")
    authority = tmp_path / "authority"
    runner = authority / "runtime/metis_brain/runner.mts"
    runner.parent.mkdir(parents=True)
    shutil.copy2(brain_tools.RUNNER_PATH, runner)
    (authority / "tooling").symlink_to(METIS_TOOLING, target_is_directory=True)
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    (tenant / "metis.toml").write_text(
        '[tenant]\nid = "demo"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    candidate_source = """metis 0.43
catalog demo.video {
  index "video"
  id id
  fields { id keyword genre keyword values ["Azione", "Commedia"] }
}
catalog demo.users {
  index "users"
  id id
  fields { id keyword segment keyword values ["Family", "Young"] }
}
endpoint demo.target {
  __ENDPOINT_PRELUDE__
  block rescue {
    __BLOCK_PRELUDE__
    take 1 from @video { return response }
  }
  take 2 from @video {
    include where @genre is "Azione"
    exclude where @genre is "Commedia"
    promote where @genre is "Commedia"
    order by @id ascending
    return response -> deduplicate fallback to block.rescue when empty
  }
  take 3 from @users {
    include where @segment is "Family"
    return response
  }
}
""".replace("__ENDPOINT_PRELUDE__", endpoint_prelude).replace("__BLOCK_PRELUDE__", block_prelude)
    (tenant / "candidate.metis").write_text(
        candidate_source,
        encoding="utf-8",
    )
    request = {
        "schema_version": 1,
        "operation": "compile-candidate",
        "tenant_root": str(tenant.resolve()),
        "endpoint": endpoint,
    }
    return subprocess.run(
        [node, "--import", "tsx", str(runner)],
        cwd=authority / "tooling",
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _edit_surface_runner(
    tmp_path: Path,
    *,
    source: str,
    endpoint: str = "demo.target",
    request_patch: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    node = os.environ.get("METIS_MODEL1_NODE") or shutil.which("node")
    if node is None or not (METIS_TOOLING / "node_modules/tsx").exists():
        pytest.skip("local pinned Metis tooling is unavailable")
    authority = tmp_path / "authority"
    runner = authority / "runtime/metis_brain/runner.mts"
    runner.parent.mkdir(parents=True)
    shutil.copy2(brain_tools.RUNNER_PATH, runner)
    (authority / "tooling").symlink_to(METIS_TOOLING, target_is_directory=True)
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    (tenant / "metis.toml").write_text(
        '[tenant]\nid = "demo"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (tenant / "target.metis").write_text(source, encoding="utf-8")
    request: dict[str, object] = {
        "schema_version": 1,
        "operation": "edit-surface",
        "tenant_root": str(tenant.resolve()),
        "relative_path": "target.metis",
        "endpoint": endpoint,
    }
    if request_patch:
        for key, value in request_patch.items():
            if value is None:
                request.pop(key, None)
            else:
                request[key] = value
    return subprocess.run(
        [node, "--import", "tsx", str(runner)],
        cwd=authority / "tooling",
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _real_edit_surface_runner(
    authority: Path,
    *,
    relative_path: str,
    endpoint: str,
) -> subprocess.CompletedProcess[str]:
    node = os.environ.get("METIS_MODEL1_NODE") or shutil.which("node")
    if (
        node is None
        or not (METIS_TOOLING / "node_modules/tsx").exists()
        or not (PLAY_PROD_ROOT / "metis.toml").is_file()
    ):
        pytest.skip("local pinned Metis/play-prod fixtures are unavailable")
    runner = authority / "runtime/metis_brain/runner.mts"
    runner.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(brain_tools.RUNNER_PATH, runner)
    tooling_link = authority / "tooling"
    if not tooling_link.exists():
        tooling_link.symlink_to(METIS_TOOLING, target_is_directory=True)
    request = {
        "schema_version": 1,
        "operation": "edit-surface",
        "tenant_root": str(PLAY_PROD_ROOT),
        "relative_path": relative_path,
        "endpoint": endpoint,
    }
    return subprocess.run(
        [node, "--import", "tsx", str(runner)],
        cwd=authority / "tooling",
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _real_candidate_runner(
    authority: Path,
    *,
    endpoint: str,
) -> subprocess.CompletedProcess[str]:
    node = os.environ.get("METIS_MODEL1_NODE") or shutil.which("node")
    if (
        node is None
        or not (METIS_TOOLING / "node_modules/tsx").exists()
        or not (PLAY_PROD_ROOT / "metis.toml").is_file()
    ):
        pytest.skip("local pinned Metis/play-prod fixtures are unavailable")
    runner = authority / "runtime/metis_brain/runner.mts"
    runner.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(brain_tools.RUNNER_PATH, runner)
    tooling_link = authority / "tooling"
    if not tooling_link.exists():
        tooling_link.symlink_to(METIS_TOOLING, target_is_directory=True)
    request = {
        "schema_version": 1,
        "operation": "compile-candidate",
        "tenant_root": str(PLAY_PROD_ROOT),
        "endpoint": endpoint,
    }
    return subprocess.run(
        [node, "--import", "tsx", str(runner)],
        cwd=authority / "tooling",
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


COMPLEX_EDIT_SURFACE_SOURCE = """metis 0.43
catalog demo.video {
  index "video"
  id id
  fields { id keyword genre keyword }
}
block genre_row(genres! text, window duration) {
  take 6 from @video as row_template "Template"
}
endpoint demo.target {
  input format text
  blocks {
    local {
      take 7 from @video as inner "Interno" {
        return response -> limit to 3
      }
    }
  }
  variant similar_4_k if $format is "4K HDR" or $format is "4K SDR" {
    take 11 from @video as hero "Èroe 🎬" {
      return response -> limit to 4
    }
    use block.local "Fallback locale"
    use blocks {
      genre_row(genres = "Azione,Commedia", window = 30d) as genres "Generi"
    }
    return response -> limit to 2
  }
}
"""


def test_runner_digest_is_bound_after_validation_hardening() -> None:
    assert bytes_sha256(brain_tools.RUNNER_PATH.read_bytes()) == brain_tools.RUNNER_SHA256


def test_schema_two_projection_and_compile_fail_closed_on_incompatible_semantics_from(
    tmp_path: Path,
) -> None:
    projection = _runner(tmp_path / "projection", "semantic-catalog")
    assert projection.returncode == 1
    assert "tenant validation failed" in projection.stderr
    assert "demo.video_pg" not in projection.stderr

    compiled = _runner(tmp_path / "compile", "compile")
    assert compiled.returncode == 0
    payload = json.loads(compiled.stdout)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"]
    assert any("compatib" in item["message"] for item in payload["diagnostics"])


def test_compile_candidate_returns_bounded_occurrence_manifest_without_raw_ir(
    tmp_path: Path,
) -> None:
    completed = _candidate_runner(tmp_path)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok", payload["diagnostics"]
    assert payload["endpoint"] == "demo.target"
    assert payload["manifest"]["endpoint"] == "demo.target"
    fetches = payload["manifest"]["fetches"]
    assert [item["occurrence"] for item in fetches] == [0, 1, 2]
    assert [item["catalog"] for item in fetches] == [
        "demo.video",
        "demo.video",
        "demo.users",
    ]
    assert [item["count"]["take"] for item in fetches] == [1, 2, 3]
    intents = [item["intent"] for item in fetches[1]["predicates"]]
    assert intents == ["include", "exclude", "promote"]
    assert fetches[1]["ordering_sha256"].startswith("sha256:")
    assert fetches[1]["output_sha256"].startswith("sha256:")
    assert fetches[1]["fallback_sha256"].startswith("sha256:")
    assert all(
        item["semantics_sha256"].startswith("sha256:") for item in payload["manifest"]["containers"]
    )
    assert "structural_ir" not in payload
    assert "provenance" not in completed.stdout


def test_compile_candidate_container_hash_covers_direct_endpoint_and_block_semantics(
    tmp_path: Path,
) -> None:
    baseline = _candidate_runner(tmp_path / "baseline")
    semantic_change = _candidate_runner(
        tmp_path / "semantic-change",
        endpoint_prelude="params { analytics off }\n  needs time",
        block_prelude="schedule monday 00:01..02:00",
    )
    assert baseline.returncode == 0, baseline.stderr
    assert semantic_change.returncode == 0, semantic_change.stderr
    before = json.loads(baseline.stdout)
    after = json.loads(semantic_change.stdout)
    assert before["status"] == after["status"] == "ok"
    before_containers = before["manifest"]["containers"]
    after_containers = after["manifest"]["containers"]
    assert before_containers[0]["semantics_sha256"] != after_containers[0]["semantics_sha256"]
    assert before_containers[1]["semantics_sha256"] != after_containers[1]["semantics_sha256"]


def test_compile_candidate_hash_keeps_user_metadata_named_provenance(tmp_path: Path) -> None:
    first = _candidate_runner(
        tmp_path / "first",
        block_prelude='meta provenance "alpha"',
    )
    second = _candidate_runner(
        tmp_path / "second",
        block_prelude='meta provenance "beta"',
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["status"] == second_payload["status"] == "ok"
    assert (
        first_payload["manifest"]["containers"][1]["semantics_sha256"]
        != second_payload["manifest"]["containers"][1]["semantics_sha256"]
    )


def test_compile_candidate_invalid_identity_returns_no_partial_authority(tmp_path: Path) -> None:
    completed = _candidate_runner(tmp_path, endpoint="demo.missing")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"][0]["code"] == "BRAIN_ENDPOINT_IDENTITY"
    for field in (
        "endpoint",
        "endpoint_sha256",
        "runtime_context_sha256",
        "manifest",
        "manifest_sha256",
    ):
        assert payload[field] is None


def test_compile_candidate_preserves_non_catalog_context_predicate_lineage(
    tmp_path: Path,
) -> None:
    completed = _real_candidate_runner(
        tmp_path,
        endpoint="play.tvod_multiple_block",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok", payload["diagnostics"]
    contextual = [
        item
        for item in payload["manifest"]["fetches"]
        if item["source"] == {"kind": "context", "ref": "user.video_watched_w_ts"}
    ]
    assert len(contextual) == 1
    assert contextual[0]["catalog"] is None
    ts = [item for item in contextual[0]["predicates"] if item["field"] == "ts"]
    assert len(ts) == 1
    assert ts[0]["catalog"] is None
    assert ts[0]["operator"] == "within"


def test_edit_surface_projects_exact_private_complex_targets_in_source_order(
    tmp_path: Path,
) -> None:
    completed = _edit_surface_runner(tmp_path, source=COMPLEX_EDIT_SURFACE_SOURCE)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok", payload["diagnostics"]
    surface = payload["edit_surface"]
    assert surface["contract"] == "metis-brain-edit-surface/v1"
    assert surface["relative_path"] == "target.metis"
    assert surface["source_sha256"].startswith("sha256:")
    assert payload["edit_surface_sha256"].startswith("sha256:")
    assert surface["counts"] == {
        "items": 10,
        "take_cardinality": 2,
        "output_limit": 3,
        "display_label_or_title": 4,
        "block_argument_list": 1,
    }
    items = surface["items"]
    assert [item["ordinal"] for item in items] == list(range(10))
    starts = [item["property"]["span"]["utf16"]["start"] for item in items]
    assert starts == sorted(starts)
    assert all(item["edit_ref"].startswith("sha256:") for item in items)
    assert all(item["owner"]["node_id"].startswith("$/") for item in items)
    assert all(item["owner"]["preimage_sha256"].startswith("sha256:") for item in items)
    assert all(item["property"]["preimage_sha256"].startswith("sha256:") for item in items)
    assert all(item["scope"]["ancestors"][0]["kind"] == "endpoint" for item in items)

    variant_items = [
        item
        for item in items
        if any(
            ancestor["kind"] == "variant" and ancestor["name"] == "similar_4_k"
            for ancestor in item["scope"]["ancestors"]
        )
    ]
    assert len(variant_items) == 7
    for item in variant_items:
        stage = item["scope"]["stage"]
        assert stage["activation_sha256"].startswith("sha256:")
        assert stage["selectors"] == {"identifiers": [], "string_literals": []}

    argument = next(item for item in items if item["primitive"] == "block_argument_list")
    assert argument["old_value"] == {
        "type": "string",
        "argument": "genres",
        "value": "Azione,Commedia",
    }
    assert argument["scope"]["stage"]["kind"] == "use_instance"
    assert argument["scope"]["stage"]["identifier"] == "genres"
    assert argument["property"]["ast_node_id"].endswith("/value")
    assert len([item for item in items if item["primitive"] == "block_argument_list"]) == 1
    unicode_label = next(
        item
        for item in items
        if item["primitive"] == "display_label_or_title" and item["old_value"]["value"] == "Èroe 🎬"
    )
    token_span = unicode_label["property"]["span"]
    assert (
        token_span["utf8_bytes"]["end"] - token_span["utf8_bytes"]["start"]
        > token_span["utf16"]["end"] - token_span["utf16"]["start"]
    )
    assert unicode_label["property"]["preimage_sha256"] == bytes_sha256('"Èroe 🎬"'.encode())
    assert '"provenance"' not in completed.stdout

    replay = _edit_surface_runner(tmp_path / "replay", source=COMPLEX_EDIT_SURFACE_SOURCE)
    assert replay.returncode == 0, replay.stderr
    replay_payload = json.loads(replay.stdout)
    assert replay_payload["edit_surface"] == surface
    assert replay_payload["edit_surface_sha256"] == payload["edit_surface_sha256"]


def test_edit_surface_distinguishes_repeated_limits_by_stage_occurrence(tmp_path: Path) -> None:
    source = """metis 0.43
catalog demo.video { index "video" id id fields { id keyword } }
endpoint demo.target {
  take 10 from @video {
    return response -> limit to 8 -> limit to page default 20 -> limit to 4
  }
  take 5 from @video
}
"""
    completed = _edit_surface_runner(tmp_path, source=source)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok", payload["diagnostics"]
    limits = [
        item for item in payload["edit_surface"]["items"] if item["primitive"] == "output_limit"
    ]
    assert [item["scope"]["occurrence"] for item in limits] == [0, 1]
    assert len({item["scope"]["stage"]["node_id"] for item in limits}) == 1
    assert [item["old_value"]["value"] for item in limits] == [8, 4]
    takes = [
        item for item in payload["edit_surface"]["items"] if item["primitive"] == "take_cardinality"
    ]
    assert [item["scope"]["occurrence"] for item in takes] == [0, 1]
    assert len({item["scope"]["stage"]["node_id"] for item in takes}) == 2


def test_edit_surface_exposes_the_closest_guard_selectors_per_take(tmp_path: Path) -> None:
    source = """metis 0.43
catalog demo.video { index "video" id id fields { id keyword } }
endpoint demo.target {
  input format text
  variant formats if $format is "4K HDR" or $format is "4K SDR" {
    take 30 from @video if $format is "4K HDR"
    take 30 from @video if $format is "4K SDR"
    return response -> limit to 30
  }
}
"""
    completed = _edit_surface_runner(tmp_path, source=source)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok", payload["diagnostics"]
    takes = [
        item for item in payload["edit_surface"]["items"] if item["primitive"] == "take_cardinality"
    ]
    assert [item["scope"]["stage"]["selectors"] for item in takes] == [
        {"identifiers": ["format"], "string_literals": ["4K HDR"]},
        {"identifiers": ["format"], "string_literals": ["4K SDR"]},
    ]
    assert all(item["scope"]["stage"]["activation_sha256"] for item in takes)
    assert (
        takes[0]["scope"]["stage"]["activation_sha256"]
        != takes[1]["scope"]["stage"]["activation_sha256"]
    )
    limit = next(
        item for item in payload["edit_surface"]["items"] if item["primitive"] == "output_limit"
    )
    assert limit["scope"]["stage"]["selectors"] == {
        "identifiers": [],
        "string_literals": [],
    }


def test_edit_surface_rejects_ambiguous_endpoint_without_partial_authority(
    tmp_path: Path,
) -> None:
    source = """metis 0.43
catalog demo.video { index "video" id id fields { id keyword } }
endpoint demo.target { take 1 from @video }
endpoint demo.target { take 2 from @video }
"""
    completed = _edit_surface_runner(tmp_path, source=source)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"][0]["code"] == "BRAIN_ENDPOINT_IDENTITY"
    assert "ambiguous" in payload["diagnostics"][0]["message"]
    assert payload["edit_surface"] is None
    assert payload["edit_surface_sha256"] is None


def test_edit_surface_rejects_item_bound_without_partial_projection(tmp_path: Path) -> None:
    takes = "\n".join(f"  take {index + 1} from @video" for index in range(257))
    source = f"""metis 0.43
catalog demo.video {{ index "video" id id fields {{ id keyword }} }}
endpoint demo.target {{
{takes}
}}
"""
    completed = _edit_surface_runner(tmp_path, source=source)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "invalid"
    assert payload["diagnostics"][0]["code"] == "BRAIN_EDIT_SURFACE_LIMIT"
    assert payload["edit_surface"] is None
    assert payload["edit_surface_sha256"] is None


def test_edit_surface_request_roster_is_closed(tmp_path: Path) -> None:
    completed = _edit_surface_runner(
        tmp_path,
        source=COMPLEX_EDIT_SURFACE_SOURCE,
        request_patch={"unexpected": True},
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "invalid field roster" in completed.stderr


def test_edit_surface_covers_ten_real_complex_edit_targets_read_only(tmp_path: Path) -> None:
    cases = [
        {
            "path": "properties/play/similar_cinema.metis",
            "endpoint": "play.similar_cinema",
            "targets": [
                ("take_cardinality", 30, "variant", "similar_4_k", 2),
                ("output_limit", 30, "variant", "similar_4_k", 1),
            ],
        },
        {
            "path": "properties/play/similar_serie_tv_fiction.metis",
            "endpoint": "play.similar_serie_tv_fiction",
            "targets": [
                (
                    "take_cardinality",
                    5,
                    "variant",
                    "similar_serie_tv_fiction_2",
                    1,
                )
            ],
        },
        {
            "path": "properties/search/filtered_search.metis",
            "endpoint": "search.filtered_search",
            "targets": [("take_cardinality", 50, "variant", "ricerca_film", 1)],
        },
        {
            "path": "properties/search/detail.metis",
            "endpoint": "search.detail",
            "targets": [("display_label_or_title", "Film", "variant", "film", 1)],
        },
        {
            "path": "properties/play/multiple_block_compleanno.metis",
            "endpoint": "play.multiple_block_compleanno",
            "targets": [
                (
                    "display_label_or_title",
                    "Altri film suggeriti per te",
                    "variant",
                    "ciak",
                    1,
                )
            ],
        },
        {
            "path": "properties/play/multiple_block_dem_titoli_momento.metis",
            "endpoint": "play.multiple_block_dem_titoli_momento",
            "targets": [
                (
                    "display_label_or_title",
                    "Le serie di Mediaset Infinity",
                    "variant",
                    "clusterizzato",
                    1,
                )
            ],
        },
        {
            "path": "properties/play/tvod_multiple_block.metis",
            "endpoint": "play.tvod_multiple_block",
            "targets": [
                (
                    "display_label_or_title",
                    "Azione",
                    "variant",
                    "tvod_multiple_block_2",
                    1,
                )
            ],
        },
        {
            "path": "properties/play/multiple_block4_k.metis",
            "endpoint": "play.multiple_block4_k",
            "targets": [
                (
                    "take_cardinality",
                    20,
                    "block",
                    "inf_film_4_k_params_genre",
                    1,
                )
            ],
        },
        {
            "path": "properties/play/inf_multiple_block_film_serie.metis",
            "endpoint": "play.inf_multiple_block_film_serie",
            "targets": [
                (
                    "block_argument_list",
                    "Azione,Thriller,Crime",
                    "variant",
                    "personalizzata",
                    1,
                )
            ],
        },
        {
            "path": "properties/play/similar_intrat_abtest.metis",
            "endpoint": "play.similar_intrat_abtest",
            "targets": [
                (
                    "take_cardinality",
                    24,
                    "variant",
                    "similar_intrattenimento_ipotesi_c",
                    1,
                ),
                (
                    "output_limit",
                    24,
                    "variant",
                    "similar_intrattenimento_ipotesi_c",
                    1,
                ),
            ],
        },
    ]
    authority = tmp_path / "authority"
    observed: list[tuple[str, str]] = []
    for case in cases:
        completed = _real_edit_surface_runner(
            authority,
            relative_path=case["path"],
            endpoint=case["endpoint"],
        )
        assert completed.returncode == 0, (case["endpoint"], completed.stderr)
        payload = json.loads(completed.stdout)
        assert payload["status"] == "ok", (case["endpoint"], payload["diagnostics"])
        surface = payload["edit_surface"]
        assert surface["relative_path"] == case["path"]
        assert surface["endpoint"]["name"] == case["endpoint"]
        assert surface["source_sha256"] == bytes_sha256(
            (PLAY_PROD_ROOT / case["path"]).read_bytes()
        )
        assert surface["counts"]["items"] == len(surface["items"])
        assert '"provenance"' not in completed.stdout
        for primitive, value, scope_kind, scope_name, minimum in case["targets"]:
            matches = [
                item
                for item in surface["items"]
                if item["primitive"] == primitive
                and item["old_value"]["value"] == value
                and any(
                    ancestor["kind"] == scope_kind and ancestor["name"] == scope_name
                    for ancestor in item["scope"]["ancestors"]
                )
            ]
            assert len(matches) >= minimum, (case["endpoint"], primitive, value)
        observed.append((case["path"], case["endpoint"]))
    assert len(observed) == len(set(observed)) == 10
