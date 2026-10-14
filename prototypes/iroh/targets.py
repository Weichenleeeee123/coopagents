"""Local targets behind the iroh host, plus a probe that runs through the client's forwarded port.

serve <tcp_echo_port> <ws_echo_port>   start a TCP echo server and a WebSocket echo server
probe <state_dir> <tcp_port> <ws_port> measure echo round trips through the forwarded ports
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import websockets


async def tcp_echo(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    writer.close()


async def ws_echo(ws):
    async for message in ws:
        await ws.send(message)


async def serve(tcp_port, ws_port):
    tcp = await asyncio.start_server(tcp_echo, '127.0.0.1', tcp_port)
    async with websockets.serve(ws_echo, '127.0.0.1', ws_port):
        print(json.dumps({'event': 'targets_ready', 'tcp': tcp_port, 'ws': ws_port}), flush=True)
        async with tcp:
            await tcp.serve_forever()


async def probe(state, tcp_port, ws_port):
    result = {'t': round(time.time(), 2)}
    reader, writer = await asyncio.open_connection('127.0.0.1', tcp_port)
    rtts = []
    for i in range(20):
        start = time.perf_counter()
        writer.write(f'ping {i}\n'.encode())
        await writer.drain()
        await reader.readline()
        rtts.append((time.perf_counter() - start) * 1000)
    payload = b'x' * (1024 * 1024)
    start = time.perf_counter()
    writer.write(payload)
    await writer.drain()
    got = 0
    while got < len(payload):
        got += len(await reader.read(65536))
    result['tcp_rtt_ms'] = {'median': round(statistics.median(rtts), 1), 'max': round(max(rtts), 1)}
    result['tcp_1mib_echo_s'] = round(time.perf_counter() - start, 2)
    writer.close()
    async with websockets.connect(f'ws://127.0.0.1:{ws_port}/') as ws:
        ws_rtts = []
        for i in range(10):
            start = time.perf_counter()
            await ws.send(json.dumps({'n': i}))
            assert json.loads(await ws.recv())['n'] == i
            ws_rtts.append((time.perf_counter() - start) * 1000)
    result['ws_rtt_ms'] = {'median': round(statistics.median(ws_rtts), 1), 'max': round(max(ws_rtts), 1)}
    with open(Path(state) / 'probe.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(result) + '\n')
    print(json.dumps(result), flush=True)


if sys.argv[1] == 'serve':
    asyncio.run(serve(int(sys.argv[2]), int(sys.argv[3])))
else:
    asyncio.run(probe(sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
