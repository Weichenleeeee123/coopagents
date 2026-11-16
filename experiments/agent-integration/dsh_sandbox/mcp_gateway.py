"""Loopback MCP HTTP gateway scoped to one preconfigured member.

The bridge client is injected so transport behavior can be tested locally. The
production adapter in ``bridge_client.py`` uses the private member profile and
the existing authenticated Bridge.remote()/P2P link lifecycle.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import threading
from urllib.parse import urlsplit


MAX_REQUEST_BYTES = 64 * 1024
MCP_PROTOCOL_VERSION = "2025-03-26"
_AUTH_KEYS = frozenset({
    "authorization", "proxyauthorization", "token", "accesstoken",
    "agenttoken", "webtoken", "controltoken", "membertoken", "bearer",
})
_AUTH_HEADERS = frozenset({
    "authorization", "proxy-authorization", "x-member-id", "x-member-token",
    "x-agent-token", "x-access-token", "x-control-token", "x-identity",
})


def _model_dict(value):
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if dump:
        return dump(by_alias=True, exclude_none=True)
    legacy_dump = getattr(value, "dict", None)
    if legacy_dump:
        return legacy_dump(by_alias=True, exclude_none=True)
    raise TypeError("Unsupported bridge response")


def _contains_credential_override(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _AUTH_KEYS:
                return True
            if _contains_credential_override(child):
                return True
    elif isinstance(value, list):
        return any(_contains_credential_override(child) for child in value)
    return False


def _has_identity_override(params):
    if not isinstance(params, dict):
        return False
    return any("".join(character for character in str(key).lower() if character.isalnum()) == "memberid"
               for key in params)


class MemberScopedGateway:
    """Serve stateless JSON-RPC MCP over an IPv4 loopback interface only."""

    def __init__(self, bridge_client, *, member_id, host="127.0.0.1", max_request_bytes=MAX_REQUEST_BYTES):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("Gateway host must be an IPv4 loopback address") from None
        if address.version != 4 or not address.is_loopback:
            raise ValueError("Gateway host must be an IPv4 loopback address")
        if not isinstance(member_id, str) or not member_id.strip():
            raise ValueError("A fixed member identity is required")
        if type(max_request_bytes) is not int or not 1 <= max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError("Invalid gateway request limit")
        if not callable(getattr(bridge_client, "list_tools", None)) or not callable(getattr(bridge_client, "call_tool", None)):
            raise TypeError("bridge_client must implement async list_tools() and call_tool(name, arguments)")
        client_identity = getattr(bridge_client, "member_id", None)
        if client_identity is None:
            client_identity = getattr(bridge_client, "identity", None)
        if isinstance(client_identity, tuple) and len(client_identity) == 2:
            client_identity = client_identity[1]
        if client_identity != member_id:
            raise ValueError("Gateway identity must match the configured bridge client")
        self._bridge = bridge_client
        self.member_id = member_id
        self.host = str(address)
        self.max_request_bytes = max_request_bytes
        self._server = None
        self._thread = None

    async def _dispatch(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
        request_id = message.get("id")
        method = message["method"]
        params = message.get("params", {})
        if request_id is None:
            if method == "notifications/initialized":
                return None
            return None
        if not isinstance(params, dict) or _contains_credential_override(params) or _has_identity_override(params):
            return self._error(request_id, -32602, "Invalid request parameters")
        try:
            if method == "initialize":
                return {"jsonrpc": "2.0", "id": request_id, "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "Coopagents member gateway", "version": "0.1.0"},
                }}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": request_id, "result": {}}
            if method == "tools/list":
                tools = await self._bridge.list_tools()
                return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [_model_dict(tool) for tool in tools]}}
            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments", {})
                if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                    return self._error(request_id, -32602, "Invalid tool request")
                result = await self._bridge.call_tool(name, arguments)
                return {"jsonrpc": "2.0", "id": request_id, "result": _model_dict(result)}
            return self._error(request_id, -32601, "Method not found")
        except Exception:
            # Bridge exceptions may contain URLs, credentials or request data.
            return self._error(request_id, -32603, "Gateway operation failed")

    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _make_server(self, port=0):
        gateway = self

        class QuietThreadingHTTPServer(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                return

            def _respond(self, status, payload=None):
                body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.close_connection = True
                self.send_response(status)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(body)))
                if payload is not None:
                    self.send_header("Content-Type", "application/json")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_POST(self):
                parsed = urlsplit(self.path)
                if parsed.path != "/mcp" or parsed.query or parsed.fragment:
                    self._respond(404, {"error": "Not found"})
                    return
                try:
                    host_header = self.headers.get("Host", "")
                    host_name = host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header
                    host_address = ipaddress.ip_address(host_name.strip("[]"))
                except ValueError:
                    self._respond(400, {"error": "Invalid local request"})
                    return
                if not host_address.is_loopback:
                    self._respond(400, {"error": "Invalid local request"})
                    return
                if any(name.lower() in _AUTH_HEADERS for name in self.headers.keys()):
                    self._respond(400, {"error": "Authentication override rejected"})
                    return
                if self.headers.get("Transfer-Encoding"):
                    self._respond(400, {"error": "Invalid request framing"})
                    return
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    self._respond(415, {"error": "Expected application/json"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self._respond(400, {"error": "Invalid request length"})
                    return
                if length < 1 or length > gateway.max_request_bytes:
                    self._respond(413, {"error": "Request body too large or empty"})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._respond(400, {"error": "Invalid request body"})
                    return
                try:
                    message = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    self._respond(400, {"error": "Malformed JSON"})
                    return
                params = message.get("params", {}) if isinstance(message, dict) else {}
                if _contains_credential_override(params) or _has_identity_override(params):
                    self._respond(400, {"error": "Identity or authentication override rejected"})
                    return
                response = asyncio.run(gateway._dispatch(message))
                self._respond(202 if response is None else 200, response)

            def do_GET(self):
                self._respond(405, {"error": "Method not allowed"})

            def do_PUT(self):
                self._respond(405, {"error": "Method not allowed"})

            def do_DELETE(self):
                self._respond(405, {"error": "Method not allowed"})

        return QuietThreadingHTTPServer((self.host, port), Handler)

    def serve_in_thread(self):
        """Start the local listener for tests or an embedding supervisor."""
        if self._server is not None:
            raise RuntimeError("Gateway is already serving")
        self._server = self._make_server()
        self._thread = threading.Thread(target=self._server.serve_forever, name="dsh-mcp-gateway", daemon=True)
        self._thread.start()
        return self._server

    def serve_forever(self, port):
        """Run the gateway on a specified ephemeral or provisioned local port."""
        if self._server is not None:
            raise RuntimeError("Gateway is already serving")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("Invalid gateway port")
        self._server = self._make_server(port)
        self._server.serve_forever()
