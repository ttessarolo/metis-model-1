from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from metis_model1.video_catalog_capture import (
    CommandResult,
    VideoCatalogCaptureError,
    _capture_video_catalog_for_test,
    capture_video_catalog,
    validate_video_catalog_capture_receipt,
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("pinned\n", encoding="utf-8")
    (root / "metis.toml").write_text("name = 'synthetic'\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.metis\n", encoding="utf-8")
    _git(root, "add", "tracked.txt", "metis.toml", ".gitignore")
    _git(root, "commit", "-qm", "pinned")
    return _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")


def _semantic(line: int) -> dict[str, Any]:
    return {
        "state": "unannotated",
        "at": {"file": "catalogs/video.metis", "line": line},
    }


def _describe() -> dict[str, Any]:
    return {
        "schema": 2,
        "tenant": "synthetic",
        "thresholds": {"inline-max": 2, "enum-max": 20},
        "catalogs": [
            {
                "name": "synthetic.video",
                "driver": "opensearch",
                "index": "video",
                "file": "catalogs/video.metis",
                "fields": [
                    {
                        "name": "kind",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "inline", "size": 2, "values": ["Film", "Serie"]},
                        "semantic": _semantic(10),
                    },
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                        "semantic": _semantic(20),
                    },
                    {
                        "name": "title",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "open"},
                        "semantic": _semantic(30),
                    },
                    {
                        "name": "year",
                        "type": "number",
                        "modifiers": [],
                        "domain": {"kind": "none"},
                        "semantic": _semantic(40),
                    },
                    {
                        "name": "empty",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "inline", "size": 0, "values": []},
                        "semantic": _semantic(50),
                    },
                ],
                "semantic": _semantic(2),
            }
        ],
    }


def _values(field: str, literals: list[str]) -> dict[str, Any]:
    described = next(item for item in _describe()["catalogs"][0]["fields"] if item["name"] == field)
    domain = described["domain"]
    value: dict[str, Any] = {
        "schema": 2,
        "tenant": "synthetic",
        "catalog": "synthetic.video",
        "field": field,
        "kind": domain["kind"],
        "size": domain["size"],
        "values": literals,
        "semantic": {
            "field": described["semantic"],
            "values": [
                {"literal": literal, **_semantic(60 + index)}
                for index, literal in enumerate(literals)
            ],
        },
    }
    if "nature" in domain:
        value["nature"] = domain["nature"]
    return value


