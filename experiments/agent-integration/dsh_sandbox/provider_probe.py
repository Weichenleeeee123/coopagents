"""Opt-in, redacted OpenAI-compatible Chat Completions compatibility probe."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import (HTTPRedirectHandler, Request, build_opener)

from dsh_sandbox.api_proxy import parse_usage, validate_endpoint

MAX_TOKENS = 32
MAX_RESPONSE_BYTES = 1_048_576
TIMEOUT_SECONDS = 30
TOOL_NAME = "probe_echo"


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_request(endpoint: str, model: str) -> Request:
    endpoint = validate_endpoint(endpoint)
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": "Call probe_echo with {\\\"ok\\\":true}, then reply: probe complete.",
        }],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
        "tools": [{
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": "Return the supplied synthetic probe value.",
                "parameters": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            },
        }],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }
    return Request(endpoint, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
    })


def _tool_is_valid(message: dict[str, Any]) -> bool:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return False
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
            continue
        try:
            arguments = json.loads(function.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(arguments, dict) and isinstance(arguments.get("ok"), bool):
            return True
    return False


def classify_response(payload: Any, expected_model: str) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices else None
    if not isinstance(message, dict):
        message = {}
    model_matches = isinstance(payload, dict) and payload.get("model") == expected_model
    has_text = isinstance(message.get("content"), str) and bool(message["content"].strip())
    tool_call = _tool_is_valid(message)
    compatible = bool(model_matches and has_text and tool_call)
    return {
        "classification": "compatible" if compatible else "incompatible",
        "model_matches": bool(model_matches),
        "text": bool(has_text),
        "tool_call": tool_call,
        "usage": parse_usage(payload),
    }


def _classify_stream_events(events: Iterable[dict[str, Any]], expected_model: str,
                            stream_done: bool) -> dict[str, Any]:
    model_matches = False
    text = False
    usage = None
    tool_names: dict[int, str] = {}
    tool_args: dict[int, str] = {}
    for event in events:
        if event.get("model") is not None:
            model_matches = event["model"] == expected_model
        usage = parse_usage(event) or usage
        choices = event.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            text = text or (isinstance(content, str) and bool(content.strip()))
            calls = delta.get("tool_calls", [])
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    index = call.get("index", 0)
                    if isinstance(index, bool) or not isinstance(index, int):
                        continue
                    function = call.get("function", {})
                    if not isinstance(function, dict):
                        continue
                    if isinstance(function.get("name"), str):
                        tool_names[index] = tool_names.get(index, "") + function["name"]
                    if isinstance(function.get("arguments"), str):
                        tool_args[index] = tool_args.get(index, "") + function["arguments"]
    tool_call = any(
        name == TOOL_NAME and _tool_is_valid({"tool_calls": [{"function": {
            "name": name, "arguments": tool_args.get(index, "")
        }}]})
        for index, name in tool_names.items()
    )
    compatible = bool(stream_done and model_matches and text and tool_call)
    return {
        "classification": "compatible" if compatible else "incompatible",
        "model_matches": model_matches,
        "text": text,
        "tool_call": tool_call,
        "stream_done": stream_done,
        "usage": usage,
    }


def classify_sse(chunks: Iterable[bytes], expected_model: str) -> dict[str, Any]:
    buffer = b""
    data_lines: list[bytes] = []
    events: list[dict[str, Any]] = []
    stream_done = False

    def consume_event(lines: list[bytes]) -> bool:
        nonlocal stream_done
        if not lines:
            return False
        raw = b"\n".join(lines)
        if raw == b"[DONE]":
            stream_done = True
            return True
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if isinstance(event, dict):
            events.append(event)
        return False

    for chunk in chunks:
        if not isinstance(chunk, bytes):
            continue
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line:
                if consume_event(data_lines):
                    return _classify_stream_events(events, expected_model, True)
                data_lines = []
            elif line.startswith(b"data:"):
                data_lines.append(line[5:].lstrip())
    if buffer:
        if buffer.startswith(b"data:"):
            data_lines.append(buffer[5:].lstrip())
    if data_lines:
        consume_event(data_lines)
    return _classify_stream_events(events, expected_model, stream_done)


def run_probe(endpoint: str, model: str, api_key: str) -> dict[str, Any]:
    request = probe_request(endpoint, model)
    request.add_header("Authorization", "Bearer " + api_key)
    opener = build_opener(NoRedirectHandler())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        content_type = response.headers.get("Content-Type", "")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            return {"classification": "incompatible", "reason": "response_too_large"}
        if "text/event-stream" in content_type.lower():
            return classify_sse([body], model)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"classification": "incompatible", "reason": "invalid_response"}
        return classify_response(payload, model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in Chat Completions compatibility probe")
    parser.add_argument("--live", action="store_true", help="allow one live provider request")
    parser.add_argument("--key-rotated", action="store_true",
                        help="attest that the prior exposed key was rotated")
    args = parser.parse_args(argv)
    try:
        if not args.live or not args.key_rotated:
            print(json.dumps({"classification": "not_run", "reason": "explicit_opt_in_required"}))
            return 2
        endpoint = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        api_key = os.environ.get("LLM_API_KEY", "")
        if not endpoint or not model or not api_key:
            print(json.dumps({"classification": "not_run", "reason": "required_environment_missing"}))
            return 2
        result = run_probe(endpoint, model, api_key)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("classification") == "compatible" else 1
    except (ValueError, HTTPError, URLError, OSError, TimeoutError):
        print(json.dumps({"classification": "incompatible", "reason": "request_failed"}))
        return 1
    finally:
        os.environ.pop("LLM_API_KEY", None)


if __name__ == "__main__":
    raise SystemExit(main())
