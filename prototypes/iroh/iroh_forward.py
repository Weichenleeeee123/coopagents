"""Prototype: forward local TCP over iroh (what the space bridge would do).

host:   python iroh_forward.py host <state_dir> <target_port>
        Persists its secret key so the endpoint id survives restarts; writes ticket.txt.
client: python iroh_forward.py client <state_dir> <ticket_or_file> <listen_port>
        Each local TCP connection becomes one bidirectional QUIC stream to the host.
Both sides append JSON lines to <state_dir>/log.jsonl. Nothing is deleted.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import iroh

ALPN = b'crewmesh-proto/0'
state = Path(sys.argv[2])
state.mkdir(parents=True, exist_ok=True)


def log(**row):
    row = {'t': round(time.time(), 2)} | row
    with open(state / 'log.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    print(json.dumps(row, ensure_ascii=False, default=str), flush=True)


def secret():
    key_file = state / 'secret.key'
    if not key_file.exists():
        key_file.write_bytes(iroh.SecretKey.generate().to_bytes())
    return key_file.read_bytes()


def describe_paths(conn):
    out = []
    try:
        for p in conn.paths():
            row = {k: str(getattr(p, k)) for k in dir(p) if not k.startswith('_') and not callable(getattr(p, k))}
            if os.environ.get('CREWMESH_REDACT'):
                row.pop('remote_addr', None)
                row.pop('stats', None)
            out.append(row)
    except Exception as exc:  # prototype: record, never hide
        out.append({'error': repr(exc)})
    return out


async def pump_quic_to_tcp(recv, writer):
    try:
        while True:
            chunk = await recv.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception as exc:
        log(event='pump_q2t_end', detail=repr(exc)[:200])
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def pump_tcp_to_quic(reader, send):
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            await send.write_all(chunk)
        await send.finish()
    except Exception as exc:
        log(event='pump_t2q_end', detail=repr(exc)[:200])


async def watch(conn, side):
    while True:
        log(event='path', side=side, rtt_ms=round(conn.rtt() / 1e6, 2) if isinstance(conn.rtt(), int) else str(conn.rtt()),
            paths=describe_paths(conn))
        await asyncio.sleep(10)


async def host(target_port):
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(preset=iroh.preset_n0(), secret_key=secret(), alpns=[ALPN]))
    await ep.online()
    ticket = str(iroh.EndpointTicket.from_addr(ep.addr()))
    (state / 'ticket.txt').write_text(ticket, encoding='utf-8')
    log(event='host_ready', id=str(ep.id()), ticket_len=len(ticket))
    while True:
        incoming = await ep.accept_next()
        if incoming is None:
            break
        asyncio.create_task(serve_conn(incoming, target_port))


async def serve_conn(incoming, target_port):
    conn = await (await incoming.accept()).connect()
    log(event='accepted', remote=str(conn.remote_id()))
    asyncio.create_task(watch(conn, 'host'))
    while True:
        try:
            bi = await conn.accept_bi()
        except Exception as exc:
            log(event='conn_closed', detail=repr(exc)[:200])
            return
        reader, writer = await asyncio.open_connection('127.0.0.1', target_port)
        asyncio.create_task(pump_quic_to_tcp(bi.recv(), writer))
        asyncio.create_task(pump_tcp_to_quic(reader, bi.send()))


async def client(ticket_arg, listen_port):
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(preset=iroh.preset_n0()))
    if ticket_arg.startswith('id:'):
        # Only the public key is shared; addresses come from iroh's discovery service.
        addr = iroh.EndpointAddr(iroh.EndpointId.from_string(ticket_arg[3:]), None, [])
    else:
        ticket_text = Path(ticket_arg).read_text(encoding='utf-8').strip() if Path(ticket_arg).exists() else ticket_arg
        addr = iroh.EndpointTicket.from_string(ticket_text).endpoint_addr()
    started = time.time()
    conn = await ep.connect(addr, ALPN)
    log(event='connected', remote=str(conn.remote_id()), connect_s=round(time.time() - started, 2))
    asyncio.create_task(watch(conn, 'client'))

    async def on_local(reader, writer):
        bi = await conn.open_bi()
        asyncio.create_task(pump_quic_to_tcp(bi.recv(), writer))
        asyncio.create_task(pump_tcp_to_quic(reader, bi.send()))

    server = await asyncio.start_server(on_local, '127.0.0.1', listen_port)
    log(event='client_listening', port=listen_port)
    async with server:
        await server.serve_forever()


async def main():
    iroh.iroh_ffi.uniffi_set_event_loop(asyncio.get_running_loop())
    if sys.argv[1] == 'host':
        await host(int(sys.argv[3]))
    else:
        await client(sys.argv[3], int(sys.argv[4]))


asyncio.run(main())