def _raw(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


class FixtureRunner:
    def __init__(self, *, mutation: str | None = None, on_call=None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.mutation = mutation
        self.on_call = on_call

    def __call__(self, *, argv, cwd, env, timeout) -> CommandResult:
        del cwd, env, timeout
        command = tuple(argv)
        self.calls.append(command)
        if self.on_call is not None:
            self.on_call(len(self.calls))
        mode = command[4]
        if mode == "describe":
            payload = _describe()
        else:
            field = command[command.index("--field") + 1]
            payload = _values(field, ["Film", "Serie"] if field == "kind" else ["Drama", "Comedy"])
            if self.mutation == "invalid":
                payload["schema"] = 1
            elif self.mutation == "duplicate" and field == "genre":
                payload["values"] = ["Drama", "Drama"]
                payload["semantic"]["values"][1]["literal"] = "Drama"
            elif self.mutation == "missing" and field == "genre":
                payload.pop("values")
                payload["semantic"].pop("values")
                payload.pop("nature")
                payload["note"] = "not materialized"
        return CommandResult(0, _raw(payload))


@pytest.fixture
def capture_fixture(tmp_path: Path):
    metis = tmp_path / "metis"
    tenant = tmp_path / "tenant"
    _repository(metis)
    tenant_revision, tenant_tree = _repository(tenant)
    (metis / "tooling").mkdir()
    (metis / "tooling" / "fixture.txt").write_text("tooling\n", encoding="utf-8")
    # The injected runner and verifier make the synthetic fixtures independent
    # from Node while preserving the production command roster.
    _git(metis, "add", "tooling/fixture.txt")
    _git(metis, "commit", "-qm", "tooling")
    metis_revision = _git(metis, "rev-parse", "HEAD")
    metis_tree = _git(metis, "rev-parse", "HEAD^{tree}")
    node = tmp_path / "node"
    node.write_bytes(b"synthetic-node")
    pin = {
        "revision": metis_revision,
        "tree": metis_tree,
        "retrieval_schema": 2,
        "runtime": {},
    }
    return metis, tenant, node, tenant_revision, tenant_tree, pin


def _capture(fixture, runner: FixtureRunner):
    metis, tenant, node, tenant_revision, tenant_tree, pin = fixture
    return _capture_video_catalog_for_test(
        metis_root=metis,
        tenant_root=tenant,
        node_path=node,
        tenant_revision=tenant_revision,
        tenant_tree=tenant_tree,
        catalog_ref="video",
        runner=runner,
        pin=pin,
        runtime_verifier=lambda *_: None,
    )


def test_capture_is_complete_for_finite_domains_and_skips_open_none_empty(capture_fixture) -> None:
    runner = FixtureRunner()
    result = _capture(capture_fixture, runner)

    assert [call[4] for call in runner.calls] == ["describe", "values", "values"]
    assert [call[call.index("--field") + 1] for call in runner.calls[1:]] == ["genre", "kind"]
    fields = result["projection"]["catalogs"][0]["fields"]
    assert [item["literal"] for item in fields[0]["domain"]["values"]] == ["Film", "Serie"]
    assert [item["literal"] for item in fields[1]["domain"]["values"]] == ["Drama", "Comedy"]
    assert fields[2]["domain"] == {"kind": "open"}
    assert fields[3]["domain"] == {"kind": "none"}
    assert fields[4]["domain"] == {"kind": "inline", "size": 0, "values": []}
    assert result["receipt"]["counts"] == {
        "commands_in": 3,
        "commands_out": 3,
        "commands_distinct": 3,
        "commands_gaps": 0,
        "catalogs": 1,
        "fields": 5,
        "finite_fields": 2,
        "values_responses": 2,
        "values": 4,
    }
    assert validate_video_catalog_capture_receipt(result["receipt"]) == []
    assert "Drama" not in str(result["receipt"])
    assert "genre" not in str(result["receipt"])


def test_exact_command_roster_is_offline_semantic_and_has_caps(capture_fixture) -> None:
    runner = FixtureRunner()
    _capture(capture_fixture, runner)
    for command in runner.calls:
        assert command[1:5] == ("--import", "tsx", "src/cli/catalog-domain.ts", command[4])
        assert command[-1] == "--semantic"
        assert "sync" not in command


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("invalid", "VALUES_PAYLOAD_INVALID"),
        ("duplicate", "PROJECTION_JOIN_INVALID"),
        ("missing", "PROJECTION_JOIN_INVALID"),
    ],
)
def test_invalid_duplicate_and_missing_values_fail_payload_free(
    capture_fixture, mutation: str, code: str
) -> None:
    with pytest.raises(VideoCatalogCaptureError) as captured:
        _capture(capture_fixture, FixtureRunner(mutation=mutation))
    assert str(captured.value) == code


def test_tenant_commit_drift_during_capture_is_rejected(capture_fixture) -> None:
    tenant = capture_fixture[1]

    def drift(call_number: int) -> None:
        if call_number == 1:
            (tenant / "tracked.txt").write_text("changed\n", encoding="utf-8")
            _git(tenant, "add", "tracked.txt")
            _git(tenant, "commit", "-qm", "drift")

    with pytest.raises(VideoCatalogCaptureError, match="TENANT_COMMIT_DRIFT"):
        _capture(capture_fixture, FixtureRunner(on_call=drift))


def test_receipt_is_deterministic_and_tamper_evident(capture_fixture) -> None:
    first = _capture(capture_fixture, FixtureRunner())
    second = _capture(capture_fixture, FixtureRunner())
    assert first["receipt"] == second["receipt"]
    assert first["commands"] == second["commands"]

    tampered = copy.deepcopy(first["receipt"])
    tampered["counts"]["values"] += 1
    assert validate_video_catalog_capture_receipt(tampered) == ["CAPTURE_RECEIPT_HASH_INVALID"]


def test_preflight_rejects_commit_and_tree_drift_before_runner(capture_fixture) -> None:
    metis, tenant, node, tenant_revision, tenant_tree, pin = capture_fixture
    runner = FixtureRunner()
    with pytest.raises(VideoCatalogCaptureError, match="TENANT_COMMIT_DRIFT"):
        _capture_video_catalog_for_test(
            metis_root=metis,
            tenant_root=tenant,
            node_path=node,
            tenant_revision="0" * 40,
            tenant_tree=tenant_tree,
            catalog_ref="video",
            runner=runner,
            pin=pin,
            runtime_verifier=lambda *_: None,
        )
    assert runner.calls == []


