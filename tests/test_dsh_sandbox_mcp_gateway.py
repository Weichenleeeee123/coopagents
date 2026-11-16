"""Provider-independent tests for the per-member sandbox MCP gateway."""

import json
import http.client
import asyncio
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODULE_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent-integration" / "dsh_sandbox"
sys.path.insert(0, str(MODULE_DIR))
import mcp_gateway
import bridge_client


class FakeBridgeClient:
    def __init__(self, identity):
        self.identity = identity
        self.calls = []

    async def list_tools(self):
        return [{"name": "whoami", "description": "Current identity", "inputSchema": {"type": "object"}}]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": self.identity}], "structuredContent": {"member_id": self.identity}}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeBridgeClient("member-front")
        self.gateway = mcp_gateway.MemberScopedGateway(self.client, member_id="member-front")
        self.server = self.gateway.serve_in_thread()
        self.url = f"http://127.0.0.1:{self.server.server_port}/mcp"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, payload, headers=None):
        return self.post_raw(json.dumps(payload).encode("utf-8"), headers)

    def post_raw(self, body, headers=None):
        request = Request(self.url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=4) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_only_tools_list_and_call_forward_to_this_member_client(self):
        status, result = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["tools"][0]["name"], "whoami")

        status, result = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["structuredContent"]["member_id"], "member-front")
        self.assertEqual(self.client.calls, [("whoami", {})])

    def test_business_tool_member_filter_is_forwarded_without_changing_gateway_identity(self):
        status, result = self.post({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                                    "params": {"name": "read_context", "arguments": {"member_id": "member-back"}}})
        self.assertEqual(status, 200)
        self.assertEqual(self.client.calls, [("read_context", {"member_id": "member-back"})])
        self.assertEqual(result["result"]["structuredContent"]["member_id"], "member-front")

    def test_rejects_identity_and_authentication_override_attempts(self):
        attempts = (
            ({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"member_id": "member-back"}}, {}),
            ({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "whoami", "member_id": "member-back", "arguments": {}}}, {}),
            ({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "whoami", "arguments": {"agent_token": "sentinel"}}}, {}),
            ({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {"authorization": "Bearer sentinel"}}, {}),
            ({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}, {"Authorization": "Bearer sentinel"}),
            ({"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {}}, {"X-Member-Id": "member-back"}),
        )
        for payload, headers in attempts:
            with self.subTest(payload=payload, headers=headers):
                self.assertEqual(self.post(payload, headers)[0], 400)
        self.assertEqual(self.client.calls, [])

    def test_gateway_cannot_bind_public_interface(self):
        with self.assertRaises(ValueError):
            mcp_gateway.MemberScopedGateway(self.client, member_id="member-front", host="0.0.0.0")
        with self.assertRaises(ValueError):
            mcp_gateway.MemberScopedGateway(self.client, member_id="member-back")

    def test_credentials_are_rejected_without_echo(self):
        status, payload = self.post({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "whoami", "arguments": {"access_token": "member-secret"}}})
        self.assertEqual(status, 400)
        self.assertNotIn("member-secret", json.dumps(payload))

    def test_oversized_and_malformed_bodies_are_rejected(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        connection.putrequest("POST", "/mcp")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(mcp_gateway.MAX_REQUEST_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        connection.close()
        status, payload = self.post_raw(b"not-json")
        self.assertEqual(status, 400)
        self.assertNotIn("not-json", json.dumps(payload))


class BridgeAdapterTests(unittest.TestCase):
    def test_adapter_uses_bridge_remote_and_preserves_member_identity(self):
        class Remote:
            async def list_tools(self, cursor=None):
                return type("Page", (), {"tools": [{"name": "whoami"}], "next_cursor": None})()

            async def call_tool(self, name, arguments):
                return {"name": name, "arguments": arguments}

        class Bridge:
            identity = ("room-1", "member-front")

            @asynccontextmanager
            async def remote(self):
                yield Remote()

        adapter = bridge_client.BridgeMCPClient("private-profile.json", bridge_factory=lambda _: Bridge())
        self.assertEqual(adapter.member_id, "member-front")
        self.assertEqual(asyncio.run(adapter.list_tools()), [{"name": "whoami"}])
        self.assertEqual(asyncio.run(adapter.call_tool("whoami", {})), {"name": "whoami", "arguments": {}})


if __name__ == "__main__":
    unittest.main()
