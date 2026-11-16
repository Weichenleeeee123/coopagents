import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent-integration"))

from dsh_sandbox.provider_probe import (
    classify_response,
    classify_sse,
    main,
    probe_request,
)


MODEL = "deepseekv41flash-auto-b"


class ResponseClassificationTests(unittest.TestCase):
    def test_classifies_text_tool_usage_and_model_without_retaining_response(self):
        payload = {
            "model": MODEL,
            "choices": [{"message": {
                "content": "probe complete",
                "tool_calls": [{"id": "call_123", "type": "function", "function": {
                    "name": "probe_echo", "arguments": "{\"ok\":true}"
                }}],
            }}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        }
        result = classify_response(payload, MODEL)
        self.assertEqual(result, {
            "classification": "compatible", "model_matches": True, "text_observed": True,
            "tool_compatible": True, "usage": {"prompt_tokens": 8, "completion_tokens": 4,
                                                  "total_tokens": 12},
        })
        self.assertNotIn("probe complete", str(result))

    def test_missing_or_malformed_fields_are_reported_as_incompatible_and_usage_null(self):
        result = classify_response({"model": "other", "choices": []}, MODEL)
        self.assertEqual(result["classification"], "incompatible")
        self.assertIsNone(result["usage"])
        self.assertFalse(result["tool_compatible"])

    def test_forced_tool_call_is_compatible_when_content_is_null(self):
        payload = {"model": MODEL, "choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "call_456", "type": "function", "function": {
                "name": "probe_echo", "arguments": "{\"ok\":true}"
            }}],
        }}]}
        result = classify_response(payload, MODEL)
        self.assertEqual(result["classification"], "compatible")
        self.assertTrue(result["tool_compatible"])
        self.assertFalse(result["text_observed"])
        self.assertIsNone(result["usage"])

    def test_rejects_false_extra_or_malformed_tool_call_schema_without_raising(self):
        malformed = [
            {"type": "function", "function": {"name": "probe_echo", "arguments": '{"ok":true}'}},
            {"id": "call_1", "type": "function", "function": {
                "name": "probe_echo", "arguments": '{"ok":false}'}},
            {"id": "call_1", "type": "function", "function": {
                "name": "probe_echo", "arguments": '{"ok":true,"extra":1}'}},
        ]
        for call in malformed:
            payload = {"model": MODEL, "choices": [{"message": {"tool_calls": [call]}}]}
            with self.subTest(call=call):
                self.assertFalse(classify_response(payload, MODEL)["tool_compatible"])
        for choices in ([None], ["bad"], {}):
            with self.subTest(choices=choices):
                self.assertEqual(classify_response({"model": MODEL, "choices": choices}, MODEL)["classification"],
                                 "incompatible")

    def test_sse_requires_done_and_classifies_final_response(self):
        events = [
            'data: {"model":"%s","choices":[{"delta":{"content":"ok"}}]}' % MODEL,
            'data: {"model":"%s","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"probe_echo","arguments":"{\\"ok\\":true}"}}]}}]}' % MODEL,
            'data: {"model":"%s","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_sse_1","type":"function"}]}}]}' % MODEL,
            'data: {"model":"%s","choices":[{"delta":{},"finish_reason":"tool_calls"}]}' % MODEL,
            'data: {"model":"%s","choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}' % MODEL,
            "data: [DONE]",
        ]
        result = classify_sse((line.encode() + b"\n\n" for line in events), MODEL)
        self.assertTrue(result["stream_done"])
        self.assertEqual(result["classification"], "compatible")
        self.assertEqual(result["usage"]["total_tokens"], 3)

    def test_stream_requires_consistent_models_and_tool_calls_finish_reason(self):
        good_tool_delta = {"index": 0, "id": "call_1", "type": "function",
                           "function": {"name": "probe_echo", "arguments": '{"ok":true}'}}
        events = [
            {"model": MODEL, "choices": [{"delta": {"tool_calls": [good_tool_delta]},
                                           "finish_reason": "tool_calls"}]},
            {"model": "wrong-model", "choices": []},
        ]
        chunks = [b"data: " + json.dumps(event).encode() + b"\n\n" for event in events]
        result = classify_sse(chunks + [b"data: [DONE]\n\n"], MODEL)
        self.assertFalse(result["model_matches"])
        self.assertEqual(result["classification"], "incompatible")
        unfinished = [{"model": MODEL, "choices": [{"delta": {"tool_calls": [good_tool_delta]},
                                                       "finish_reason": "stop"}]}]
        result = classify_sse([b"data: " + json.dumps(unfinished[0]).encode() + b"\n\n",
                               b"data: [DONE]\n\n"], MODEL)
        self.assertEqual(result["classification"], "incompatible")
        self.assertFalse(result["tool_compatible"])

    def test_sse_without_done_is_incompatible(self):
        result = classify_sse([b'data: {"model":"%s","choices":[]}\n\n' % MODEL.encode()], MODEL)
        self.assertFalse(result["stream_done"])
        self.assertEqual(result["classification"], "incompatible")


