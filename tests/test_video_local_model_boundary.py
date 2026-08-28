from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from metis_model1.video_local_model_boundary import (
    LocalModelBoundaryError,
    LocalModelClient,
    LocalModelConfig,
)

MODEL = "qwen3.8:27b-mlx"
DIGEST = "sha256:" + "a" * 64
BAD_DIGEST = "sha256:" + "b" * 64
SENTINEL = "PRIVATE-PROMPT-AND-OUTPUT-MUST-NOT-LEAK"


class _State:
    def __init__(self) -> None:
        self.tags = [
            {"name": MODEL, "digest": DIGEST},
        ]
        self.post_tags: list[list[dict[str, Any]]] = []
        self.requests: list[tuple[str, str, bytes]] = []
        self.chat_response: bytes = json.dumps(
            {"model": MODEL, "message": {"role": "assistant", "content": "answer"}, "done": True}
        ).encode()
        self.generate_response: bytes = json.dumps(
            {"model": MODEL, "response": "generated", "done": True}
        ).encode()
        self.redirect_tags = False
        self.oversize_tags = False
        self.post_count = 0


def _handler_for(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            state.requests.append(("GET", self.path, b""))
            if self.path == "/api/tags" and state.redirect_tags:
                self.send_response(302)
                self.send_header("Location", "/api/tags-redirect-target")
                self.end_headers()
                return
            if self.path != "/api/tags":
                self._send(404, b"{}")
                return
            state.post_count += 1
            if state.oversize_tags:
                self._send(200, b"{" + b"x" * 1024 + b"}")
                return
            tags = state.tags
            if state.post_tags:
                index = min(state.post_count - 1, len(state.post_tags) - 1)
                tags = state.post_tags[index]
            self._send(200, json.dumps({"models": tags}).encode())

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            state.requests.append(("POST", self.path, body))
            if self.path == "/api/chat":
                self._send(200, state.chat_response)
            elif self.path == "/api/generate":
                self._send(200, state.generate_response)
            else:
                self._send(404, b"{}")

    return Handler


def _server(state: _State) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _client(base_url: str, *, digest: str = DIGEST, **kwargs: Any) -> LocalModelClient:
    return LocalModelClient(
        LocalModelConfig(base_url=base_url, model=MODEL, expected_digest=digest, **kwargs)
    )


@pytest.fixture
def running_server() -> Any:
    state = _State()
    server, thread, url = _server(state)
    try:
        yield state, url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_chat_checks_tags_before_and_after_and_returns_sanitized_receipt(
    running_server: Any,
) -> None:
    state, url = running_server
    result = _client(url).chat([{"role": "user", "content": SENTINEL}])

    assert result.content == "answer"
    assert result.done is True
    assert [path for method, path, _body in state.requests if method == "GET"] == [
        "/api/tags",
        "/api/tags",
    ]
    post = next(
        body for method, path, body in state.requests if method == "POST" and path == "/api/chat"
    )
    request = json.loads(post)
    assert request == {
        "model": MODEL,
        "messages": [{"role": "user", "content": SENTINEL}],
        "stream": False,
    }
    receipt = result.receipt.as_dict()
    assert set(receipt) == {
        "schema_version",
        "request_sha256",
        "response_sha256",
        "response_bytes",
        "response_items",
        "model_digest",
        "tags_pre_count",
        "tags_post_count",
    }
    assert SENTINEL not in json.dumps(receipt)
    assert "answer" not in json.dumps(receipt)
    assert receipt["model_digest"] == DIGEST
    assert receipt["tags_pre_count"] == receipt["tags_post_count"] == 1


def test_generate_is_non_streaming_and_schema_bound(running_server: Any) -> None:
    state, url = running_server
    result = _client(url).generate("prompt")

    assert result.content == "generated"
    post = next(
        body
        for method, path, body in state.requests
        if method == "POST" and path == "/api/generate"
    )
    assert json.loads(post) == {"model": MODEL, "prompt": "prompt", "stream": False}


def test_structured_chat_sends_closed_options_and_validates_json(running_server: Any) -> None:
    state, url = running_server
    state.tags[0]["capabilities"] = ["completion"]
    state.chat_response = json.dumps(
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": '{"answer":"ok"}'},
            "done": True,
        }
    ).encode()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"const": "ok"}},
    }
    result = _client(url).chat_json(
        [{"role": "user", "content": "synthetic"}], schema, seed=19, max_tokens=64
    )
    assert result.document == {"answer": "ok"}
    body = json.loads(next(body for method, path, body in state.requests if path == "/api/chat"))
    assert body["think"] is False
    assert body["format"] == schema
    assert body["options"] == {"temperature": 0, "seed": 19, "num_predict": 64}


