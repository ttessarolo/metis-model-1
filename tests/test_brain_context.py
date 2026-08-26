from __future__ import annotations

import os
from pathlib import Path

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_protocol import BrainError


def _tenant(root: Path, *, tenant_id: str = "tenant-one") -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        f'[tenant]\nid = "{tenant_id}"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (root / "catalogs").mkdir()
    (root / "catalogs/catalog.metis").write_text(
        "metis 0.43\ncatalog sample.items { id item_id fields { item_id keyword } }\n",
        encoding="utf-8",
    )
    return root.resolve()


def _registry(root: Path) -> TenantRegistry:
    return TenantRegistry([("demo", "tenant-one", root.resolve())])


def test_snapshot_is_deterministic_content_bound_and_returns_allowed_sources(
    tmp_path: Path,
) -> None:
    root = _tenant(tmp_path / "tenant")
    (root / ".env").write_text("SECRET=never-read\n", encoding="utf-8")
    registry = _registry(root)

    first = registry.capture("demo", toolchain_binding="sha256:" + "a" * 64)
    second = registry.capture("demo", toolchain_binding="sha256:" + "a" * 64)

    assert first == second
    assert [item.path for item in first.files] == ["catalogs/catalog.metis", "metis.toml"]
    payload = first.public_payload()
    assert {item["path"] for item in payload["files"]} == {
        "catalogs/catalog.metis",
        "metis.toml",
    }
    assert "never-read" not in str(payload)
    assert first.source_map()["catalogs/catalog.metis"].startswith("metis 0.43")
    assert first.total_bytes == sum(len(item.content) for item in first.files)


def test_revision_binds_toolchain_and_tenant_bytes(tmp_path: Path) -> None:
    root = _tenant(tmp_path / "tenant")
    registry = _registry(root)
    initial = registry.capture("demo", toolchain_binding="sha256:" + "a" * 64)
    other_toolchain = registry.capture("demo", toolchain_binding="sha256:" + "b" * 64)
    assert initial.revision != other_toolchain.revision

    (root / "catalogs/catalog.metis").write_text(
        "metis 0.43\ncatalog sample.changed { id item_id fields { item_id keyword } }\n",
        encoding="utf-8",
    )
    changed = registry.capture("demo", toolchain_binding="sha256:" + "a" * 64)
    assert initial.revision != changed.revision
    with pytest.raises(BrainError, match="tenant context changed") as raised:
        registry.assert_current(initial)
    assert raised.value.code == "STALE_CONTEXT"


def test_snapshot_rejects_symlinks_without_reading_external_target(tmp_path: Path) -> None:
    root = _tenant(tmp_path / "tenant")
    sentinel = tmp_path / "external.metis"
    sentinel.write_text("secret sentinel", encoding="utf-8")
    os.symlink(sentinel, root / "catalogs/escape.metis")

    with pytest.raises(BrainError, match="symbolic link") as raised:
        _registry(root).capture("demo", toolchain_binding="sha256:" + "a" * 64)
    assert raised.value.code == "INVALID_TENANT"
    assert sentinel.read_text(encoding="utf-8") == "secret sentinel"


def test_directory_swap_to_symlink_cannot_win_between_stat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tenant(tmp_path / "tenant")
    external = tmp_path / "external"
    external.mkdir()
    (external / "leak.metis").write_text("TOP-SECRET", encoding="utf-8")
    original_open = os.open
    swapped = False

    def racing_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if path == "catalogs" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            (root / "catalogs").rename(root / "catalogs-before-race")
            os.symlink(external, root / "catalogs")
        return original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(BrainError) as raised:
        _registry(root).capture("demo", toolchain_binding="sha256:" + "a" * 64)
    assert raised.value.code in {"STALE_CONTEXT", "INVALID_TENANT"}


def test_snapshot_rejects_wrong_tenant_identity(tmp_path: Path) -> None:
    root = _tenant(tmp_path / "tenant", tenant_id="another")
    with pytest.raises(BrainError, match="identity differs"):
        _registry(root).capture("demo", toolchain_binding="sha256:" + "a" * 64)


def test_registry_detects_root_inode_swap(tmp_path: Path) -> None:
    original = _tenant(tmp_path / "tenant")
    registry = _registry(original)
    moved = tmp_path / "old-tenant"
    original.rename(moved)
    _tenant(tmp_path / "tenant")

    with pytest.raises(BrainError, match="root identity changed") as raised:
        registry.capture("demo", toolchain_binding="sha256:" + "a" * 64)
    assert raised.value.code == "STALE_CONTEXT"


def test_registry_rejects_unknown_alias_and_noncanonical_root(tmp_path: Path) -> None:
    root = _tenant(tmp_path / "tenant")
    registry = _registry(root)
    with pytest.raises(BrainError) as raised:
        registry.grant("missing")
    assert raised.value.code == "TENANT_NOT_AUTHORIZED"

    link = tmp_path / "tenant-link"
    os.symlink(root, link)
    with pytest.raises(BrainError, match="canonical"):
        TenantRegistry([("demo", "tenant-one", link)])