class ProbeRequestTests(unittest.TestCase):
    def test_builds_synthetic_fixed_token_tool_request_at_complete_endpoint(self):
        request = probe_request("https://provider.example/v1/chat/completions", MODEL)
        self.assertEqual(request.full_url, "https://provider.example/v1/chat/completions")
        self.assertEqual(request.method, "POST")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["max_tokens"], 32)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["tool_choice"]["function"]["name"], "probe_echo")
        self.assertNotIn("Authorization", request.headers)

    def test_preserves_configured_query_and_port_and_rejects_incomplete_or_plain_http_urls(self):
        endpoint = "https://provider.example:9443/custom/chat/completions?tenant=synthetic"
        self.assertEqual(probe_request(endpoint, MODEL).full_url, endpoint)
        for endpoint in ("http://provider.example/v1/chat/completions", "https://provider.example/v1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                probe_request(endpoint, MODEL)

    def test_redirects_are_not_followed(self):
        from dsh_sandbox.provider_probe import NoRedirectHandler

        handler = NoRedirectHandler()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example"))


class CliSafetyTests(unittest.TestCase):
    def test_live_probe_requires_explicit_enablement_and_rotated_key_attestation(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1/chat/completions",
               "LLM_MODEL": MODEL, "LLM_API_KEY": "sentinel-secret"}
        with patch.dict(os.environ, env, clear=True), patch("sys.stdout.write") as output:
            self.assertEqual(main([]), 2)
            self.assertNotIn("sentinel-secret", str(output.call_args_list))
        with patch.dict(os.environ, env, clear=True), patch("dsh_sandbox.provider_probe.build_opener") as opener:
            self.assertEqual(main(["--live"]), 2)
            opener.assert_not_called()

    def test_key_environment_is_cleared_even_when_live_probe_fails(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1/chat/completions",
               "LLM_MODEL": MODEL, "LLM_API_KEY": "sentinel-secret"}
        with patch.dict(os.environ, env, clear=True), patch("dsh_sandbox.provider_probe.build_opener",
                                                           side_effect=OSError("sentinel-secret")):
            self.assertEqual(main(["--live", "--key-rotated"]), 1)
            self.assertNotIn("LLM_API_KEY", os.environ)

    def test_sandbox_modules_import_in_package_and_module_execution_contexts(self):
        module_dir = str(Path(__file__).resolve().parents[1] / "experiments" / "agent-integration")
        env = os.environ.copy()
        env["PYTHONPATH"] = module_dir + os.pathsep + env.get("PYTHONPATH", "")
        package_import = subprocess.run(
            [sys.executable, "-c", "import dsh_sandbox.fixture_repo, dsh_sandbox.bridge_client"],
            capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(package_import.returncode, 0, package_import.stderr)
        module_run = subprocess.run(
            [sys.executable, "-m", "dsh_sandbox.bridge_client", "--help"],
            capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(module_run.returncode, 0, module_run.stderr)


if __name__ == "__main__":
    unittest.main()
