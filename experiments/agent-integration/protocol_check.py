"""Check the real HTTP transport; this is not a native-agent experiment."""
import asyncio
import json
from pathlib import Path
from lab_paths import EVIDENCE_ROOT
from uuid import uuid4

from mcp import Client


async def check():
    run_id = str(uuid4())
    async with Client("http://127.0.0.1:8768/mcp") as client:
        tools = await client.list_tools()
        expected = {"post_probe", "read_probes", "ack_probe", "probe_receipts"}
        if not expected <= {tool.name for tool in tools.tools}:
            raise RuntimeError("missing probe tools")

        async def call(name, args):
            result = await client.call_tool(name, args)
            if result.is_error or result.structured_content is None:
                raise RuntimeError(f"probe call failed: {name}")
            return result.structured_content

        args = {"request_key": run_id, "author": "protocol-test", "body": "fictional schema v1"}
        row = await call("post_probe", args)
        retry = await call("post_probe", args)
        if row != retry:
            raise RuntimeError("retry created a different message")
        page = await call("read_probes", {"after_id": row["id"] - 1})
        if not any(message == row for message in page["messages"]):
            raise RuntimeError("posted message is not readable")
        receipt = await call("probe_receipts", {"message_id": row["id"]})
        if receipt["receivers"]:
            raise RuntimeError("reading unexpectedly acknowledged the message")
        for _ in range(2):
            ack = await call("ack_probe", {"message_id": row["id"], "receiver": "protocol-checker"})
            if ack.get("acknowledged") is not True:
                raise RuntimeError("acknowledgement failed")
        receipt = await call("probe_receipts", {"message_id": row["id"]})
        if receipt["receivers"] != ["protocol-checker"]:
            raise RuntimeError("receipt is missing or duplicated")
        report = {"run_id": run_id, "kind": "sdk-http-only", "message_id": row["id"],
                  "protocol_version": client.protocol_version, "passed": True}
    output = EVIDENCE_ROOT / (run_id + "-protocol.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(check())
