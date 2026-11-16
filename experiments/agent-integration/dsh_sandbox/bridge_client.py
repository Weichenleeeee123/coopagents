"""Adapter from the sandbox gateway to the configured Coopagents member bridge."""

import argparse
from contextlib import asynccontextmanager
if __package__:
    from .mcp_gateway import MemberScopedGateway
else:
    from mcp_gateway import MemberScopedGateway


class BridgeMCPClient:
    """Open short-lived authenticated MCP requests using one private profile."""

    def __init__(self, profile_path, *, bridge_factory=None):
        if bridge_factory is None:
            from coopagents.space_bridge import Bridge
            bridge_factory = Bridge
        self.bridge = bridge_factory(profile_path)
        self.identity = self.bridge.identity
        self.member_id = self.identity[1]

    @asynccontextmanager
    async def _remote(self):
        async with self.bridge.remote() as remote:
            yield remote

    async def list_tools(self):
        async with self._remote() as remote:
            tools = []
            cursor = None
            for _ in range(10):
                page = await remote.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    return tools
            raise RuntimeError("Tool list exceeded bounded pages")

    async def call_tool(self, name, arguments):
        async with self._remote() as remote:
            return await remote.call_tool(name, arguments)


def serve(profile_path, port):
    from coopagents.spaces import read_profile
    from coopagents.p2p import member_link
    profile = read_profile(profile_path)
    bridge = BridgeMCPClient(profile_path)
    gateway = MemberScopedGateway(bridge, member_id=bridge.member_id)
    with member_link(profile):
        gateway.serve_forever(port)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Loopback MCP gateway for one Coopagents member profile")
    parser.add_argument("--profile", required=True, help="Private member profile path")
    parser.add_argument("--port", type=int, default=8769)
    options = parser.parse_args(argv)
    serve(options.profile, options.port)


if __name__ == "__main__":
    main()