def test_structured_chat_rejects_output_that_misses_schema(running_server: Any) -> None:
    state, url = running_server
    state.chat_response = json.dumps(
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": '{"wrong":true}'},
            "done": True,
        }
    ).encode()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    with pytest.raises(LocalModelBoundaryError, match="schema-valid JSON"):
        _client(url).chat_json([{"role": "user", "content": "synthetic"}], schema)


def test_ollama_native_digest_without_prefix_is_normalized(running_server: Any) -> None:
    state, url = running_server
    state.tags[0]["digest"] = DIGEST.removeprefix("sha256:")
    result = _client(url).generate("synthetic")
    assert result.receipt.model_digest == DIGEST


def test_multiline_prompt_and_structured_output_are_allowed(running_server: Any) -> None:
    state, url = running_server
    state.chat_response = json.dumps(
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": '{\n  "ok": true\n}'},
            "done": True,
        }
    ).encode()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"const": True}},
    }
    result = _client(url).chat_json([{"role": "user", "content": "line one\nline two"}], schema)
    assert result.document == {"ok": True}


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1.evil:11434",
        "https://127.0.0.1:11434",
        "http://[::1]:11434",
        "http://0.0.0.0:11434",
    ],
)
def test_only_numeric_ipv4_loopback_http_is_accepted(url: str) -> None:
    with pytest.raises(LocalModelBoundaryError, match="numeric IPv4 loopback HTTP"):
        LocalModelConfig(base_url=url, model=MODEL, expected_digest=DIGEST)


def test_redirect_is_rejected_without_following_it(running_server: Any) -> None:
    state, url = running_server
    state.redirect_tags = True

    with pytest.raises(LocalModelBoundaryError, match="redirect denied"):
        _client(url).chat([{"role": "user", "content": "prompt"}])
    assert ("GET", "/api/tags-redirect-target", b"") not in state.requests


def test_ambient_proxy_is_not_used(monkeypatch: pytest.MonkeyPatch, running_server: Any) -> None:
    _state, url = running_server
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    assert _client(url).generate("prompt").content == "generated"


def test_wrong_preflight_digest_blocks_post(running_server: Any) -> None:
    state, url = running_server
    state.tags = [{"name": MODEL, "digest": BAD_DIGEST}]

    with pytest.raises(LocalModelBoundaryError, match="expected model digest mismatch"):
        _client(url).chat([{"role": "user", "content": "prompt"}])
    assert not any(method == "POST" for method, _path, _body in state.requests)


def test_digest_change_after_inference_fails_closed(running_server: Any) -> None:
    state, url = running_server
    state.post_tags = [
        [{"name": MODEL, "digest": DIGEST}],
        [{"name": MODEL, "digest": BAD_DIGEST}],
    ]

    with pytest.raises(LocalModelBoundaryError, match="post-inference model digest mismatch"):
        _client(url).chat([{"role": "user", "content": "prompt"}])


def test_oversize_tags_response_is_rejected_without_payload_in_error(running_server: Any) -> None:
    state, url = running_server
    state.oversize_tags = True

    with pytest.raises(LocalModelBoundaryError) as caught:
        _client(url, max_response_bytes=128).chat([{"role": "user", "content": SENTINEL}])
    assert SENTINEL not in str(caught.value)
    assert "x" not in str(caught.value)


def test_streamed_or_extra_field_output_is_rejected_and_post_tags_are_still_checked(
    running_server: Any,
) -> None:
    state, url = running_server
    state.chat_response = (
        b'{"model":"'
        + MODEL.encode()
        + b'","message":{"role":"assistant","content":"'
        + SENTINEL.encode()
        + b'"},"done":true,"unexpected":"x"}'
    )

    with pytest.raises(LocalModelBoundaryError, match="chat response schema invalid") as caught:
        _client(url).chat([{"role": "user", "content": "prompt"}])
    assert SENTINEL not in str(caught.value)
    assert [path for method, path, _body in state.requests if method == "GET"] == [
        "/api/tags",
        "/api/tags",
    ]


def test_invalid_request_and_expected_digest_are_rejected_before_network(
    running_server: Any,
) -> None:
    state, url = running_server
    with pytest.raises(LocalModelBoundaryError, match="invalid chat request"):
        _client(url).chat([])
    with pytest.raises(LocalModelBoundaryError, match="invalid expected model digest"):
        LocalModelConfig(base_url=url, model=MODEL, expected_digest="not-a-digest")
    assert state.requests == []
