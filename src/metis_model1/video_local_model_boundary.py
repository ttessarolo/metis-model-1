"""Fail-closed client boundary for a pinned Ollama model on loopback.

This module is intentionally a small transport boundary, not a model runner.
It talks only to an explicitly configured numeric IPv4 loopback HTTP endpoint,
checks the expected model digest before and after one non-streaming request,
and returns a schema-validated response with a payload-free receipt.  It never
reads environment variables, credentials, private stores, or tenant data.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 600.0
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_MODEL_NAME_CHARS = 256
MAX_TEXT_CHARS = 1_000_000
MAX_TAGS = 100_000
MAX_MESSAGES = 100_000
SHA256_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
OLLAMA_DIGEST_RE = re.compile(r"\A(?:sha256:)?([0-9a-f]{64})\Z")

_TAG_KEYS = frozenset({"name", "model", "modified_at", "size", "digest", "details", "capabilities"})
_CHAT_KEYS = frozenset(
    {
        "model",
        "created_at",
        "message",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    }
)
_GENERATE_KEYS = frozenset(
    {
        "model",
        "created_at",
        "response",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    }
)
_MESSAGE_KEYS = frozenset({"role", "content"})
_ROLES = frozenset({"system", "user", "assistant", "tool"})


class LocalModelBoundaryError(ValueError):
    """A stable, payload-free boundary failure."""


def _fail(code: str) -> LocalModelBoundaryError:
    # Never include a URL, exception text, request text, response text, or model
    # output in a boundary error.  Callers can safely display ``str(error)``.
    return LocalModelBoundaryError(code)


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _fail("canonical JSON failure") from None


def _bounded_string(value: Any, *, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _fail(code)
    if any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise _fail(code)
    return value


def _bounded_text(value: Any, *, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _fail(code)
    if any(
        (ord(character) < 0x20 and character not in "\t\n\r") or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise _fail(code)
    return value


def _validate_digest(value: Any, code: str = "invalid model digest") -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise _fail(code)
    return value


def _validate_ollama_digest(value: Any, code: str = "invalid model digest") -> str:
    if not isinstance(value, str):
        raise _fail(code)
    match = OLLAMA_DIGEST_RE.fullmatch(value)
    if match is None:
        raise _fail(code)
    return "sha256:" + match.group(1)


def _reject_constant(_token: str) -> None:
    raise _fail("non-finite JSON number")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("duplicate JSON key")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> Any:
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise _fail("JSON response exceeds byte cap")
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except LocalModelBoundaryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _fail("response is not one complete JSON document") from None


def _exact_keys(
    value: Mapping[str, Any], allowed: frozenset[str], required: frozenset[str], code: str
) -> None:
    keys = set(value)
    if keys - allowed or required - keys:
        raise _fail(code)


def _validate_tags(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, dict):
        raise _fail("tags response schema invalid")
    _exact_keys(value, frozenset({"models"}), frozenset({"models"}), "tags response schema invalid")
    models = value["models"]
    if not isinstance(models, list) or len(models) > MAX_TAGS:
        raise _fail("tags response schema invalid")
    validated: list[Mapping[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise _fail("tags response schema invalid")
        _exact_keys(model, _TAG_KEYS, frozenset({"digest"}), "tags response schema invalid")
        names = [model[key] for key in ("name", "model") if key in model]
        if not names:
            raise _fail("tags response schema invalid")
        for name in names:
            _bounded_string(name, maximum=MAX_MODEL_NAME_CHARS, code="tags response schema invalid")
        normalized_digest = _validate_ollama_digest(model["digest"], "tags response schema invalid")
        if "size" in model and (type(model["size"]) is not int or model["size"] < 0):
            raise _fail("tags response schema invalid")
        if "modified_at" in model:
            _bounded_string(model["modified_at"], maximum=128, code="tags response schema invalid")
        details = model.get("details")
        if details is not None and (
            not isinstance(details, Mapping) or len(_canonical(details)) > 64 * 1024
        ):
            raise _fail("tags response schema invalid")
        capabilities = model.get("capabilities")
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or len(capabilities) > 64
            or any(
                not isinstance(item, str)
                or not item
                or len(item) > 128
                or any(ord(character) < 0x20 for character in item)
                for item in capabilities
            )
        ):
            raise _fail("tags response schema invalid")
        validated.append({**model, "digest": normalized_digest})
    return validated


def _find_model(models: Sequence[Mapping[str, Any]], expected_name: str) -> str:
    matches: list[str] = []
    for model in models:
        if expected_name in (model.get("name"), model.get("model")):
            matches.append(model["digest"])
    if len(matches) != 1:
        raise _fail("expected model is not uniquely available")
    return _validate_digest(matches[0], "invalid model digest")


def _validate_chat_response(value: Any, expected_model: str) -> tuple[str, bool]:
    if not isinstance(value, dict):
        raise _fail("chat response schema invalid")
    _exact_keys(
        value, _CHAT_KEYS, frozenset({"model", "message", "done"}), "chat response schema invalid"
    )
    model = _bounded_string(
        value["model"], maximum=MAX_MODEL_NAME_CHARS, code="chat response schema invalid"
    )
    if model != expected_model or type(value["done"]) is not bool:
        raise _fail("chat response schema invalid")
    _validate_response_metadata(value, "chat response schema invalid")
    message = value["message"]
    if not isinstance(message, dict):
        raise _fail("chat response schema invalid")
    _exact_keys(
        message, _MESSAGE_KEYS, frozenset({"role", "content"}), "chat response schema invalid"
    )
    if message["role"] != "assistant":
        raise _fail("chat response schema invalid")
    content = _bounded_text(
        message["content"], maximum=MAX_TEXT_CHARS, code="chat response schema invalid"
    )
    return content, value["done"]


def _validate_generate_response(value: Any, expected_model: str) -> tuple[str, bool]:
    if not isinstance(value, dict):
        raise _fail("generate response schema invalid")
    _exact_keys(
        value,
        _GENERATE_KEYS,
        frozenset({"model", "response", "done"}),
        "generate response schema invalid",
    )
    model = _bounded_string(
        value["model"], maximum=MAX_MODEL_NAME_CHARS, code="generate response schema invalid"
    )
    if model != expected_model or type(value["done"]) is not bool:
        raise _fail("generate response schema invalid")
    _validate_response_metadata(value, "generate response schema invalid")
    return _bounded_text(
        value["response"], maximum=MAX_TEXT_CHARS, code="generate response schema invalid"
    ), value["done"]


def _validate_response_metadata(value: Mapping[str, Any], code: str) -> None:
    for key in ("created_at", "done_reason"):
        if key in value:
            _bounded_string(value[key], maximum=MAX_MODEL_NAME_CHARS, code=code)
    for key in (
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    ):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1):
            raise _fail(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise _fail("redirect denied")


@dataclass(frozen=True)
class LocalModelConfig:
    """Explicit authority for one local Ollama model."""

    base_url: str
    model: str
    expected_digest: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url)
        _bounded_string(self.model, maximum=MAX_MODEL_NAME_CHARS, code="invalid model name")
        _validate_digest(self.expected_digest, "invalid expected model digest")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise _fail("invalid timeout")
        if not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise _fail("invalid timeout")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= MAX_RESPONSE_BYTES
        ):
            raise _fail("invalid response cap")


def _validate_base_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise _fail("base URL must be numeric IPv4 loopback HTTP")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        address = ipaddress.ip_address(hostname or "")
        port = parsed.port
    except (ValueError, TypeError):
        raise _fail("base URL must be numeric IPv4 loopback HTTP") from None
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not isinstance(address, ipaddress.IPv4Address)
        or not address.is_loopback
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise _fail("base URL must be numeric IPv4 loopback HTTP")
    return value.rstrip("/")


@dataclass(frozen=True)
class LocalModelReceipt:
    """Sanitized evidence; it deliberately has no prompt, output, or URL."""

    request_sha256: str
    response_sha256: str
    response_bytes: int
    response_items: int
    model_digest: str
    tags_pre_count: int
    tags_post_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "response_bytes": self.response_bytes,
            "response_items": self.response_items,
            "model_digest": self.model_digest,
            "tags_pre_count": self.tags_pre_count,
            "tags_post_count": self.tags_post_count,
        }


@dataclass(frozen=True)
class LocalModelResult:
    """Validated model response plus a receipt safe to persist or log."""

    content: str
    model: str
    done: bool
    payload: Mapping[str, Any]
    receipt: LocalModelReceipt


@dataclass(frozen=True)
class LocalJSONModelResult:
    """One schema-valid JSON document plus the payload-free model receipt."""

    document: Any
    model: str
    done: bool
    receipt: LocalModelReceipt


class LocalModelClient:
    """One-request client for a pinned local Ollama model."""

    def __init__(self, config: LocalModelConfig) -> None:
        self.config = config
        self._base_url = _validate_base_url(config.base_url)
        # An empty proxy map prevents ambient HTTP(S)_PROXY use.  Redirects are
        # rejected rather than followed, including redirects to loopback aliases.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def chat(self, messages: Sequence[Mapping[str, Any]]) -> LocalModelResult:
        request_messages = _validate_messages(messages)
        body = {"model": self.config.model, "messages": request_messages, "stream": False}
        return self._invoke("chat", body)

    def chat_json(
        self,
        messages: Sequence[Mapping[str, Any]],
        output_schema: Mapping[str, Any],
        *,
        seed: int = 17,
        max_tokens: int = 4096,
    ) -> LocalJSONModelResult:
        """Request one deterministic JSON document and validate it locally.

        The schema is sent to the already-pinned local peer as Ollama's
        structured-output ``format`` and then enforced again by the host.  No
        caller-controlled sampling options, tool calls, remote references, or
        thinking trace are admitted.
        """

        request_messages = _validate_messages(messages)
        if not isinstance(output_schema, Mapping):
            raise _fail("invalid output schema")
        schema = dict(output_schema)
        try:
            if len(_canonical(schema)) > 256 * 1024:
                raise _fail("invalid output schema")
            Draft202012Validator.check_schema(schema)
        except LocalModelBoundaryError:
            raise
        except (SchemaError, TypeError, ValueError, RecursionError):
            raise _fail("invalid output schema") from None
        if type(seed) is not int or not -(2**31) <= seed <= 2**31 - 1:
            raise _fail("invalid deterministic options")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 32_768:
            raise _fail("invalid deterministic options")
        body = {
            "model": self.config.model,
            "messages": request_messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0, "seed": seed, "num_predict": max_tokens},
        }
        result = self._invoke("chat", body)
        try:
            document = _parse_json(result.content.encode("utf-8"))
            errors = list(Draft202012Validator(schema).iter_errors(document))
        except LocalModelBoundaryError:
            raise _fail("model output is not schema-valid JSON") from None
        except (TypeError, ValueError, RecursionError):
            raise _fail("model output is not schema-valid JSON") from None
        if errors:
            raise _fail("model output is not schema-valid JSON")
        return LocalJSONModelResult(
            document=document,
            model=result.model,
            done=result.done,
            receipt=result.receipt,
        )

    def generate(self, prompt: str) -> LocalModelResult:
        prompt = _bounded_text(prompt, maximum=MAX_TEXT_CHARS, code="invalid generate request")
        body = {"model": self.config.model, "prompt": prompt, "stream": False}
        return self._invoke("generate", body)

    def _invoke(self, operation: str, body: dict[str, Any]) -> LocalModelResult:
        request_raw = _canonical(body)
        if len(request_raw) > MAX_REQUEST_BYTES:
            raise _fail("request exceeds byte cap")
        pre_models = self._tags()
        pre_digest = _find_model(pre_models, self.config.model)
        if pre_digest != self.config.expected_digest:
            raise _fail("expected model digest mismatch")

        operation_error: LocalModelBoundaryError | None = None
        response_raw = b""
        payload: Any = None
        try:
            response_raw = self._post(f"/api/{operation}", request_raw)
            payload = _parse_json(response_raw)
            if operation == "chat":
                content, done = _validate_chat_response(payload, self.config.model)
            else:
                content, done = _validate_generate_response(payload, self.config.model)
        except LocalModelBoundaryError as error:
            operation_error = error
            content = ""
            done = False

        try:
            post_models = self._tags()
            post_digest = _find_model(post_models, self.config.model)
        except LocalModelBoundaryError:
            raise _fail("post-inference model verification failed") from None
        if post_digest != self.config.expected_digest or post_digest != pre_digest:
            raise _fail("post-inference model digest mismatch")
        if operation_error is not None:
            raise operation_error

        assert isinstance(payload, dict)
        receipt = LocalModelReceipt(
            request_sha256=_sha256(request_raw),
            response_sha256=_sha256(response_raw),
            response_bytes=len(response_raw),
            response_items=1,
            model_digest=post_digest,
            tags_pre_count=len(pre_models),
            tags_post_count=len(post_models),
        )
        return LocalModelResult(
            content=content,
            model=self.config.model,
            done=done,
            payload=payload,
            receipt=receipt,
        )

    def _tags(self) -> list[Mapping[str, Any]]:
        raw = self._request("GET", "/api/tags", None)
        return _validate_tags(_parse_json(raw))

    def _post(self, path: str, body: bytes) -> bytes:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: bytes | None) -> bytes:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                if response.status < 200 or response.status >= 300:
                    raise _fail("HTTP status rejected")
                if response.headers.get_content_type() != "application/json":
                    raise _fail("content type rejected")
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > self.config.max_response_bytes:
                            raise _fail("response exceeds byte cap")
                    except (TypeError, ValueError):
                        raise _fail("invalid response length") from None
                raw = response.read(self.config.max_response_bytes + 1)
                if len(raw) > self.config.max_response_bytes:
                    raise _fail("response exceeds byte cap")
                return raw
        except LocalModelBoundaryError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError):
            raise _fail("local model transport failure") from None


def _validate_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if isinstance(messages, (str, bytes, bytearray)) or not isinstance(messages, Sequence):
        raise _fail("invalid chat request")
    if not messages or len(messages) > MAX_MESSAGES:
        raise _fail("invalid chat request")
    result: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise _fail("invalid chat request")
        _exact_keys(message, _MESSAGE_KEYS, frozenset({"role", "content"}), "invalid chat request")
        role = _bounded_string(message["role"], maximum=32, code="invalid chat request")
        if role not in _ROLES:
            raise _fail("invalid chat request")
        content = _bounded_text(
            message["content"], maximum=MAX_TEXT_CHARS, code="invalid chat request"
        )
        result.append({"role": role, "content": content})
    return result


__all__ = [
    "LocalModelBoundaryError",
    "LocalModelClient",
    "LocalModelConfig",
    "LocalModelReceipt",
    "LocalModelResult",
    "LocalJSONModelResult",
]
