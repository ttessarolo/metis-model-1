from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis_model1.brain_protocol import CAPABILITIES, BrainError, parse_json_object
from metis_model1.brain_server import (
    BrainConfig,
    BrainModelConfig,
    BrainRetrievalConfig,
    MetisBrainService,
    load_brain_config,
)
from metis_model1.brain_sessions import ClientPolicy, SessionLimits


def _config(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"node")
    metis = tmp_path / "metis"
    metis.mkdir()
    value: dict[str, object] = {
        "schema_version": 1,
        "server": {
            "host": "127.0.0.1",
            "port": 0,
            "runtime_root": str(tmp_path / "runtime"),
        },
        "toolchain": {
            "metis_git_root": str(metis),
            "node_path": str(node),
            "compiler_concurrency": 1,
        },
        "tenants": [{"alias": "demo", "tenant_id": "tenant-one", "root": str(tenant)}],
        "clients": [
            {
                "client_id": "visix",
                "tenant_aliases": ["demo"],
                "capabilities": sorted(CAPABILITIES),
            }
        ],
        "limits": {
            "global_sessions": 16,
            "sessions_per_client": 4,
            "sessions_per_tenant": 4,
        },
    }
    path = tmp_path / "brain-config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def test_load_config_has_no_secret_or_client_controlled_execution_fields(tmp_path: Path) -> None:
    path, _value = _config(tmp_path)
    config = load_brain_config(path.resolve())
    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert config.tenant_grants[0][:2] == ("demo", "tenant-one")
    rendered = json.loads(path.read_text(encoding="utf-8"))

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    for forbidden in ("token", "secret", "password", "argv", "command", "environment"):
        assert forbidden not in keys(rendered)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("server", "host", "0.0.0.0"),
        ("server", "host", "::"),
        ("server", "port", True),
        ("toolchain", "compiler_concurrency", "1"),
    ],
)
def test_config_rejects_wildcard_and_ambiguous_types(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    path, config = _config(tmp_path)
    config[section][field] = value  # type: ignore[index]
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError):
        load_brain_config(path.resolve())


def test_config_rejects_unknown_and_duplicate_fields(tmp_path: Path) -> None:
    path, config = _config(tmp_path)
    config["server"]["command"] = "touch /tmp/owned"  # type: ignore[index]
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError) as raised:
        load_brain_config(path.resolve())
    assert raised.value.code == "INVALID_SCHEMA"

    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(BrainError) as raised:
        load_brain_config(path.resolve())
    assert raised.value.code == "DUPLICATE_FIELD"


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_strict_json_rejects_non_json_numeric_constants(constant: bytes) -> None:
    with pytest.raises(BrainError) as raised:
        parse_json_object(b'{"value":' + constant + b"}")
    assert raised.value.code == "INVALID_JSON"


def test_config_loader_refuses_dotenv_and_symlink_config(tmp_path: Path) -> None:
    path, _config_value = _config(tmp_path)
    dotenv = tmp_path / ".env.brain"
    dotenv.write_bytes(path.read_bytes())
    with pytest.raises(BrainError, match="non-secret"):
        load_brain_config(dotenv.resolve())

    link = tmp_path / "brain-link.json"
    link.symlink_to(path)
    with pytest.raises(BrainError):
        load_brain_config(link)


def test_optional_model_and_schema2_retrieval_config_is_strict(tmp_path: Path) -> None:
    path, config = _config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"python")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config["model"] = {
        "python_path": str(python_path),
        "model_path": str(model_path),
        "adapter_path": str(adapter_path),
        "timeout_seconds": 12.5,
    }
    config["retrieval"] = {"schema2": True}
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded = load_brain_config(path.resolve())
    assert loaded.model == BrainModelConfig(
        python_path=python_path,
        model_path=model_path,
        adapter_path=adapter_path,
        timeout_seconds=12.5,
        warmup="lazy",
    )
    assert loaded.retrieval == BrainRetrievalConfig(schema2=True)

    config["retrieval"] = {"schema2": True, "warmup": "on_start"}
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_brain_config(path.resolve()).retrieval == BrainRetrievalConfig(
        schema2=True, warmup="on_start"
    )

    config["retrieval"] = {"schema2": True, "warmup": "always"}
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError, match="retrieval warmup policy"):
        load_brain_config(path.resolve())

    config["retrieval"] = {"schema2": True, "warmup": []}
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError, match="retrieval warmup policy"):
        load_brain_config(path.resolve())

    config["retrieval"] = {"schema2": False}
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError, match="requires schema2"):
        load_brain_config(path.resolve())

    config["retrieval"] = {"schema2": True, "extra": False}
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError):
        load_brain_config(path.resolve())

    config["model"]["warmup"] = "on_start"  # type: ignore[index]
    config["retrieval"] = {"schema2": True}
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_brain_config(path.resolve()).model == BrainModelConfig(
        python_path=python_path,
        model_path=model_path,
        adapter_path=adapter_path,
        timeout_seconds=12.5,
        warmup="on_start",
    )

    config["model"]["warmup"] = "always"  # type: ignore[index]
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(BrainError, match="warmup policy"):
        load_brain_config(path.resolve())


def test_service_constructor_rejects_nonloopback_even_if_called_without_loader(
    tmp_path: Path,
) -> None:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    metis = tmp_path / "metis"
    metis.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"node")
    config = BrainConfig(
        host="0.0.0.0",
        port=0,
        runtime_root=tmp_path / "runtime",
        metis_git_root=metis,
        node_path=node,
        compiler_concurrency=1,
        tenant_grants=(("demo", "tenant-one", tenant),),
        client_policies=(ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES),),
        limits=SessionLimits(),
    )
    with pytest.raises(BrainError, match="numeric loopback"):
        MetisBrainService(config)


def test_play_demo_fixture_binds_the_workspace_tenant_identity() -> None:
    path = Path(__file__).resolve().parents[1] / "examples/metis-brain-config.play-demo.local.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["tenants"] == [
        {
            "alias": "play-demo",
            "tenant_id": "play-demo",
            "root": "/Users/tommasotessarolo/metis-tenants/play-demo",
        }
    ]
    assert value["model"]["warmup"] == "on_start"
    assert value["retrieval"] == {"schema2": True, "warmup": "on_start"}
