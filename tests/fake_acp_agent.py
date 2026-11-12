"""Stand-in ACP agent (kimi acp) for client tests: newline JSON-RPC on stdio.

Behavior is driven by environment variables:
  FAKE_ACP_STATE: append one JSON line per received request and reverse reply.
  FAKE_ACP_REVERSE: on session/new, first send an fs/read_text_file reverse
    request and record the client's reply before answering.
  FAKE_ACP_SLEEP: seconds to sleep before answering session/prompt.
  FAKE_ACP_GARBAGE: emit a non-JSON line at startup.
  FAKE_ACP_EXIT: exit immediately without reading stdin.
"""
import json
import os
import sys
import time

state = os.environ.get('FAKE_ACP_STATE')


def record(event):
    if state:
        with open(state, 'a', encoding='utf-8') as output:
            output.write(json.dumps(event) + '\n')


def send(payload):
    print(json.dumps(payload), flush=True)


if os.environ.get('FAKE_ACP_EXIT'):
    sys.exit(0)
if os.environ.get('FAKE_ACP_GARBAGE'):
    print('this is not json', flush=True)

for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    method, request_id = message.get('method'), message.get('id')
    record({'method': method, 'params': message.get('params')})
    if method == 'initialize':
        send({'jsonrpc': '2.0', 'id': request_id, 'result': {
            'protocolVersion': 1,
            'agentInfo': {'name': 'Kimi Code CLI', 'version': '9.9.9-test'},
            'capabilities': {'loadSession': True},
            'authMethods': [{'id': 'login', 'name': 'Terminal login'}]}})
    elif method == 'session/new':
        if os.environ.get('FAKE_ACP_REVERSE'):
            send({'jsonrpc': '2.0', 'id': 9001, 'method': 'fs/read_text_file',
                  'params': {'path': '/tmp/kimi-acp-probe.txt'}})
            record({'reverse_reply': json.loads(sys.stdin.readline())})
        send({'jsonrpc': '2.0', 'id': request_id, 'result': {'sessionId': 'sess-1'}})
    elif method == 'session/prompt':
        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'sess-1',
            'update': {'sessionUpdate': 'agent_message_chunk',
                       'content': {'type': 'text', 'text': 'hi'}}}})
        sleep = float(os.environ.get('FAKE_ACP_SLEEP', '0'))
        if sleep:
            time.sleep(sleep)
        send({'jsonrpc': '2.0', 'id': request_id, 'result': {'stopReason': 'end_turn'}})
    elif method in ('session/cancel', 'session/close', 'authenticate'):
        send({'jsonrpc': '2.0', 'id': request_id, 'result': {}})
    elif method == 'session/fail':
        send({'jsonrpc': '2.0', 'id': request_id,
              'error': {'code': -32603, 'message': 'Stub failure'}})
    elif request_id is not None:
        send({'jsonrpc': '2.0', 'id': request_id,
              'error': {'code': -32601, 'message': 'Method not found'}})
