"""Pure parsers for Codex exec JSON and Claude print stream-json observations.

No processes, files or network are opened. Inputs are decoded JSON objects,
optionally wrapped as {at: unix_seconds, event: object}. evidence_index is the
zero-based input position of the first actual call observation; at is its
collector timestamp, never an inferred model timestamp. Results stay native.

Usage preserves reported input_tokens; cached_input_tokens maps Claude
cache_read_input_tokens. Native cache_creation_input_tokens is a separate field,
never added into either existing input count; Codex leaves it unknown.
Per-message/turn cumulative snapshots use maxima, not fragment sums. Claude's
native final usage/cost summary supersedes message subtotals. No prices are
estimated. Missing identities, usage fields or cost remain null.
"""
import json
import math


USAGE_KEYS = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_creation_input_tokens')
CODEX_TOOLS = {'mcp_tool_call', 'command_execution', 'web_search', 'file_change', 'todo_list'}


def _number(value, *, integer=False):
    if type(value) is int:
        return value if value >= 0 else None
    if type(value) is not float or not math.isfinite(value) or value < 0:
        return None
    return value if not integer or type(value) is int else None


def _usage(value):
    value = value if isinstance(value, dict) else {}
    return {key: _number(value.get(key, value.get('cache_read_input_tokens')
                                if key == 'cached_input_tokens' else None), integer=True)
            for key in USAGE_KEYS}


def _sum_known(values):
    values = list(values)
    return sum(values) if values and all(v is not None for v in values) else None


def _sum_usage(values):
    values = list(values)
    return {key: _sum_known(value.get(key) if isinstance(value, dict) else None for value in values)
            for key in USAGE_KEYS}


def _error_flag(value):
    return isinstance(value, dict) and (value.get('isError') is True or value.get('is_error') is True
        or isinstance(value.get('type'), str) and value['type'].endswith('_tool_result_error'))


def _error_status(value):
    text = json.dumps(value, ensure_ascii=True, default=str).lower()
    quota = ('quota', 'usage_limit', 'rate_limit', 'rate limit', 'no credits',
             'credit balance', 'hit your limit', 'max_budget', 'billing_hard_limit')
    return 'quota' if any(marker in text for marker in quota) else 'error'