@pytest.mark.parametrize(
    ("target", "revision", "tree", "code"),
    [
        ("toolchain", "0" * 40, None, "TOOLCHAIN_COMMIT_DRIFT"),
        ("tenant", None, "0" * 40, "TENANT_TREE_DRIFT"),
    ],
)
def test_each_pinned_git_identity_is_checked_before_execution(
    capture_fixture, target: str, revision: str | None, tree: str | None, code: str
) -> None:
    metis, tenant, node, tenant_revision, tenant_tree, pin = capture_fixture
    changed_pin = dict(pin)
    if target == "toolchain":
        changed_pin["revision"] = revision
    else:
        tenant_tree = tree or tenant_tree
    runner = FixtureRunner()
    with pytest.raises(VideoCatalogCaptureError, match=code):
        _capture_video_catalog_for_test(
            metis_root=metis,
            tenant_root=tenant,
            node_path=node,
            tenant_revision=tenant_revision,
            tenant_tree=tenant_tree,
            catalog_ref="video",
            runner=runner,
            pin=changed_pin,
            runtime_verifier=lambda *_: None,
        )
    assert runner.calls == []


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (CommandResult(1, b"", b"reserved payload"), "TOOLCHAIN_COMMAND_FAILED"),
        (CommandResult(0, b"{}", b"x" * (64 * 1024 + 1)), "TOOLCHAIN_OUTPUT_CAP_EXCEEDED"),
    ],
)
def test_command_failures_and_caps_do_not_echo_payload(capture_fixture, result, code) -> None:
    def runner(*, argv, cwd, env, timeout):
        del argv, cwd, env
        assert timeout == 30
        return result

    with pytest.raises(VideoCatalogCaptureError) as captured:
        _capture(capture_fixture, runner)
    assert str(captured.value) == code
    assert "reserved payload" not in str(captured.value)


def test_public_capture_path_cannot_inject_runner(capture_fixture) -> None:
    metis, tenant, node, tenant_revision, tenant_tree, pin = capture_fixture
    with pytest.raises(TypeError):
        capture_video_catalog(
            metis_root=metis,
            tenant_root=tenant,
            node_path=node,
            tenant_revision=tenant_revision,
            tenant_tree=tenant_tree,
            catalog_ref="video",
            pin=pin,
            runner=FixtureRunner(),  # type: ignore[call-arg]
        )


def test_ignored_tenant_inputs_are_rejected_before_runner(capture_fixture) -> None:
    metis, tenant, node, tenant_revision, tenant_tree, pin = capture_fixture
    (tenant / "ignored.metis").write_text("ignored\n", encoding="utf-8")
    runner = FixtureRunner()
    with pytest.raises(VideoCatalogCaptureError, match="TENANT_IGNORED_FILES_PRESENT"):
        _capture_video_catalog_for_test(
            metis_root=metis,
            tenant_root=tenant,
            node_path=node,
            tenant_revision=tenant_revision,
            tenant_tree=tenant_tree,
            catalog_ref="video",
            runner=runner,
            pin=pin,
            runtime_verifier=lambda *_: None,
        )
    assert runner.calls == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_non_regular_node_path_is_rejected_before_read(capture_fixture) -> None:
    metis, tenant, _node, tenant_revision, tenant_tree, pin = capture_fixture
    fifo = metis.parent / "node.fifo"
    os.mkfifo(fifo)
    try:
        with pytest.raises(VideoCatalogCaptureError, match="TOOLCHAIN_RUNTIME_UNAVAILABLE"):
            _capture_video_catalog_for_test(
                metis_root=metis,
                tenant_root=tenant,
                node_path=fifo,
                tenant_revision=tenant_revision,
                tenant_tree=tenant_tree,
                catalog_ref="video",
                runner=FixtureRunner(),
                pin=pin,
            )
    finally:
        fifo.unlink()


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="macOS sandbox-exec unavailable",
)
def test_sandbox_denies_unlisted_env_ignored_and_raw_files(tmp_path: Path) -> None:
    metis = tmp_path / "metis"
    tenant = tmp_path / "tenant"
    outside = tmp_path / "outside"
    metis.mkdir()
    tenant.mkdir()
    outside.mkdir()
    allowed = tenant / "allowed.metis"
    allowed.write_text("allowed\n", encoding="utf-8")
    forbidden = [
        metis / ".env",
        tenant / ".env",
        tenant / "ignored.metis",
        tenant / "raw.json",
        outside / ".env",
    ]
    for path in forbidden:
        path.write_text(f"secret-{path.name}\n", encoding="utf-8")

    from metis_model1.video_catalog_capture import _sandbox_profile

    profile = _sandbox_profile(metis, tenant, Path("/bin/cat"), [allowed])
    assert "(deny default)" in profile
    assert "(allow default)" not in profile
    allowed_result = subprocess.run(
        ["/usr/bin/sandbox-exec", "-p", profile, "/bin/cat", str(allowed)],
        check=False,
        capture_output=True,
        text=True,
        cwd="/usr",
    )
    assert allowed_result.returncode == 0
    assert allowed_result.stdout == "allowed\n"
    for path in forbidden:
        result = subprocess.run(
            ["/usr/bin/sandbox-exec", "-p", profile, "/bin/cat", str(path)],
            check=False,
            capture_output=True,
            text=True,
            cwd="/usr",
        )
        assert result.returncode != 0
        assert "secret-" not in result.stdout
        assert "secret-" not in result.stderr
