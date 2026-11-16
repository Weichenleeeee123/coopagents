import json
import math
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent-integration"))

from dsh_sandbox.api_proxy import (
    ProxyConfig,
    create_handler,
    parse_usage,
    validate_endpoint,
)


class ProxyContractTests(unittest.TestCase):
    def test_endpoint_is_complete_tls_chat_completions_url(self):
        endpoint = "https://provider.example/v1/chat/completions?tenant=x"
        self.assertEqual(validate_endpoint(endpoint), endpoint)
        for endpoint in (
            "http://provider.example/v1/chat/completions",
            "https://provider.example/v1",
            "https://user:pass@provider.example/v1/chat/completions",
            "https://provider.example/v1/chat/completions/extra",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_usage_is_null_when_missing_or_invalid(self):
        self.assertIsNone(parse_usage({}))
        self.assertIsNone(parse_usage({"usage": {"prompt_tokens": "bad"}}))
        self.assertEqual(
            parse_usage({"usage": {"prompt_tokens": 12, "completion_tokens": 5}}),
            {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        )

    def test_cost_limiter_requires_real_finite_positive_rates_and_limits(self):
        from dsh_sandbox.api_proxy import ProxyConfig

        base = dict(endpoint="https://provider.example/v1/chat/completions", model="fixed",
                    provider_key="secret", client_tokens={"vm": "run"})
        for overrides in (
            {},
            {"input_cost_per_million": True},
            {"output_cost_per_million": math.nan},
            {"max_cost_per_run": math.inf},
            {"max_tokens_per_run": True},
            {"max_request_bytes": 1.5},
            {"credential_ttl_seconds": 0},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                ProxyConfig(**base, **overrides)


class ProxyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.config = ProxyConfig(
            endpoint="https://provider.example/v1/chat/completions?tenant=x",
            model="deepseekv41flash-auto-b",
            provider_key="provider-secret",
            client_tokens={"vm-token": "run-1"},
            max_request_bytes=1024,
            max_response_bytes=2048,
            max_requests_per_run=1,
            max_tokens_per_run=100,
            max_cost_per_run=1.0,
            input_cost_per_million=1.0,
            output_cost_per_million=1.0,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(self.config))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, value, token="vm-token"):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        request = Request(self.url, data=data, headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        })
        return urlopen(request, timeout=2)

    @patch("dsh_sandbox.api_proxy.HTTPSConnection")
    def test_forwards_exact_url_fixed_model_and_provider_auth_only_upstream(self, connection):
        upstream = connection.return_value
        response = upstream.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "application/json"
        response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }).encode()
        upstream_response = self.post({"model": "attacker-model", "messages": [], "max_tokens": 4})
        self.assertEqual(upstream_response.status, 200)
        self.assertEqual(upstream.request.call_args.args[1], "/v1/chat/completions?tenant=x")
        body = json.loads(upstream.request.call_args.kwargs["body"])
        self.assertEqual(body["model"], self.config.model)
        headers = upstream.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer provider-secret")
        self.assertNotIn("Authorization", upstream_response.headers)
        self.assertEqual(json.loads(upstream_response.read())["usage"]["total_tokens"], 5)

    def test_rejects_bad_auth_oversized_and_over_budget_requests(self):
        with self.assertRaises(HTTPError) as bad_auth:
            self.post({"model": self.config.model, "messages": [], "max_tokens": 1}, "wrong")
        self.assertEqual(bad_auth.exception.code, 401)

        with self.assertRaises(HTTPError) as oversized:
            self.post(b"x" * 1025)
        self.assertEqual(oversized.exception.code, 413)

    @patch("dsh_sandbox.api_proxy.HTTPSConnection")
    def test_provider_errors_are_redacted_and_redirects_not_followed(self, connection):
        upstream = connection.return_value
        response = upstream.getresponse.return_value
        response.status = 302
        response.getheader.return_value = "https://evil.example/" 
        response.read.return_value = b"provider-secret prompt-private"
        with self.assertRaises(HTTPError) as error:
            self.post({"model": self.config.model, "messages": [], "max_tokens": 1})
        self.assertEqual(error.exception.code, 502)
        result = error.exception
        self.assertNotEqual(result.status, 302)
        body = result.read().decode()
        self.assertNotIn("provider-secret", body)
        self.assertNotIn("prompt-private", body)
        self.assertNotIn("evil.example", body)

    @patch("dsh_sandbox.api_proxy.HTTPSConnection")
    def test_budget_stops_additional_request_and_streaming_body_is_preserved(self, connection):
        upstream = connection.return_value
        response = upstream.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "text/event-stream"
        stream_body = b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
        response.read.return_value = stream_body
        payload = {"model": self.config.model, "messages": [], "max_tokens": 1, "stream": True}
        result = self.post(payload)
        self.assertEqual(result.headers["Content-Type"], "text/event-stream")
        self.assertEqual(result.read(), stream_body)
        with self.assertRaises(HTTPError) as limited:
            self.post(payload)
        self.assertEqual(limited.exception.code, 429)

    @patch("dsh_sandbox.api_proxy.HTTPSConnection")
    def test_missing_usage_is_reported_as_null_without_exposing_provider_body(self, connection):
        observed = []
        self.config.usage_observer = lambda run_id, usage: observed.append((run_id, usage))
        upstream = connection.return_value
        response = upstream.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "application/json"
        response.read.return_value = b'{"choices":[],"diagnostic":"prompt-private"}'
        result = self.post({"model": self.config.model, "messages": [], "max_tokens": 1})
        self.assertNotIn("prompt-private", str(result.headers))
        self.assertEqual(observed, [("run-1", None)])

    def test_expired_short_lived_client_credential_is_rejected(self):
        self.config._token_expiry["vm-token"] = 0
        with self.assertRaises(HTTPError) as expired:
            self.post({"model": self.config.model, "messages": [], "max_tokens": 1})
        self.assertEqual(expired.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