class _Trace:
    def __init__(self, harness):
        self.harness = harness
        self.session = None
        self.models = []
        self.calls = {}
        self.completed_calls = set()
        self.results = {}
        self.errors = []
        self.incomplete = False
        self.status, self.terminal = 'unknown', False
        self.usages = {}
        self.total_usage = None
        self.costs, self.total_cost = {}, None
        self.turn, self.turn_open = 0, False
        self.turn_key = ('turn', 0)
        self.usage_ambiguous = False
        self.streams, self.uuids = {}, set()

    def issue(self, kind, index, detail, *, incomplete=False):
        self.errors.append({'kind': kind, 'evidence_index': index, 'detail': detail})
        self.incomplete = self.incomplete or incomplete

    def identity(self, raw, index):
        session = raw.get('thread_id') if self.harness == 'codex' else raw.get('session_id')
        if isinstance(session, str) and session:
            if self.session is not None and self.session != session:
                self.issue('session_conflict', index, 'Multiple session identities in one trace', incomplete=True)
            elif self.session is None:
                self.session = session

    def identifier(self, raw, key, index):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            self.issue('malformed_identifier', index, key, incomplete=True)
        return None

    def message_usage(self, msg, index):
        identifier = self.identifier(msg, 'id', index)
        if identifier is None:
            self.usage_ambiguous = True
            self.issue('missing_message_id', index, 'Message usage cannot be deduplicated', incomplete=True)
        self.usage(('message', identifier if identifier is not None else ('missing', index)), msg.get('usage'))
        return identifier

    def model(self, value):
        if isinstance(value, str) and value and value not in self.models:
            self.models.append(value)

    def usage(self, key, value):
        prior = self.usages.setdefault(key, {k: None for k in USAGE_KEYS})
        for metric, amount in _usage(value).items():
            if self.harness == 'codex' and metric == 'cache_creation_input_tokens':
                continue
            if amount is not None:
                prior[metric] = max(prior[metric], amount) if prior[metric] is not None else amount

    def call(self, identifier, name, arguments, at, index):
        key = identifier if isinstance(identifier, str) and identifier else ('missing-id', index)
        if name is not None and (not isinstance(name, str) or not name):
            self.issue('malformed_tool_name', index, 'Expected a native tool name', incomplete=True)
            name = None
        if key not in self.calls:
            self.calls[key] = {'id': identifier if isinstance(identifier, str) else None,
                'name': name, 'arguments': arguments, 'result': None, 'is_error': None,
                'at': at, 'evidence_index': index}
            if not isinstance(key, str):
                self.issue('missing_call_id', index, 'Tool observation has no usable id', incomplete=True)
            if name is None:
                self.issue('missing_tool_name', index, 'Tool observation has no name', incomplete=True)
        else:
            if name is not None:
                self.calls[key]['name'] = name
            if arguments is not None:
                self.calls[key]['arguments'] = arguments
        if key in self.results:
            self.attach(key, *self.results[key])
        return key

    def attach(self, key, result, failed, index, native_error=None):
        call = self.calls[key]
        if key in self.completed_calls and (call['result'], call['is_error']) == (result, failed):
            return
        if key in self.completed_calls:
            self.issue('conflicting_tool_results', index, {'id': call['id']}, incomplete=True)
        call['result'], call['is_error'] = result, failed
        self.completed_calls.add(key)
        if failed:
            self.issue('tool_error', index, {'id': call['id'], 'error': native_error,
                                            'result': result})

    def codex(self, raw, at, index):
        kind = raw.get('type')
        if kind in ('thread.started', 'turn.started', 'turn.completed'):
            self.model(raw.get('model'))
        if kind == 'turn.started':
            identifier = self.identifier(raw, 'turn_id', index)
            if identifier is not None and ('turn', identifier) in self.usages:
                return
            if self.turn_open:
                self.issue('unfinished_turn', index, 'New turn started before a terminal event', incomplete=True)
            self.turn += 1
            self.turn_key = ('turn', identifier if identifier is not None else self.turn)
            self.turn_open = True
            self.status, self.terminal = 'unknown', False
            self.usages.setdefault(self.turn_key, {k: None for k in USAGE_KEYS})
        elif kind in ('turn.completed', 'turn.failed'):
            identifier = self.identifier(raw, 'turn_id', index)
            key = ('turn', identifier) if identifier is not None else self.turn_key
            self.turn_key = key
            self.usage(key, raw.get('usage'))
            self.costs.setdefault(key, None)
            if _number(raw.get('cost_usd')) is not None:
                self.costs[key] = _number(raw['cost_usd'])
            self.turn_open = False
            self.terminal = True
            self.status = 'success' if kind == 'turn.completed' else _error_status(raw.get('error'))
            if kind == 'turn.failed':
                self.issue('native_error', index, raw.get('error'))
        elif kind == 'error':
            detail = raw.get('error', raw.get('message'))
            self.status = _error_status(detail)
            self.terminal = False
            self.issue('native_error', index, detail)
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            item = raw.get('item')
            if not isinstance(item, dict):
                self.issue('malformed_item', index, 'Expected an item object', incomplete=True)
                return
            item_kind = item.get('type')
            if not isinstance(item_kind, str):
                self.issue('malformed_item_type', index, 'Expected a native item type', incomplete=True)
                return
            if item_kind == 'error':
                self.issue('native_error', index, item.get('message', item.get('error')))
                return
            if item_kind not in CODEX_TOOLS:
                if item_kind not in ('agent_message', 'reasoning'):
                    self.issue('unsupported_item_type', index, item_kind, incomplete=True)
                return
            name = item.get('tool') if item_kind == 'mcp_tool_call' else item_kind
            args = (item.get('arguments') if item_kind == 'mcp_tool_call' else
                    {'command': item['command']} if item_kind == 'command_execution' and 'command' in item else
                    {'query': item['query']} if item_kind == 'web_search' and 'query' in item else None)
            key = self.call(item.get('id'), name, args, at, index)
            if kind != 'item.completed':
                return
            result = item.get('result')
            if item_kind == 'command_execution':
                result = {k: item[k] for k in ('aggregated_output', 'exit_code') if k in item}
                result = result or None
            elif item_kind == 'file_change':
                result = {k: item[k] for k in ('changes', 'status') if k in item} or result
            elif item_kind == 'todo_list' and 'items' in item:
                result = {'items': item['items']}
            failed = (item.get('status') == 'failed' or item.get('error') is not None or _error_flag(result)
                      or item_kind == 'command_execution' and type(item.get('exit_code')) is int and item['exit_code'] != 0)
            # Completion is native evidence, but a shell exit status may be absent.
            known = (failed or item_kind != 'command_execution' or type(item.get('exit_code')) is int)
            self.attach(key, result, bool(failed) if known else None, index, item.get('error'))

    def blocks(self, blocks, at, index, *, role='assistant'):
        if role == 'user' and isinstance(blocks, str):
            return
        if not isinstance(blocks, list):
            self.issue('malformed_content', index, 'Expected structured content blocks', incomplete=True)
            return
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind in ('tool_use', 'server_tool_use') and role != 'user':
                self.call(block.get('id'), block.get('name'), block.get('input'), at, index)
            elif (kind == 'tool_result' and role == 'user'
                  or isinstance(kind, str) and kind != 'tool_result' and kind.endswith('_tool_result')):
                key = block.get('tool_use_id')
                if not isinstance(key, str) or not key:
                    self.issue('missing_result_id', index, 'Tool result has no call id', incomplete=True)
                    continue
                content = block.get('content')
                failed = block.get('is_error') is True or _error_flag(content)
                self.results[key] = (content, failed, index, None)
                if key in self.calls:
                    self.attach(key, *self.results[key])

    def stream(self, raw, at, index):
        event = raw.get('event')
        if not isinstance(event, dict):
            self.issue('malformed_stream', index, 'Expected a stream event object', incomplete=True)
            return
        session = self.identifier(raw, 'session_id', index)
        parent = self.identifier(raw, 'parent_tool_use_id', index)
        if raw.get('parent_tool_use_id') is not None and parent is None:
            return
        key = (session, parent)
        kind = event.get('type')
        if kind == 'message_start':
            msg = event.get('message')
            if not isinstance(msg, dict):
                self.issue('malformed_message', index, 'Expected a native message object', incomplete=True)
                return
            identifier = self.message_usage(msg, index)
            self.streams[key] = {'message_id': identifier, 'blocks': {}, 'open': True}
            self.model(msg.get('model'))
            return
        current = self.streams.get(key)
        if current is None:
            self.issue('orphan_stream_fragment', index, kind, incomplete=True)
            return
        block_index = event.get('index')
        if kind == 'content_block_start':
            block = event.get('content_block')
            if not isinstance(block, dict) or type(block_index) is not int:
                self.issue('malformed_stream_block', index, 'Invalid content block', incomplete=True)
                return
            current['blocks'][block_index] = {'block': block, 'json': '', 'closed': False}
            self.blocks([block], at, index)
        elif kind == 'content_block_delta':
            delta = event.get('delta')
            if isinstance(delta, dict) and delta.get('type') == 'input_json_delta':
                block = current['blocks'].get(block_index) if type(block_index) is int else None
                fragment = delta.get('partial_json')
                if block is None or not isinstance(fragment, str):
                    self.issue('orphan_input_fragment', index, 'Input delta has no matching block', incomplete=True)
                else:
                    block['json'] += fragment
                    identifier = block['block'].get('id')
                    if isinstance(identifier, str) and identifier in self.calls:
                        self.calls[identifier]['arguments'] = None
        elif kind == 'content_block_stop':
            block = current['blocks'].get(block_index) if type(block_index) is int else None
            if block:
                block['closed'] = True
            if block and block['json']:
                try:
                    args = json.loads(block['json'])
                    identifier = block['block'].get('id')
                    if isinstance(identifier, str) and identifier in self.calls:
                        self.calls[identifier]['arguments'] = args
                except (ValueError, TypeError):
                    self.issue('malformed_tool_input', index, 'Incomplete tool argument JSON', incomplete=True)
                    identifier = block['block'].get('id')
                    if isinstance(identifier, str) and identifier in self.calls:
                        self.calls[identifier]['arguments'] = None
        elif kind == 'message_delta':
            self.usage(('message', current['message_id']), event.get('usage'))
        elif kind == 'message_stop':
            if any(not b['closed'] for b in current['blocks'].values()):
                self.issue('unclosed_content_block', index, 'Message ended before its blocks', incomplete=True)
            current['open'] = False

    def claude(self, raw, at, index):
        kind = raw.get('type')
        if kind == 'system' and raw.get('subtype') == 'init':
            self.model(raw.get('model'))
        elif kind in ('assistant', 'user'):
            msg = raw.get('message')
            if not isinstance(msg, dict):
                self.issue('malformed_message', index, 'Expected a native message object', incomplete=True)
                return
            if kind == 'assistant':
                identifier = self.message_usage(msg, index)
                self.model(msg.get('model'))
                if raw.get('error') is not None:
                    self.issue('native_error', index, raw['error'])
                    self.status = _error_status(raw['error'])
                for stream in self.streams.values():
                    if stream['message_id'] == identifier:
                        stream['open'] = False
            self.blocks(msg.get('content', []), at, index, role=kind)
        elif kind == 'stream_event':
            self.stream(raw, at, index)
        elif kind == 'result':
            self.terminal = True
            failed = raw.get('is_error') is True or str(raw.get('subtype', '')).startswith('error_')
            if failed:
                detail = {k: raw[k] for k in ('subtype', 'errors', 'result') if k in raw}
                self.status = _error_status(detail)
                self.issue('native_error', index, detail)
            else:
                self.status = 'success' if raw.get('is_error') is False or raw.get('subtype') == 'success' else 'unknown'
            if isinstance(raw.get('usage'), dict):
                self.total_usage = _usage(raw['usage'])
            if 'total_cost_usd' in raw or 'cost_usd' in raw:
                self.total_cost = _number(raw.get('total_cost_usd', raw.get('cost_usd')))
            if isinstance(raw.get('modelUsage'), dict):
                for model in raw['modelUsage']:
                    self.model(model)
                if 'total_cost_usd' not in raw and 'cost_usd' not in raw:
                    self.total_cost = _sum_known(_number(m.get('costUSD')) if isinstance(m, dict) else None
                                                 for m in raw['modelUsage'].values())
        elif kind == 'error':
            self.terminal = False
            self.status = _error_status(raw.get('error', raw.get('message')))
            self.issue('native_error', index, raw.get('error', raw.get('message')))

    def finish(self):
        for key, call in self.calls.items():
            if key not in self.completed_calls:
                self.issue('unpaired_tool_call', call['evidence_index'], {'id': call['id']}, incomplete=True)
        for key, result in self.results.items():
            if key not in self.calls:
                self.issue('orphan_tool_result', result[2], {'id': key}, incomplete=True)
        partial = self.turn_open or any(s['open'] for s in self.streams.values())
        return {'session_id': self.session, 'models': self.models, 'tool_calls': list(self.calls.values()),
                'usage': self.total_usage if self.total_usage is not None else
                         _sum_usage([] if self.usage_ambiguous else self.usages.values()),
                'cost_usd': self.total_cost if self.harness == 'claude' else _sum_known(self.costs.values()),
                'terminal_status': self.status,
                'complete': bool(self.terminal and not self.incomplete and not partial and self.status != 'unknown'),
                'errors': self.errors}


