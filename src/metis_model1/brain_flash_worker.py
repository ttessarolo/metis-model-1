"""Standalone, sandboxed MLX worker for Brain's Flash Intent IR.

This module intentionally uses only the standard library before it verifies the
tracked manifest.  It runs under the separately qualified Python environment,
loads Gemma once, and applies llguidance token masks to every generated token.
The Brain parent process validates the resulting IR again with JSON Schema and
the admitted request.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import stat
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

MAX_LINE_BYTES = 512 * 1024
MAX_TOKENS = 384
EXPECTED_DECODER = "llguidance-1.8.0"
EXPECTED_MODEL_REVISION = "475b9088d29754a3379866cf5aeb6b41acd313c2"
EXPECTED_PACKAGES = {
    "llguidance": "1.8.0",
    "mlx": "0.32.1",
    "mlx-metal": "0.32.1",
    "mlx-vlm": "0.6.15",
    "numpy": "2.5.2",
    "transformers": "5.14.0",
}
OPERATIONS = frozenset({"create", "edit", "repair", "review", "migrate"})
TARGET_SCOPES = {"create": "new", "existing": "existing"}


class WorkerError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise WorkerError(f"invalid {label}") from error
    if not isinstance(value, dict):
        raise WorkerError(f"invalid {label}")
    return value


def _safe_json(path: Path, *, maximum: int = 1024 * 1024) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not 0 < opened.st_size <= maximum
        ):
            raise WorkerError("invalid JSON file")
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named_after = path.lstat()
    except (OSError, WorkerError) as error:
        raise WorkerError("unavailable JSON file") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(named_after)
        or len(raw) != opened.st_size
    ):
        raise WorkerError("JSON file changed while reading")
    return _decode_object(raw, label="JSON file")


def _canonical_path(value: str, *, directory: bool) -> Path:
    path = Path(value)
    if not path.is_absolute() or "\x00" in value:
        raise WorkerError("path is invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise WorkerError("path is unavailable") from error
    if resolved != path or (not resolved.is_dir() if directory else not resolved.is_file()):
        raise WorkerError("path is invalid")
    return resolved


def _verify_runtime(manifest: dict[str, Any]) -> None:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("packages") != EXPECTED_PACKAGES:
        raise WorkerError("runtime manifest differs")
    if runtime.get("decoder") != EXPECTED_DECODER or runtime.get("network") != "denied":
        raise WorkerError("runtime policy differs")
    if sys.version.split()[0] != runtime.get("python"):
        raise WorkerError("Python runtime differs")
    live = {name: importlib.metadata.version(name) for name in EXPECTED_PACKAGES}
    if live != EXPECTED_PACKAGES:
        raise WorkerError("runtime packages differ")


def _verify_model(model_path: Path, manifest: dict[str, Any]) -> str:
    model = manifest.get("model")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "qualified"
        or manifest.get("role") != "metis_brain_flash_intent_compiler"
        or not isinstance(model, dict)
        or model.get("revision") != EXPECTED_MODEL_REVISION
        or model.get("model_type") != "gemma4"
    ):
        raise WorkerError("model manifest differs")
    rows = model.get("files")
    if not isinstance(rows, list) or not rows:
        raise WorkerError("model file roster is invalid")
    expected_names = {row.get("path") for row in rows if isinstance(row, dict)}
    actual_names = {item.name for item in model_path.iterdir()}
    if expected_names != actual_names or len(expected_names) != len(rows):
        raise WorkerError("model file roster differs")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise WorkerError("model file entry is invalid")
        relative = Path(str(row["path"]))
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name != str(relative):
            raise WorkerError("model file entry is invalid")
        path = model_path / relative
        try:
            metadata = path.lstat()
        except OSError as error:
            raise WorkerError("model file is unavailable") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or path.is_symlink()
            or metadata.st_size != row["bytes"]
            or _sha256_file(path) != row["sha256"]
        ):
            raise WorkerError("model file identity differs")
    config = _safe_json(model_path / "config.json")
    quantization = config.get("quantization")
    if (
        config.get("model_type") != "gemma4"
        or not isinstance(quantization, dict)
        or quantization != {"bits": 4, "group_size": 64, "mode": "affine"}
    ):
        raise WorkerError("model configuration differs")
    return str(model["revision"])


def _verify_schema(schema_path: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    schema = _safe_json(schema_path)
    digest = "sha256:" + hashlib.sha256(_canonical(schema)).hexdigest()
    identity = manifest.get("intent_schema")
    if (
        not isinstance(identity, dict)
        or identity.get("path") != "schemas/metis-brain-flash-intent-ir.schema.json"
        or identity.get("canonical_sha256") != digest
    ):
        raise WorkerError("intent schema identity differs")
    return schema, digest


def _request_schema(schema: dict[str, Any], *, operation: str, target_mode: str) -> dict[str, Any]:
    value = deepcopy(schema)
    for key in ("$schema", "$id", "title"):
        value.pop(key, None)
    value["properties"]["operation"] = {"const": operation}
    value["properties"]["target_scope"] = {"const": TARGET_SCOPES[target_mode]}
    return value


def _messages(*, instruction: str, operation: str, target_mode: str) -> list[dict[str, str]]:
    target_scope = TARGET_SCOPES[target_mode]
    system = (
        "Sei il compilatore Flash di intenti per Metis Brain. Produci soltanto l'Intent IR "
        "vincolato, mai codice. Il server ha gia fissato operation e target_scope: copiali. "
        "Estrai in concepts soltanto i requisiti editoriali sui contenuti. Escludi comandi, "
        "nomi di endpoint, quantita, formato, fallback, istruzioni di mantenimento, response.* "
        "e ordinamento. Non trasformare questi controlli in concepts. Crea un elemento separato "
        "per ogni "
        "requisito che potrebbe diventare un filtro indipendente. source deve essere la "
        "citazione minima, esatta e contigua della richiesta. Non includere all'inizio di source "
        "verbi come crea, modifica, verifica, seleziona o mantieni, ne formule come 'una selezione "
        "di': per 'verifica una selezione di film' source e soltanto 'film'. query puo chiarire "
        "soltanto la "
        "stessa idea in italiano; non puo aggiungere requisiti. Non usare nomi tecnici di "
        "cataloghi, campi o valori, non usare @ e non generare DSL. polarity e exclude solo "
        "per una negazione esplicita. concept_logic descrive la logica tra requisiti. "
        "response_format e fallback classificano solo richieste esplicite e non autorizzano "
        "alcuna azione. Segnala soltanto ambiguita reali. Esempio: 'crea 12 film francesi, "
        "comici e senza violenza' produce quattro concepts separati: 'film'; 'francesi' con "
        "query 'paese di produzione Francia'; 'comici' con query 'tono comico'; 'senza "
        "violenza' con query 'violenza' e polarity exclude."
    )
    user = (
        f"DECLARED_OPERATION={operation}\n"
        f"DECLARED_TARGET_SCOPE={target_scope}\n"
        "INSTRUCTION=" + instruction.strip()
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _GrammarProcessor:
    def __init__(self, *, tokenizer: Any, grammar: str, vocab_size: int) -> None:
        from llguidance import LLMatcher
        from llguidance.numpy import allocate_token_bitmask

        self._matcher = LLMatcher(tokenizer, grammar, log_level=0)
        if self._matcher.is_error():
            raise WorkerError("constrained grammar is invalid")
        self._prompt_length: int | None = None
        self._committed = 0
        self._mask = allocate_token_bitmask(1, vocab_size)

    def __call__(self, tokens: Any, logits: Any) -> Any:
        from llguidance.mlx import apply_token_bitmask
        from llguidance.numpy import fill_next_token_bitmask

        token_ids = tokens.tolist()
        if token_ids and isinstance(token_ids[0], list):
            token_ids = token_ids[0]
        if self._prompt_length is None:
            self._prompt_length = len(token_ids)
        for token in token_ids[self._prompt_length + self._committed :]:
            if not self._matcher.consume_token(int(token)):
                raise WorkerError("constrained grammar rejected a generated token")
            self._committed += 1
        fill_next_token_bitmask(self._matcher, self._mask)
        one_dimensional = len(logits.shape) == 1
        masked = apply_token_bitmask(logits, self._mask)
        return masked[0] if one_dimensional else masked


def _strict_request(raw: bytes) -> dict[str, Any]:
    return _decode_object(raw, label="worker request")


def _write(value: dict[str, Any]) -> None:
    raw = _canonical(value) + b"\n"
    if len(raw) > MAX_LINE_BYTES:
        raise WorkerError("worker response is too large")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def worker(*, model_path: Path, manifest_path: Path, schema_path: Path) -> int:
    manifest = _safe_json(manifest_path)
    _verify_runtime(manifest)
    model_revision = _verify_model(model_path, manifest)
    schema, schema_sha256 = _verify_schema(schema_path, manifest)

    from llguidance import LLMatcher
    from llguidance.hf import from_tokenizer
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    load_started = time.monotonic()
    model, processor = load(model_path, lazy=False)
    worker_load_ms = max(0, int((time.monotonic() - load_started) * 1000))
    if getattr(model.config, "model_type", None) != "gemma4":
        raise WorkerError("loaded model type differs")
    tokenizer = processor.tokenizer if hasattr(processor, "tokenizer") else processor
    if not getattr(tokenizer, "is_fast", False):
        raise WorkerError("Flash tokenizer is not grammar compatible")
    ll_tokenizer = from_tokenizer(
        tokenizer,
        n_vocab=len(tokenizer),
        eos_token=tokenizer.eos_token_id,
        slices=[],
    )

    while True:
        raw = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
            raise WorkerError("worker request is too large")
        request = _strict_request(raw[:-1])
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise WorkerError("worker request ID is invalid")
        if request.get("operation") == "warmup":
            if set(request) != {"request_id", "operation"}:
                raise WorkerError("warmup request is invalid")
            _write(
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "status": "ready",
                    "worker_load_ms": worker_load_ms,
                    "model_revision": model_revision,
                    "schema_sha256": schema_sha256,
                    "decoder": EXPECTED_DECODER,
                }
            )
            continue
        if (
            set(request)
            != {
                "request_id",
                "operation",
                "instruction",
                "intent",
                "target_mode",
                "max_tokens",
            }
            or request.get("operation") != "compile"
        ):
            raise WorkerError("compile request is invalid")
        instruction = request["instruction"]
        operation = request["intent"]
        target_mode = request["target_mode"]
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction.encode("utf-8")) > 512 * 1024
            or operation not in OPERATIONS
            or target_mode not in TARGET_SCOPES
            or request["max_tokens"] != MAX_TOKENS
        ):
            raise WorkerError("compile request is invalid")
        constrained = _request_schema(schema, operation=operation, target_mode=target_mode)
        grammar = LLMatcher.grammar_from_json_schema(
            constrained,
            overrides={"whitespace_flexible": False},
        )
        grammar_error, warnings = LLMatcher.validate_grammar_with_warnings(grammar, ll_tokenizer)
        if grammar_error or warnings:
            raise WorkerError("constrained grammar failed validation")
        prompt = apply_chat_template(
            processor,
            model.config,
            _messages(instruction=instruction, operation=operation, target_mode=target_mode),
            add_generation_prompt=True,
        )
        generation_started = time.monotonic()
        result = generate(
            model,
            processor,
            prompt,
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            logits_processors=[
                _GrammarProcessor(
                    tokenizer=ll_tokenizer,
                    grammar=grammar,
                    vocab_size=ll_tokenizer.vocab_size,
                )
            ],
            verbose=False,
        )
        generation_ms = max(0, int((time.monotonic() - generation_started) * 1000))
        intent_ir = _decode_object(result.text.encode("utf-8"), label="constrained generation")
        finish_reason = str(getattr(result, "finish_reason", "length"))
        if finish_reason != "stop":
            raise WorkerError("constrained generation did not finish")
        metrics = {
            "worker_load_ms": worker_load_ms,
            "generation_ms": generation_ms,
            "prompt_tokens": int(getattr(result, "prompt_tokens", 0)),
            "generation_tokens": int(getattr(result, "generation_tokens", 0)),
            "prompt_tps": float(getattr(result, "prompt_tps", 0.0)),
            "generation_tps": float(getattr(result, "generation_tps", 0.0)),
            "finish_reason": finish_reason,
            "peak_metal_gb": float(getattr(result, "peak_memory", 0.0)),
        }
        if any(
            not math.isfinite(float(value))
            for key, value in metrics.items()
            if key in {"prompt_tps", "generation_tps", "peak_metal_gb"}
        ):
            raise WorkerError("generation telemetry is invalid")
        _write(
            {
                "schema_version": 1,
                "request_id": request_id,
                "intent_ir": intent_ir,
                "model_revision": model_revision,
                "schema_sha256": schema_sha256,
                "decoder": EXPECTED_DECODER,
                "metrics": metrics,
            }
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("worker",))
    parser.add_argument("--model", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args(argv)
    try:
        return worker(
            model_path=_canonical_path(args.model, directory=True),
            manifest_path=_canonical_path(args.manifest, directory=False),
            schema_path=_canonical_path(args.schema, directory=False),
        )
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            return 130
        print("Flash worker failed closed", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
