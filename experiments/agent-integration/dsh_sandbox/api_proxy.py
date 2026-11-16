"""Small, bounded OpenAI-compatible Chat Completions reverse proxy."""

from __future__ import annotations

import http.client
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from hmac import compare_digest
from typing import Callable
from typing import Any
from urllib.parse import urlsplit

HTTPSConnection = http.client.HTTPSConnection


def validate_endpoint(endpoint: str) -> str:
    """Accept only a complete HTTPS Chat Completions URL."""
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.path.rstrip("/") != "/v1/chat/completions"
            and not parsed.path.rstrip("/").endswith("/chat/completions")):
        raise ValueError("endpoint must be a complete TLS Chat Completions URL")
    if parsed.path.endswith("/"):
        raise ValueError("endpoint path must not end with a slash")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint has an invalid port") from exc
    return endpoint


def parse_usage(payload: Any) -> dict[str, int] | None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if (isinstance(prompt, bool) or not isinstance(prompt, int) or prompt < 0
            or isinstance(completion, bool) or not isinstance(completion, int) or completion < 0):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        total = prompt + completion
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


@dataclass
class ProxyConfig:
    endpoint: str
    model: str
    provider_key: str
    client_tokens: dict[str, str]
    max_request_bytes: int = 1_048_576
    max_response_bytes: int = 4_194_304
    max_requests_per_run: int = 100
    max_tokens_per_run: int = 100_000
    max_cost_per_run: float = 5.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    timeout_seconds: float = 60.0
    credential_ttl_seconds: float = 3600.0
    usage_observer: Callable[[str, dict[str, int] | None], None] | None = None
    _state: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _token_expiry: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        self.endpoint = validate_endpoint(self.endpoint)
        if not self.model or not self.provider_key or not self.client_tokens:
            raise ValueError("model and runtime credentials are required")
        if (not isinstance(self.client_tokens, dict)
                or any(not isinstance(token, str) or not token or not isinstance(run, str) or not run
                       for token, run in self.client_tokens.items())):
            raise ValueError("client credentials must map nonempty tokens to run ids")
        integer_limits = (self.max_request_bytes, self.max_response_bytes,
                          self.max_requests_per_run, self.max_tokens_per_run)
        numeric_limits = (self.max_cost_per_run, self.input_cost_per_million,
                          self.output_cost_per_million, self.timeout_seconds,
                          self.credential_ttl_seconds)
        if (any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in integer_limits)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value < 0 for value in numeric_limits)
                or self.max_cost_per_run <= 0 or self.input_cost_per_million <= 0
                or self.output_cost_per_million <= 0 or self.timeout_seconds <= 0
                or self.credential_ttl_seconds <= 0):
            raise ValueError("proxy limits must be positive")
        expiry = time.monotonic() + self.credential_ttl_seconds
        self._token_expiry = {token: expiry for token in self.client_tokens}

    @classmethod
    def from_env(cls, *, client_tokens: dict[str, str], **kwargs):
        """Read provider configuration at process startup without persisting it."""
        return cls(
            endpoint=os.environ["LLM_BASE_URL"],
            model=os.environ["LLM_MODEL"],
            provider_key=os.environ["LLM_API_KEY"],
            client_tokens=client_tokens,
            **kwargs,
        )

    def reserve(self, run_id: str, input_bytes: int, requested_tokens: int) -> bool:
        # Byte count is a conservative upper bound on input token count.
        token_reserve = input_bytes + requested_tokens
        cost_reserve = (input_bytes * self.input_cost_per_million
                        + requested_tokens * self.output_cost_per_million) / 1_000_000
        with self._lock:
            state = self._state.setdefault(run_id, {"requests": 0, "tokens": 0, "cost": 0.0})
            if (state["requests"] + 1 > self.max_requests_per_run
                    or state["tokens"] + token_reserve > self.max_tokens_per_run
                    or state["cost"] + cost_reserve > self.max_cost_per_run):
                return False
            state["requests"] += 1
            state["tokens"] += token_reserve
            state["cost"] += cost_reserve
            return True


def _safe_error(handler: BaseHTTPRequestHandler, status: int, code: str):
    body = json.dumps({"error": {"message": code, "type": "proxy_error"}}).encode()
    handler.close_connection = True
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(body)


def create_handler(config: ProxyConfig):
    class ChatCompletionsHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            # BaseHTTPRequestHandler's default log includes client request targets.
            return

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return _safe_error(self, 404, "not_found")

            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return _safe_error(self, 401, "unauthorized")
            presented = auth[7:]
            run_id = next((candidate_run for token, candidate_run in config.client_tokens.items()
                           if compare_digest(token, presented)), None)
            if run_id is not None and time.monotonic() >= config._token_expiry[presented]:
                run_id = None
            if run_id is None:
                return _safe_error(self, 401, "unauthorized")

            length_header = self.headers.get("Content-Length")
            if not length_header or not length_header.isdigit():
                return _safe_error(self, 411, "content_length_required")
            length = int(length_header)
            if length > config.max_request_bytes:
                return _safe_error(self, 413, "request_too_large")
            try:
                request = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return _safe_error(self, 400, "invalid_json")
            if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
                return _safe_error(self, 400, "invalid_chat_request")
            requested_tokens = request.get("max_tokens", request.get("max_completion_tokens"))
            if (isinstance(requested_tokens, bool) or not isinstance(requested_tokens, int)
                    or requested_tokens < 1):
                return _safe_error(self, 400, "max_tokens_required")
            if not config.reserve(run_id, length, requested_tokens):
                return _safe_error(self, 429, "run_budget_exhausted")

            request["model"] = config.model
            body = json.dumps(request, separators=(",", ":")).encode()
            endpoint = urlsplit(config.endpoint)
            path = endpoint.path + (("?" + endpoint.query) if endpoint.query else "")
            connection = None
            try:
                connection = HTTPSConnection(
                    endpoint.hostname, endpoint.port or 443, timeout=config.timeout_seconds
                )
                connection.request("POST", path, body=body, headers={
                    "Authorization": "Bearer " + config.provider_key,
                    "Content-Type": "application/json",
                    "Accept": self.headers.get("Accept", "application/json"),
                })
                upstream = connection.getresponse()
                # Redirects are never followed. Do not expose provider error bodies or locations.
                if upstream.status < 200 or upstream.status >= 300:
                    upstream.read(config.max_response_bytes + 1)
                    return _safe_error(self, 502, "upstream_error")
                response_body = upstream.read(config.max_response_bytes + 1)
                if len(response_body) > config.max_response_bytes:
                    return _safe_error(self, 502, "upstream_response_too_large")
                content_type = upstream.getheader("Content-Type", "application/json")
                usage = None
                if "text/event-stream" not in content_type.lower():
                    try:
                        usage = parse_usage(json.loads(response_body))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                if config.usage_observer is not None:
                    try:
                        config.usage_observer(run_id, usage)
                    except Exception:
                        pass
                self.send_response(upstream.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                self.wfile.write(response_body)
            except (OSError, http.client.HTTPException, TimeoutError):
                _safe_error(self, 502, "upstream_unavailable")
            finally:
                if connection is not None:
                    connection.close()

        def do_GET(self):
            _safe_error(self, 405, "method_not_allowed")

    return ChatCompletionsHandler
