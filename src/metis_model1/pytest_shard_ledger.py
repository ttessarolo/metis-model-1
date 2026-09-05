"""Private, bounded pytest outcome ledger used by the deterministic test harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEDGER_CONTRACT = "metis-model1-pytest-shard-ledger/v1"
MAX_LEDGER_BYTES = 64 * 1024 * 1024
MAX_NODEIDS = 10_000
MAX_NODEID_BYTES = 64 * 1024
MAX_SKIP_REASON_BYTES = 4 * 1024
_SHARD_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_OUTCOMES = frozenset({"passed", "skipped", "failed", "error", "xfailed", "xpassed"})


class ShardLedgerError(RuntimeError):
    """Raised when a pytest shard ledger is not exact, stable, and private."""


@dataclass(frozen=True)
class LedgerOutcome:
    nodeid: str
    outcome: str
    skip_reason: str | None


@dataclass(frozen=True)
class ShardLedger:
    shard_id: str
    mode: str
    exitstatus: int
    collected_nodeids: tuple[str, ...]
    outcomes: tuple[LedgerOutcome, ...]
    collection_sha256: str
    ledger_sha256: str


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ShardLedgerError(f"{label} fields differ")
    return value


def _nodeid(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or len(value.encode("utf-8")) > MAX_NODEID_BYTES
    ):
        raise ShardLedgerError("pytest nodeid is invalid")
    return value


def _skip_reason(value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_SKIP_REASON_BYTES
    ):
        raise ShardLedgerError("pytest skip reason is invalid")
    return value


def _private_parent(path: Path) -> Path:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ShardLedgerError("ledger path is invalid")
    try:
        parent = path.parent.resolve(strict=True)
        metadata = parent.lstat()
    except OSError as error:
        raise ShardLedgerError("ledger parent is unavailable") from error
    if (
        parent != path.parent
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ShardLedgerError("ledger parent is not a private stable directory")
    return parent


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_private_file(path: Path) -> bytes:
    _private_parent(path)
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = MAX_LEDGER_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise ShardLedgerError("ledger is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    raw = b"".join(chunks)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
        or not 0 < before.st_size <= MAX_LEDGER_BYTES
        or len(raw) != before.st_size
        or _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(path_after)
    ):
        raise ShardLedgerError("ledger is not a stable private regular file")
    return raw


def _body(
    *,
    shard_id: str,
    mode: str,
    exitstatus: int,
    collected_nodeids: tuple[str, ...],
    outcomes: tuple[LedgerOutcome, ...],
) -> dict[str, Any]:
    if not _SHARD_ID.fullmatch(shard_id):
        raise ShardLedgerError("ledger shard id is invalid")
    if mode not in {"collect", "execute"}:
        raise ShardLedgerError("ledger mode is invalid")
    if type(exitstatus) is not int or not 0 <= exitstatus <= 5:
        raise ShardLedgerError("ledger exit status is invalid")
    if type(collected_nodeids) is not tuple or type(outcomes) is not tuple:
        raise ShardLedgerError("ledger rosters must be immutable tuples")
    if len(collected_nodeids) > MAX_NODEIDS:
        raise ShardLedgerError("ledger collection exceeds its bound")
    collected = tuple(_nodeid(item) for item in collected_nodeids)
    if len(set(collected)) != len(collected):
        raise ShardLedgerError("ledger collection contains duplicate nodeids")
    if mode == "collect" and outcomes:
        raise ShardLedgerError("collection ledger contains execution outcomes")
    if len(outcomes) > len(collected):
        raise ShardLedgerError("ledger contains excess outcomes")
    normalized_outcomes: list[dict[str, object]] = []
    seen: set[str] = set()
    positions = {nodeid: index for index, nodeid in enumerate(collected)}
    previous = -1
    for item in outcomes:
        if type(item) is not LedgerOutcome:
            raise ShardLedgerError("ledger outcome entry is invalid")
        nodeid = _nodeid(item.nodeid)
        if nodeid in seen or nodeid not in positions or positions[nodeid] <= previous:
            raise ShardLedgerError("ledger outcomes differ from collection order")
        if item.outcome not in _OUTCOMES:
            raise ShardLedgerError("ledger outcome is invalid")
        reason = _skip_reason(
            item.skip_reason,
            required=item.outcome in {"skipped", "xfailed"},
        )
        if item.outcome not in {"skipped", "xfailed"} and reason is not None:
            raise ShardLedgerError("non-skipped outcome contains a skip reason")
        normalized_outcomes.append(
            {"nodeid": nodeid, "outcome": item.outcome, "skip_reason": reason}
        )
        previous = positions[nodeid]
        seen.add(nodeid)
    counts = {name: sum(item.outcome == name for item in outcomes) for name in sorted(_OUTCOMES)}
    counts.update({"collected": len(collected), "outcomes": len(outcomes)})
    return {
        "collection_sha256": _sha256(list(collected)),
        "collected_nodeids": list(collected),
        "contract": LEDGER_CONTRACT,
        "counts": counts,
        "exitstatus": exitstatus,
        "mode": mode,
        "outcomes": normalized_outcomes,
        "shard_id": shard_id,
    }


def write_private_ledger(
    path: Path,
    *,
    shard_id: str,
    mode: str,
    exitstatus: int,
    collected_nodeids: tuple[str, ...],
    outcomes: tuple[LedgerOutcome, ...],
) -> ShardLedger:
    """Atomically create one canonical 0600 ledger in an existing 0700 directory."""

    target = Path(path)
    parent = _private_parent(target)
    if target.exists() or target.is_symlink():
        raise ShardLedgerError("ledger target already exists")
    body = _body(
        shard_id=shard_id,
        mode=mode,
        exitstatus=exitstatus,
        collected_nodeids=collected_nodeids,
        outcomes=outcomes,
    )
    value = {**body, "ledger_sha256": _sha256(body)}
    raw = _canonical_json(value)
    if len(raw) > MAX_LEDGER_BYTES:
        raise ShardLedgerError("ledger exceeds its byte bound")
    temporary = parent / f".{target.name}.{os.getpid()}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise ShardLedgerError("ledger write was incomplete")
            written += count
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_size != len(raw)
        ):
            raise ShardLedgerError("ledger staging file is not private")
        os.close(descriptor)
        descriptor = None
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise ShardLedgerError("cannot publish shard ledger") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
    return read_private_ledger(target, expected_shard_id=shard_id, expected_mode=mode)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ShardLedgerError("ledger JSON contains duplicate keys")
        value[key] = item
    return value


def read_private_ledger(
    path: Path,
    *,
    expected_shard_id: str,
    expected_mode: str,
) -> ShardLedger:
    """Read and independently validate one stable canonical shard ledger."""

    raw = _read_stable_private_file(Path(path))
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ShardLedgerError(f"ledger contains non-finite number {item}")
            ),
        )
    except ShardLedgerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShardLedgerError("ledger is not valid UTF-8 JSON") from error
    obj = _exact_object(
        value,
        {
            "collection_sha256",
            "collected_nodeids",
            "contract",
            "counts",
            "exitstatus",
            "ledger_sha256",
            "mode",
            "outcomes",
            "shard_id",
        },
        "ledger",
    )
    if _canonical_json(obj) != raw:
        raise ShardLedgerError("ledger is not canonical JSON")
    ledger_sha256 = obj.pop("ledger_sha256")
    try:
        if type(ledger_sha256) is not str or ledger_sha256 != _sha256(obj):
            raise ShardLedgerError("ledger self-hash differs")
        if obj["contract"] != LEDGER_CONTRACT:
            raise ShardLedgerError("ledger contract differs")
        if obj["shard_id"] != expected_shard_id or obj["mode"] != expected_mode:
            raise ShardLedgerError("ledger binding differs")
        raw_collected = obj["collected_nodeids"]
        raw_outcomes = obj["outcomes"]
        if type(raw_collected) is not list or type(raw_outcomes) is not list:
            raise ShardLedgerError("ledger rosters are invalid")
        outcomes: list[LedgerOutcome] = []
        for raw_outcome in raw_outcomes:
            outcome_obj = _exact_object(
                raw_outcome,
                {"nodeid", "outcome", "skip_reason"},
                "ledger outcome",
            )
            outcomes.append(
                LedgerOutcome(
                    nodeid=outcome_obj["nodeid"],
                    outcome=outcome_obj["outcome"],
                    skip_reason=outcome_obj["skip_reason"],
                )
            )
        body = _body(
            shard_id=obj["shard_id"],
            mode=obj["mode"],
            exitstatus=obj["exitstatus"],
            collected_nodeids=tuple(raw_collected),
            outcomes=tuple(outcomes),
        )
        if obj != body:
            raise ShardLedgerError("ledger derived fields differ")
        counts = _exact_object(
            obj["counts"],
            {"collected", "error", "failed", "outcomes", "passed", "skipped", "xfailed", "xpassed"},
            "ledger counts",
        )
        if any(type(item) is not int or item < 0 for item in counts.values()):
            raise ShardLedgerError("ledger counts are invalid")
        return ShardLedger(
            shard_id=obj["shard_id"],
            mode=obj["mode"],
            exitstatus=obj["exitstatus"],
            collected_nodeids=tuple(raw_collected),
            outcomes=tuple(outcomes),
            collection_sha256=obj["collection_sha256"],
            ledger_sha256=ledger_sha256,
        )
    finally:
        obj["ledger_sha256"] = ledger_sha256


def _report_skip_reason(report: Any) -> str:
    was_xfail = getattr(report, "wasxfail", None)
    if type(was_xfail) is str and was_xfail:
        return was_xfail
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
    else:
        reason = str(longrepr)
    return reason.strip() or "pytest skipped without a reason"


class _ShardLedgerPlugin:
    def __init__(self, path: Path, shard_id: str) -> None:
        self._path = path
        self._shard_id = shard_id
        self._collected: tuple[str, ...] = ()
        self._collected_set: frozenset[str] = frozenset()
        self._outcomes: dict[str, LedgerOutcome] = {}

    def pytest_collection_finish(self, session: Any) -> None:
        self._collected = tuple(item.nodeid for item in session.items)
        self._collected_set = frozenset(self._collected)
        _body(
            shard_id=self._shard_id,
            mode="collect" if session.config.option.collectonly else "execute",
            exitstatus=0,
            collected_nodeids=self._collected,
            outcomes=(),
        )

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.nodeid not in self._collected_set:
            raise ShardLedgerError("pytest reported an uncollected nodeid")
        was_xfail = getattr(report, "wasxfail", None)
        outcome: LedgerOutcome | None = None
        if report.when == "setup" and report.failed:
            outcome = LedgerOutcome(report.nodeid, "error", None)
        elif report.when == "setup" and report.skipped:
            outcome = LedgerOutcome(
                report.nodeid,
                "xfailed" if was_xfail else "skipped",
                _report_skip_reason(report),
            )
        elif report.when == "call":
            if report.failed:
                outcome = LedgerOutcome(report.nodeid, "failed", None)
            elif report.skipped:
                outcome = LedgerOutcome(
                    report.nodeid,
                    "xfailed" if was_xfail else "skipped",
                    _report_skip_reason(report),
                )
            elif report.passed:
                outcome = LedgerOutcome(
                    report.nodeid,
                    "xpassed" if was_xfail else "passed",
                    None,
                )
        elif report.when == "teardown" and report.failed:
            outcome = LedgerOutcome(report.nodeid, "error", None)
        if outcome is not None:
            self._outcomes[report.nodeid] = outcome

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        mode = "collect" if session.config.option.collectonly else "execute"
        positions = {nodeid: index for index, nodeid in enumerate(self._collected)}
        outcomes = tuple(sorted(self._outcomes.values(), key=lambda item: positions[item.nodeid]))
        write_private_ledger(
            self._path,
            shard_id=self._shard_id,
            mode=mode,
            exitstatus=int(exitstatus),
            collected_nodeids=self._collected,
            outcomes=outcomes,
        )


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("metis-model1-shard-ledger")
    group.addoption("--metis-shard-ledger", action="store", default=None)
    group.addoption("--metis-shard-id", action="store", default=None)


def pytest_configure(config: Any) -> None:
    path = config.getoption("metis_shard_ledger")
    shard_id = config.getoption("metis_shard_id")
    if path is None and shard_id is None:
        return
    if type(path) is not str or type(shard_id) is not str:
        raise ShardLedgerError("both shard ledger options are required")
    target = Path(path)
    _private_parent(target)
    if not _SHARD_ID.fullmatch(shard_id):
        raise ShardLedgerError("ledger shard id is invalid")
    config.pluginmanager.register(_ShardLedgerPlugin(target, shard_id), "metis-shard-ledger")
