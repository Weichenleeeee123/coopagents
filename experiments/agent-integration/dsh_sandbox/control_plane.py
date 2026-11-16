"""Local TLS control-plane entry point for the bounded model proxy.

The private Git-over-SSH service is an external deployment dependency. This
module validates its private endpoint and can perform an explicit TCP probe;
it does not implement or impersonate a Git service.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dsh_sandbox.api_proxy import ProxyConfig, create_handler

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_CREDENTIAL_FILE_BYTES = 65536


def validate_bind_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("bind address must be an explicit private IP") from exc
    allowed = ((address.version == 4 and any(address in network for network in (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"))))
        or (address.version == 6 and address in ipaddress.ip_network("fc00::/7")))
    if (not allowed or address.is_loopback or address.is_unspecified
            or address.is_multicast or address.is_reserved):
        raise ValueError("bind address must be an explicit private unicast IP")
    return str(address)


def validate_git_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "ssh" or not parsed.hostname or parsed.password or parsed.query
            or parsed.fragment or not parsed.path.startswith("/") or "@" not in parsed.netloc):
        raise ValueError("Git dependency must be a private SSH URL")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not host.endswith(".internal"):
            raise ValueError("Git dependency host must be private") from None
        return value
    allowed = ((address.version == 4 and any(address in network for network in (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"))))
        or (address.version == 6 and address in ipaddress.ip_network("fc00::/7")))
    if (not allowed or address.is_loopback or address.is_unspecified
            or address.is_multicast or address.is_reserved):
        raise ValueError("Git dependency host must be private")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Git dependency URL has an invalid port") from exc
    return value


def probe_git_connectivity(endpoint: str, timeout: float = 3.0) -> dict[str, object]:
    endpoint = validate_git_endpoint(endpoint)
    parsed = urlsplit(endpoint)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 22), timeout=timeout):
            return {"dependency": "private_git_ssh", "reachable": True}
    except OSError:
        return {"dependency": "private_git_ssh", "reachable": False}


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate credential entry")
        result[key] = value
    return result


def load_client_credentials(path: str) -> dict[str, str]:
    """Load token -> run ID mapping from a runtime credential file, never echoing contents."""
    try:
        with open(path, "rb") as source:
            raw = source.read(_MAX_CREDENTIAL_FILE_BYTES + 1)
        if len(raw) > _MAX_CREDENTIAL_FILE_BYTES:
            raise ValueError("credential file is too large")
        credentials = json.loads(raw, object_pairs_hook=_unique_json_object)
        if (not isinstance(credentials, dict) or not credentials
                or any(not isinstance(token, str) or not token or not isinstance(run_id, str)
                       or not _SAFE_ID.fullmatch(run_id)
                       for token, run_id in credentials.items())):
            raise ValueError("invalid credentials")
        return credentials
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("unable to load runtime client credentials") from None


class AppendOnlyUsageLedger:
    """Create one new JSONL file for a run and append sanitized usage records."""

    def __init__(self, path: str):
        self.path = Path(path)
        parts = self.path.parts
        if (len(parts) != 4 or parts[0] != ".local" or parts[1] != "dsh-sandbox-runs"
                or not parts[2].startswith("run-") or parts[3] != "usage.jsonl"
                or not _SAFE_ID.fullmatch(parts[2][4:])):
            raise ValueError("usage ledger path must identify a new .local run")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        except OSError:
            raise ValueError("usage ledger already exists or cannot be created") from None
        self._lock = threading.Lock()

    def __call__(self, run_id: str, usage: dict[str, int] | None):
        if not _SAFE_ID.fullmatch(run_id):
            raise ValueError("invalid run identifier")
        record = json.dumps({
            "timestamp": time.time(),
            "run_id": run_id,
            "usage": usage,
        }, separators=(",", ":")).encode() + b"\n"
        with self._lock:
            os.write(self._fd, record)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class ControlPlaneConfig:
    def __init__(self, *, bind_address: str, port: int, cert_file: str, key_file: str,
                 git_ssh_url: str, endpoint: str, model: str, provider_key: str,
                 client_tokens: dict[str, str], max_requests_per_run: int,
                 max_tokens_per_run: int, max_cost_per_run: float,
                 input_cost_per_million: float, output_cost_per_million: float,
                 max_request_bytes: int = 1_048_576,
                 max_response_bytes: int = 4_194_304,
                 credential_ttl_seconds: float = 3600.0,
                 timeout_seconds: float = 60.0):
        self.bind_address = validate_bind_address(bind_address)
        self.git_ssh_url = validate_git_endpoint(git_ssh_url)
        if (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
                or not cert_file or not key_file):
            raise ValueError("invalid TLS listener configuration")
        self.port, self.cert_file, self.key_file = port, cert_file, key_file
        values = (max_requests_per_run, max_tokens_per_run, max_request_bytes, max_response_bytes)
        prices = (max_cost_per_run, input_cost_per_million, output_cost_per_million,
                  credential_ttl_seconds, timeout_seconds)
        if (any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value <= 0 for value in prices)):
            raise ValueError("invalid proxy budget configuration")
        self.proxy_kwargs = {
            "endpoint": endpoint,
            "model": model,
            "provider_key": provider_key,
            "client_tokens": client_tokens,
            "max_request_bytes": max_request_bytes,
            "max_response_bytes": max_response_bytes,
            "max_requests_per_run": max_requests_per_run,
            "max_tokens_per_run": max_tokens_per_run,
            "max_cost_per_run": max_cost_per_run,
            "input_cost_per_million": input_cost_per_million,
            "output_cost_per_million": output_cost_per_million,
            "credential_ttl_seconds": credential_ttl_seconds,
            "timeout_seconds": timeout_seconds,
        }
        ProxyConfig(**self.proxy_kwargs)

    @classmethod
    def from_env(cls, client_tokens: dict[str, str]):
        def required(name):
            value = os.environ.get(name)
            if not value:
                raise ValueError("missing runtime configuration: " + name)
            return value

        def integer(name):
            try:
                return int(required(name))
            except ValueError:
                raise ValueError("invalid runtime configuration: " + name) from None

        def number(name):
            try:
                return float(required(name))
            except ValueError:
                raise ValueError("invalid runtime configuration: " + name) from None

        return cls(
            bind_address=required("PROXY_BIND_ADDRESS"),
            port=integer("PROXY_PORT"),
            cert_file=required("PROXY_TLS_CERT_FILE"),
            key_file=required("PROXY_TLS_KEY_FILE"),
            git_ssh_url=required("SANDBOX_GIT_SSH_URL"),
            endpoint=required("LLM_BASE_URL"),
            model=required("LLM_MODEL"),
            provider_key=required("LLM_API_KEY"),
            client_tokens=client_tokens,
            max_requests_per_run=integer("MAX_REQUESTS_PER_RUN"),
            max_tokens_per_run=integer("MAX_TOKENS_PER_RUN"),
            max_cost_per_run=number("MAX_COST_PER_RUN"),
            input_cost_per_million=number("INPUT_COST_PER_MILLION"),
            output_cost_per_million=number("OUTPUT_COST_PER_MILLION"),
            max_request_bytes=integer("MAX_REQUEST_BYTES"),
            max_response_bytes=integer("MAX_RESPONSE_BYTES"),
            credential_ttl_seconds=number("CLIENT_CREDENTIAL_TTL_SECONDS"),
            timeout_seconds=number("UPSTREAM_TIMEOUT_SECONDS"),
        )


def _read_client_credentials_from_env() -> dict[str, str]:
    direct_path = os.environ.get("DSH_CLIENT_CREDENTIALS_FILE")
    if direct_path:
        path = direct_path
    else:
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        name = os.environ.get("DSH_CLIENT_CREDENTIALS_NAME", "client-tokens.json")
        if not directory or Path(name).name != name:
            raise ValueError("runtime client credentials are not configured")
        path = str(Path(directory) / name)
    return load_client_credentials(path)


def create_tls_server(config: ControlPlaneConfig, usage_ledger: AppendOnlyUsageLedger):
    proxy_config = ProxyConfig(usage_observer=usage_ledger, **config.proxy_kwargs)
    proxy_handler = create_handler(proxy_config)

    class ControlPlaneHandler(proxy_handler):
        def do_GET(self):
            if self.path != "/healthz":
                return super().do_GET()
            body = b'{"service":"model-proxy","status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(config.cert_file, config.key_file)
    server = ThreadingHTTPServer((config.bind_address, config.port), ControlPlaneHandler)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the private TLS model proxy")
    parser.add_argument("--check-git", action="store_true",
                        help="explicitly check the configured private Git SSH endpoint")
    args = parser.parse_args(argv)
    ledger = None
    try:
        tokens = _read_client_credentials_from_env()
        config = ControlPlaneConfig.from_env(tokens)
        if args.check_git:
            result = probe_git_connectivity(config.git_ssh_url)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["reachable"] else 1
        run_id = "run-" + __import__("uuid").uuid4().hex
        ledger = AppendOnlyUsageLedger(f".local/dsh-sandbox-runs/{run_id}/usage.jsonl")
        server = create_tls_server(config, ledger)
        os.environ.pop("LLM_API_KEY", None)
        server.serve_forever()
        return 0
    except (OSError, ssl.SSLError, ValueError):
        print(json.dumps({"service": "model-proxy", "status": "startup_failed"}))
        return 1
    finally:
        os.environ.pop("LLM_API_KEY", None)
        if ledger is not None:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
