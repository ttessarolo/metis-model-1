from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_protocol import CAPABILITIES, BrainError
from metis_model1.brain_sessions import ClientPolicy, SessionLimits, SessionManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tenant(root: Path) -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        '[tenant]\nid = "tenant-one"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (root / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
    return root.resolve()


def _manager(
    tmp_path: Path,
    clock: FakeClock,
    *,
    capabilities: frozenset[str] = CAPABILITIES,
    limits: SessionLimits | None = None,
) -> tuple[SessionManager, Path]:
    tenant = _tenant(tmp_path / "tenant")
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", tenant)]),
        policies=[
            ClientPolicy(
                client_id="visix",
                tenant_aliases=frozenset({"demo"}),
                capabilities=capabilities,
            )
        ],
        runtime_root=(tmp_path / "runtime").resolve(),
        toolchain_binding="sha256:" + "a" * 64,
        limits=limits,
        monotonic=clock,
    )
    return manager, tenant


def _open(manager: SessionManager, capabilities: frozenset[str] = CAPABILITIES):
    return manager.create_session(
        client_id="visix",
        tenant_alias="demo",
        requested_capabilities=capabilities,
    )


def test_ttl_is_alive_before_1200_and_expired_at_exact_boundary(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    overlay = next(manager.runtime_root.glob("session-*"))

    clock.advance(1199.999)
    assert (
        manager.status(session_id=opened.session_id, token=opened.token)["session"]["state"]
        == "active"
    )
    clock.advance(0.001)
    with pytest.raises(BrainError) as raised:
        manager.status(session_id=opened.session_id, token=opened.token)
    assert raised.value.code == "SESSION_UNAVAILABLE"
    assert not overlay.exists()


def test_status_and_failed_auth_do_not_refresh_ttl(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    clock.advance(900)
    manager.status(session_id=opened.session_id, token=opened.token)
    with pytest.raises(BrainError):
        manager.status(session_id=opened.session_id, token="wrong")
    clock.advance(300)
    with pytest.raises(BrainError) as raised:
        manager.status(session_id=opened.session_id, token=opened.token)
    assert raised.value.code == "SESSION_UNAVAILABLE"


def test_admitted_semantic_operation_refreshes_activity(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    clock.advance(1000)
    with manager.operation(
        session_id=opened.session_id,
        token=opened.token,
        capability="context.read",
        expected_revision=opened.context_revision,
    ):
        pass
    clock.advance(1199.999)
    assert (
        manager.status(session_id=opened.session_id, token=opened.token)["session"]["state"]
        == "active"
    )
    clock.advance(0.001)
    with pytest.raises(BrainError):
        manager.status(session_id=opened.session_id, token=opened.token)


def test_inflight_operation_does_not_expire_mid_run_but_expires_after_release(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    with manager.operation(
        session_id=opened.session_id,
        token=opened.token,
        capability="compile",
        expected_revision=opened.context_revision,
    ):
        clock.advance(1200)
        assert manager.sweep_expired() == 0
        assert manager.aggregate_metrics()["in_flight"] == 1
    with pytest.raises(BrainError) as raised:
        manager.status(session_id=opened.session_id, token=opened.token)
    assert raised.value.code == "SESSION_UNAVAILABLE"


def test_wrong_expected_revision_fails_before_operation_admission(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    clock.advance(1000)
    with (
        pytest.raises(BrainError) as raised,
        manager.operation(
            session_id=opened.session_id,
            token=opened.token,
            capability="compile",
            expected_revision="sha256:" + "b" * 64,
        ),
    ):
        raise AssertionError("operation must not start")
    assert raised.value.code == "STALE_CONTEXT"
    clock.advance(200)
    with pytest.raises(BrainError):
        manager.status(session_id=opened.session_id, token=opened.token)


def test_same_tenant_sessions_have_independent_tokens_ttl_and_overlays(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    first = _open(manager)
    clock.advance(100)
    second = _open(manager)
    assert first.token != second.token
    assert first.context_revision == second.context_revision
    assert len(list(manager.runtime_root.glob("session-*"))) == 2

    with pytest.raises(BrainError):
        manager.status(session_id=second.session_id, token=first.token)
    clock.advance(1100)
    with pytest.raises(BrainError):
        manager.status(session_id=first.session_id, token=first.token)
    assert (
        manager.status(session_id=second.session_id, token=second.token)["session"]["state"]
        == "active"
    )


def test_two_tenants_are_isolated_and_unauthorized_alias_is_denied(tmp_path: Path) -> None:
    clock = FakeClock()
    first_root = _tenant(tmp_path / "tenant-one")
    second_root = tmp_path / "tenant-two"
    second_root.mkdir()
    (second_root / "metis.toml").write_text(
        '[tenant]\nid = "tenant-two"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (second_root / "main.metis").write_text("metis 0.43\ntenant tenant_two {}\n", encoding="utf-8")
    manager = SessionManager(
        registry=TenantRegistry(
            [
                ("first", "tenant-one", first_root),
                ("second", "tenant-two", second_root.resolve()),
            ]
        ),
        policies=[
            ClientPolicy("visix", frozenset({"first", "second"}), CAPABILITIES),
            ClientPolicy("fast", frozenset({"first"}), CAPABILITIES),
        ],
        runtime_root=(tmp_path / "runtime").resolve(),
        toolchain_binding="sha256:" + "a" * 64,
        monotonic=clock,
    )
    first = manager.create_session(
        client_id="visix", tenant_alias="first", requested_capabilities=CAPABILITIES
    )
    second = manager.create_session(
        client_id="visix", tenant_alias="second", requested_capabilities=CAPABILITIES
    )
    assert first.context_revision != second.context_revision
    with pytest.raises(BrainError) as raised:
        manager.create_session(
            client_id="fast", tenant_alias="second", requested_capabilities=CAPABILITIES
        )
    assert raised.value.code == "TENANT_NOT_AUTHORIZED"
    with pytest.raises(BrainError):
        manager.status(session_id=second.session_id, token=first.token)


def test_capabilities_are_immutable_and_default_deny(tmp_path: Path) -> None:
    clock = FakeClock()
    allowed = frozenset({"session.read", "context.read"})
    manager, _tenant_root = _manager(tmp_path, clock, capabilities=allowed)
    opened = _open(manager, allowed)
    with (
        pytest.raises(BrainError) as raised,
        manager.operation(
            session_id=opened.session_id,
            token=opened.token,
            capability="compile",
            expected_revision=opened.context_revision,
        ),
    ):
        pass
    assert raised.value.code == "CAPABILITY_DENIED"
    with pytest.raises(BrainError) as raised:
        manager.close(session_id=opened.session_id, token=opened.token)
    assert raised.value.code == "CAPABILITY_DENIED"


def test_close_revokes_before_inflight_result_and_cleans_once(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    admitted = threading.Event()
    finish = threading.Event()
    observed: list[str] = []

    def worker() -> None:
        try:
            with manager.operation(
                session_id=opened.session_id,
                token=opened.token,
                capability="compile",
                expected_revision=opened.context_revision,
            ) as lease:
                admitted.set()
                finish.wait(timeout=5)
                assert lease.cancellation.is_set()
        except BrainError as error:
            observed.append(error.code)

    thread = threading.Thread(target=worker)
    thread.start()
    assert admitted.wait(timeout=5)
    response = manager.close(session_id=opened.session_id, token=opened.token)
    assert response["session"]["state"] == "closing"
    with pytest.raises(BrainError):
        manager.status(session_id=opened.session_id, token=opened.token)
    finish.set()
    thread.join(timeout=5)
    assert observed == ["SESSION_REVOKED"]
    assert not list(manager.runtime_root.glob("session-*"))


def test_post_operation_stale_guard_discards_result(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, tenant = _manager(tmp_path, clock)
    opened = _open(manager)
    with (
        pytest.raises(BrainError) as raised,
        manager.operation(
            session_id=opened.session_id,
            token=opened.token,
            capability="compile",
            expected_revision=opened.context_revision,
        ),
    ):
        (tenant / "main.metis").write_text("metis 0.43\ntenant changed {}\n", encoding="utf-8")
    assert raised.value.code == "STALE_CONTEXT"


def test_session_limits_fail_before_overlay_allocation(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(
        tmp_path,
        clock,
        limits=SessionLimits(global_sessions=1, sessions_per_client=1, sessions_per_tenant=1),
    )
    _open(manager)
    with pytest.raises(BrainError) as raised:
        _open(manager)
    assert raised.value.code == "SESSION_LIMIT"
    assert len(list(manager.runtime_root.glob("session-*"))) == 1


def test_pending_snapshot_capture_reserves_capacity(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(
        tmp_path,
        clock,
        limits=SessionLimits(global_sessions=1, sessions_per_client=1, sessions_per_tenant=1),
    )
    original_capture = manager._registry.capture
    entered = threading.Event()
    release = threading.Event()

    def slow_capture(*args: object, **kwargs: object):
        entered.set()
        release.wait(timeout=5)
        return original_capture(*args, **kwargs)

    manager._registry.capture = slow_capture  # type: ignore[method-assign]
    opened: list[object] = []
    thread = threading.Thread(target=lambda: opened.append(_open(manager)))
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(BrainError) as raised:
        _open(manager)
    assert raised.value.code == "SESSION_LIMIT"
    release.set()
    thread.join(timeout=5)
    assert len(opened) == 1


def test_cleanup_unlinks_overlay_symlink_without_touching_sentinel(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    overlay = next(manager.runtime_root.glob("session-*"))
    sentinel = tmp_path / "external-sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    os.symlink(sentinel, overlay / "escape")

    manager.close(session_id=opened.session_id, token=opened.token)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not overlay.exists()


def test_cleanup_failure_keeps_revoked_session_and_reaper_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    overlay = next(manager.runtime_root.glob("session-*"))
    original_rmdir = Path.rmdir
    fail_once = True

    def failing_rmdir(path: Path) -> None:
        nonlocal fail_once
        if path == overlay and fail_once:
            fail_once = False
            raise OSError("injected cleanup failure")
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", failing_rmdir)
    with pytest.raises(BrainError) as raised:
        manager.close(session_id=opened.session_id, token=opened.token)
    assert raised.value.code == "CLEANUP_FAILED"
    assert manager.aggregate_metrics()["sessions"] == 1
    with pytest.raises(BrainError):
        manager.status(session_id=opened.session_id, token=opened.token)
    assert manager.sweep_expired() == 1
    assert manager.aggregate_metrics()["sessions"] == 0


def test_brain_error_from_operation_body_preserves_public_error(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    opened = _open(manager)
    with (
        pytest.raises(BrainError) as raised,
        manager.operation(
            session_id=opened.session_id,
            token=opened.token,
            capability="compile",
            expected_revision=opened.context_revision,
        ),
    ):
        raise BrainError("COMPILER_BUSY", 429, "compiler capacity is exhausted")
    assert raised.value.code == "COMPILER_BUSY"


def test_shutdown_revokes_all_sessions_and_removes_overlays(tmp_path: Path) -> None:
    clock = FakeClock()
    manager, _tenant_root = _manager(tmp_path, clock)
    _open(manager)
    _open(manager)
    manager.shutdown()
    assert manager.aggregate_metrics() == {"sessions": 0, "active": 0, "in_flight": 0}
    assert not list(manager.runtime_root.glob("session-*"))