def parse_trace(harness, events):
    """Parse decoded native events; assistant prose is never execution evidence.

    Supports a single event or an iterable of events. Malformed entries are
    reported with their index, never parsed as assistant-written JSON. For
    partial streams, pending calls remain visible with null result/error state.
    A diagnostic error alone does not prove the process reached a terminal end.
    """
    if harness not in ('codex', 'claude'):
        raise ValueError('Harness must be codex or claude')
    trace = _Trace(harness)
    if isinstance(events, dict) or isinstance(events, (str, bytes)) or events is None:
        events = [events]
    try:
        events = iter(events)
    except TypeError:
        events = iter([events])
    for index, supplied in enumerate(events):
        raw, at = supplied, None
        if isinstance(supplied, dict) and 'type' not in supplied and 'event' in supplied:
            raw, at = supplied.get('event'), _number(supplied.get('at'))
        if not isinstance(raw, dict) or not isinstance(raw.get('type'), str):
            trace.issue('malformed_event', index, 'Expected a decoded native event object', incomplete=True)
            continue
        identifier = raw.get('uuid')
        if isinstance(identifier, str):
            key = (raw['type'], identifier)
            if key in trace.uuids:
                continue
            trace.uuids.add(key)
        trace.identity(raw, index)
        getattr(trace, harness)(raw, at, index)
    return trace.finish()


def aggregate_traces(traces):
    """Strict metric totals: any missing component keeps that total unknown."""
    traces = list(traces)
    models = list(dict.fromkeys(model for t in traces for model in t.get('models', [])))
    states = [t.get('terminal_status', 'unknown') for t in traces]
    status = ('quota' if 'quota' in states else 'error' if 'error' in states else
              'success' if states and all(s == 'success' for s in states) else 'unknown')
    return {'trace_count': len(traces), 'session_ids': [t.get('session_id') for t in traces],
            'models': models, 'tool_call_count': sum(len(t.get('tool_calls', [])) for t in traces),
            'usage': _sum_usage(t.get('usage') for t in traces),
            'cost_usd': _sum_known(_number(t.get('cost_usd')) for t in traces),
            'terminal_status': status, 'complete': bool(traces) and all(t.get('complete') is True for t in traces),
            'errors': [error for t in traces for error in t.get('errors', [])]}
