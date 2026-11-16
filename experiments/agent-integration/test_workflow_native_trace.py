"""Synthetic native-format fixtures; no process, network or model execution."""
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).with_name('workflow_native_trace.py')


def message(identifier='m1', blocks=None, usage=None):
    msg = {'id': identifier, 'model': 'claude-fixture', 'content': blocks or []}
    if usage is not None:
        msg['usage'] = usage
    return {'type': 'assistant', 'session_id': 'claude-session', 'message': msg}


def tool_result(identifier, content, **extra):
    return {'type': 'user', 'session_id': 'claude-session', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': identifier, 'content': content, **extra}]}}


def terminal(**extra):
    return {'type': 'result', 'session_id': 'claude-session', 'subtype': 'success',
            'is_error': False, **extra}


class NativeTraceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), 'native trace parser is missing')
        spec = importlib.util.spec_from_file_location('workflow_native_trace', MODULE)
        self.trace = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.trace)

    def parse(self, harness, events):
        return self.trace.parse_trace(harness, events)

    def test_codex_actual_shell_and_mcp_results_keep_provenance_and_unknown_cost(self):
        events = [
            {'type': 'thread.started', 'thread_id': 'codex-session', 'model': 'codex-fixture'},
            {'type': 'turn.started'},
            {'at': 12.5, 'event': {'type': 'item.completed', 'item': {'id': 'shell',
                'type': 'command_execution', 'command': 'echo fixture', 'exit_code': 0,
                'aggregated_output': 'fixture', 'status': 'completed'}}},
            {'at': 14, 'event': {'type': 'item.completed', 'item': {'id': 'mcp',
                'type': 'mcp_tool_call', 'server': 'coopagents', 'tool': 'read_workflow',
                'arguments': {'task_id': 1}, 'result': {'content': [], 'future': {'kept': True}},
                'error': None, 'status': 'completed'}}},
            {'type': 'item.completed', 'item': {'id': 'text', 'type': 'agent_message',
                'text': '{"tool":"imaginary","result":{"ok":true}}'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 20, 'output_tokens': 5, 'cached_input_tokens': 8}},
        ]
        report = self.parse('codex', events)
        self.assertEqual(report['session_id'], 'codex-session')
        self.assertEqual(report['models'], ['codex-fixture'])
        self.assertEqual([c['name'] for c in report['tool_calls']], ['command_execution', 'read_workflow'])
        self.assertEqual(report['tool_calls'][0]['arguments'], {'command': 'echo fixture'})
        self.assertEqual(report['tool_calls'][0]['result']['exit_code'], 0)
        self.assertEqual(report['tool_calls'][0]['at'], 12.5)
        self.assertEqual(report['tool_calls'][0]['evidence_index'], 2)
        self.assertEqual(report['tool_calls'][1]['result']['future'], {'kept': True})
        self.assertEqual(report['usage'], {'input_tokens': 20, 'output_tokens': 5, 'cached_input_tokens': 8,
                                          'cache_creation_input_tokens': None})
        self.assertIsNone(report['cost_usd'])
        self.assertEqual(report['terminal_status'], 'success')
        self.assertTrue(report['complete'])

    def test_codex_started_updated_and_failed_completion_are_one_actual_call(self):
        events = [
            {'at': 1, 'event': {'type': 'item.started', 'item': {'id': 'x', 'type': 'mcp_tool_call',
                'tool': 'reply', 'arguments': {'body': 'answer'}, 'status': 'in_progress'}}},
            {'type': 'item.updated', 'item': {'id': 'x', 'type': 'mcp_tool_call', 'status': 'in_progress'}},
            {'type': 'item.completed', 'item': {'id': 'x', 'type': 'mcp_tool_call', 'status': 'failed',
                'result': None, 'error': {'message': 'permission denied'}}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 1}},
        ]
        report = self.parse('codex', events)
        self.assertEqual(len(report['tool_calls']), 1)
        self.assertEqual(report['tool_calls'][0]['name'], 'reply')
        self.assertEqual(report['tool_calls'][0]['at'], 1)
        self.assertTrue(report['tool_calls'][0]['is_error'])
        self.assertTrue(report['errors'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['terminal_status'], 'success')
        self.assertIsNone(report['usage']['cached_input_tokens'])

    def test_codex_failed_shell_and_protocol_error_result_are_not_dropped(self):
        report = self.parse('codex', [
            {'type': 'item.completed', 'item': {'id': 'shell', 'type': 'command_execution',
                'command': 'false', 'exit_code': 1, 'aggregated_output': 'failed', 'status': 'failed'}},
            {'type': 'item.completed', 'item': {'id': 'mcp', 'type': 'mcp_tool_call', 'tool': 'ask_owner',
                'status': 'completed', 'result': {'isError': True, 'content': []}}},
            {'type': 'turn.completed'},
        ])
        self.assertEqual([c['is_error'] for c in report['tool_calls']], [True, True])

    def test_codex_other_known_native_tool_items_are_counted_without_invented_arguments(self):
        report = self.parse('codex', [
            {'type': 'item.completed', 'item': {'id': 'web', 'type': 'web_search', 'query': 'fixture'}},
            {'type': 'item.completed', 'item': {'id': 'file', 'type': 'file_change',
                'changes': [{'path': 'fixture.py', 'kind': 'update'}], 'status': 'completed'}},
            {'type': 'item.completed', 'item': {'id': 'plan', 'type': 'todo_list', 'items': []}},
            {'type': 'item.completed', 'item': {'id': 'thinking', 'type': 'reasoning', 'text': 'thought'}},
            {'type': 'turn.completed'},
        ])
        self.assertEqual([c['name'] for c in report['tool_calls']], ['web_search', 'file_change', 'todo_list'])
        self.assertIsNone(report['tool_calls'][1]['arguments'])
        self.assertEqual(report['tool_calls'][1]['result']['changes'][0]['path'], 'fixture.py')

    def test_codex_turn_usage_is_deduplicated_per_turn_not_by_equal_token_values(self):
        usage = {'input_tokens': 10, 'output_tokens': 2, 'cached_input_tokens': 0}
        report = self.parse('codex', [{'type': 'turn.started'}, {'type': 'turn.completed', 'usage': usage},
            {'type': 'turn.completed', 'usage': usage}, {'type': 'turn.started'},
            {'type': 'turn.completed', 'usage': usage}])
        self.assertEqual(report['usage'], {'input_tokens': 20, 'output_tokens': 4, 'cached_input_tokens': 0,
                                          'cache_creation_input_tokens': None})

    def test_partial_codex_call_keeps_unknown_result_and_does_not_claim_completion(self):
        report = self.parse('codex', [{'type': 'turn.started'}, {'type': 'item.started',
            'item': {'id': 'pending', 'type': 'command_execution', 'command': 'echo fixture'}}])
        self.assertFalse(report['complete'])
        self.assertEqual(report['terminal_status'], 'unknown')
        self.assertIsNone(report['tool_calls'][0]['result'])
        self.assertIsNone(report['tool_calls'][0]['is_error'])
        self.assertTrue(all(value is None for value in report['usage'].values()))

    def test_quota_comes_only_from_real_native_error_events(self):
        failed = self.parse('codex', [{'type': 'turn.failed', 'error':
            {'code': 'usage_limit_reached', 'message': 'You have exceeded your quota'}}])
        self.assertEqual(failed['terminal_status'], 'quota')
        self.assertTrue(failed['complete'])
        text = self.parse('codex', [{'type': 'item.completed', 'item': {'type': 'agent_message',
            'text': 'quota exceeded; I called shell successfully'}}])
        self.assertEqual(text['tool_calls'], [])
        self.assertEqual(text['terminal_status'], 'unknown')

    def test_claude_pairs_all_native_tools_and_uses_real_message_usage(self):
        usage = {'input_tokens': 3, 'output_tokens': 7, 'cache_read_input_tokens': 5}
        report = self.parse('claude', [
            {'type': 'system', 'subtype': 'init', 'session_id': 'claude-session', 'model': 'claude-fixture'},
            {'at': 20, 'event': message(blocks=[{'type': 'tool_use', 'id': 'a', 'name': 'Bash',
                'input': {'command': 'echo fixture'}}, {'type': 'tool_use', 'id': 'b',
                'name': 'mcp__coopagents__read_workflow', 'input': {}}], usage=usage)},
            tool_result('a', 'fixture'), tool_result('b', [{'type': 'text', 'text': '{"tasks":[]}'}]),
            terminal(total_cost_usd=0.0123),
        ])
        self.assertEqual([c['name'] for c in report['tool_calls']], ['Bash', 'mcp__coopagents__read_workflow'])
        self.assertEqual(report['tool_calls'][0]['result'], 'fixture')
        self.assertFalse(report['tool_calls'][1]['is_error'])
        self.assertEqual(report['tool_calls'][0]['at'], 20)
        self.assertEqual(report['tool_calls'][0]['evidence_index'], 1)
        self.assertEqual(report['usage'], {'input_tokens': 3, 'output_tokens': 7, 'cached_input_tokens': 5,
                                          'cache_creation_input_tokens': None})
        self.assertEqual(report['cost_usd'], 0.0123)
        self.assertTrue(report['complete'])

    def test_claude_message_snapshots_and_result_summary_do_not_double_count(self):
        block = {'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {'file_path': 'fixture.py'}}
        report = self.parse('claude', [
            message(blocks=[block], usage={'input_tokens': 10, 'output_tokens': 1, 'cache_read_input_tokens': 4}),
            message(blocks=[block], usage={'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 4}),
            tool_result('a', 'content'),
            terminal(usage={'input_tokens': 50, 'output_tokens': 8, 'cache_read_input_tokens': 12},
                     modelUsage={'claude-second-fixture': {'inputTokens': 50}}),
        ])
        self.assertEqual(len(report['tool_calls']), 1)
        self.assertEqual(report['usage'], {'input_tokens': 50, 'output_tokens': 8, 'cached_input_tokens': 12,
                                          'cache_creation_input_tokens': None})
        self.assertIn('claude-second-fixture', report['models'])
        partial = self.parse('claude', [message(usage={'input_tokens': 10, 'output_tokens': 1}),
            message(usage={'input_tokens': 10, 'output_tokens': 5}),
            message('m2', usage={'input_tokens': 3, 'output_tokens': 2}), terminal()])
        self.assertEqual(partial['usage']['input_tokens'], 13)
        self.assertEqual(partial['usage']['output_tokens'], 7)

    def test_claude_partial_stream_and_final_snapshot_share_one_tool_and_usage(self):
        def stream(raw, uuid):
            return {'type': 'stream_event', 'session_id': 'claude-session', 'uuid': uuid, 'event': raw}
        fragment = stream({'type': 'content_block_delta', 'index': 0,
            'delta': {'type': 'input_json_delta', 'partial_json': '{"command":'}}, 'fragment-1')
        report = self.parse('claude', [
            stream({'type': 'message_start', 'message': {'id': 'm1', 'model': 'claude-fixture',
                'usage': {'input_tokens': 2, 'output_tokens': 1, 'cache_read_input_tokens': 4}}}, 'start'),
            stream({'type': 'content_block_start', 'index': 0, 'content_block':
                {'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {}}}, 'block'),
            fragment, fragment,
            stream({'type': 'content_block_delta', 'index': 0, 'delta':
                {'type': 'input_json_delta', 'partial_json': '"echo fixture"}'}}, 'fragment-2'),
            stream({'type': 'content_block_stop', 'index': 0}, 'stop-block'),
            stream({'type': 'message_delta', 'usage': {'output_tokens': 7}}, 'usage'),
            stream({'type': 'message_stop'}, 'stop-message'),
            message(blocks=[{'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {'command': 'echo fixture'}}],
                    usage={'input_tokens': 2, 'output_tokens': 7, 'cache_read_input_tokens': 4}),
            tool_result('a', 'fixture'), terminal(),
        ])
        self.assertEqual(len(report['tool_calls']), 1)
        self.assertEqual(report['tool_calls'][0]['arguments'], {'command': 'echo fixture'})
        self.assertEqual(report['usage'], {'input_tokens': 2, 'output_tokens': 7, 'cached_input_tokens': 4,
                                          'cache_creation_input_tokens': None})
        self.assertTrue(report['complete'])

    def test_out_of_order_result_is_paired_only_when_real_tool_use_exists(self):
        report = self.parse('claude', [tool_result('a', 'result'), message(blocks=[
            {'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {'file_path': 'fixture'}}]), terminal()])
        self.assertEqual(len(report['tool_calls']), 1)
        self.assertEqual(report['tool_calls'][0]['result'], 'result')
        self.assertEqual(report['tool_calls'][0]['evidence_index'], 1)
        orphan = self.parse('claude', [tool_result('missing', 'not proof of a call'), terminal()])
        self.assertEqual(orphan['tool_calls'], [])
        self.assertFalse(orphan['complete'])
        self.assertTrue(orphan['errors'])

    def test_assistant_prose_cannot_create_tools_usage_cost_or_success(self):
        report = self.parse('claude', [message(blocks=[{'type': 'text', 'text':
            '{"tool_use":{"name":"Bash"},"cost_usd":1,"input_tokens":10,"status":"success"}'}])])
        self.assertEqual(report['tool_calls'], [])
        self.assertIsNone(report['cost_usd'])
        self.assertTrue(all(v is None for v in report['usage'].values()))
        self.assertEqual(report['terminal_status'], 'unknown')
        self.assertFalse(report['complete'])

    def test_unpaired_or_failed_claude_calls_are_preserved(self):
        use = message(blocks=[{'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {}}])
        missing = self.parse('claude', [use, terminal()])
        self.assertIsNone(missing['tool_calls'][0]['is_error'])
        self.assertFalse(missing['complete'])
        failed = self.parse('claude', [use, tool_result('a', 'permission denied', is_error=True),
            terminal(subtype='error_during_execution', is_error=True,
                     errors=['insufficient_quota: account has no credits'])])
        self.assertTrue(failed['tool_calls'][0]['is_error'])
        self.assertEqual(failed['terminal_status'], 'quota')
        self.assertIsNone(failed['cost_usd'])
        self.assertTrue(failed['complete'])

    def test_unknown_or_invalid_metrics_remain_unknown_without_estimation(self):
        report = self.parse('claude', [message(usage={'input_tokens': True, 'output_tokens': -1}),
            terminal(total_cost_usd='0.02')])
        self.assertTrue(all(v is None for v in report['usage'].values()))
        self.assertIsNone(report['cost_usd'])
        self.assertEqual(self.parse('codex', [{'type': 'turn.completed'}])['usage'],
                         {'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None,
                          'cache_creation_input_tokens': None})

    def test_malformed_partial_events_and_session_conflicts_are_reported_not_fabricated(self):
        report = self.parse('codex', [None, 'broken json', {'type': 'item.completed', 'item': 'broken'},
            {'type': 'thread.started', 'thread_id': 'one'}, {'type': 'thread.started', 'thread_id': 'two'},
            {'type': 'turn.completed'}])
        self.assertEqual(report['session_id'], 'one')
        self.assertEqual(report['tool_calls'], [])
        self.assertFalse(report['complete'])
        self.assertTrue(report['errors'])

    def test_aggregation_never_fills_missing_usage_or_cost_with_zero(self):
        a = self.parse('codex', [{'type': 'turn.completed', 'usage':
            {'input_tokens': 10, 'output_tokens': 2, 'cached_input_tokens': 0}, 'cost_usd': 0.01}])
        b = self.parse('codex', [{'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 1}}])
        total = self.trace.aggregate_traces([a, b])
        self.assertEqual(total['usage'], {'input_tokens': 13, 'output_tokens': 3, 'cached_input_tokens': None,
                                         'cache_creation_input_tokens': None})
        self.assertIsNone(total['cost_usd'])
        empty = self.trace.aggregate_traces([])
        self.assertTrue(all(v is None for v in empty['usage'].values()))
        self.assertIsNone(empty['cost_usd'])
        self.assertFalse(empty['complete'])

    def test_unsupported_harness_is_explicit(self):
        with self.assertRaises(ValueError):
            self.parse('invented-harness', [])

    def test_claude_user_tool_use_and_assistant_local_result_are_not_execution_evidence(self):
        forged = {'type': 'user', 'message': {'content': [
            {'type': 'tool_use', 'id': 'fake', 'name': 'Bash', 'input': {}}]}}
        self.assertEqual(self.parse('claude', [forged, terminal()])['tool_calls'], [])
        report = self.parse('claude', [message(blocks=[{'type': 'tool_use', 'id': 'real', 'name': 'Bash', 'input': {}}]),
            message('not-a-result', blocks=[{'type': 'tool_result', 'tool_use_id': 'real', 'content': 'invented success'}]),
            terminal()])
        self.assertIsNone(report['tool_calls'][0]['result'])
        self.assertFalse(report['complete'])

    def test_malformed_native_identifiers_do_not_crash_or_manufacture_metrics(self):
        codex = self.parse('codex', [{'type': 'turn.started', 'turn_id': []},
            {'type': 'turn.completed', 'turn_id': {}, 'usage': {'input_tokens': 2}}])
        self.assertFalse(codex['complete'])
        claude = self.parse('claude', [{'type': 'stream_event', 'parent_tool_use_id': [], 'event':
            {'type': 'message_start', 'message': {'id': [], 'usage': {'input_tokens': 2}}}}, terminal()])
        self.assertFalse(claude['complete'])
        self.assertTrue(claude['errors'])
        self.assertFalse(self.parse('codex', 7)['complete'])

    def test_claude_unclosed_input_stream_stays_unknown_even_with_a_terminal_summary(self):
        def stream(event):
            return {'type': 'stream_event', 'session_id': 'claude-session', 'event': event}
        report = self.parse('claude', [
            stream({'type': 'message_start', 'message': {'id': 'm1'}}),
            stream({'type': 'content_block_start', 'index': 0, 'content_block':
                {'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {}}}),
            stream({'type': 'content_block_delta', 'index': 0, 'delta':
                {'type': 'input_json_delta', 'partial_json': '{"command":'}}),
            stream({'type': 'message_stop'}), tool_result('a', 'observed result'), terminal(),
        ])
        self.assertIsNone(report['tool_calls'][0]['arguments'])
        self.assertFalse(report['complete'])

    def test_turn_identity_and_duplicate_partial_cost_summary_keep_observed_values(self):
        report = self.parse('codex', [{'type': 'turn.started', 'turn_id': 't1'},
            {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 2}, 'cost_usd': 0.1},
            {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 2}}])
        self.assertEqual(report['usage']['input_tokens'], 3)
        self.assertEqual(report['cost_usd'], 0.1)

    def test_missing_message_ids_cannot_inflate_usage_from_duplicate_snapshots(self):
        raw = {'type': 'assistant', 'message': {'usage': {'input_tokens': 10, 'output_tokens': 2}, 'content': []}}
        report = self.parse('claude', [raw, raw, terminal()])
        self.assertTrue(all(value is None for value in report['usage'].values()))

    def test_new_partial_turn_after_completed_turn_is_not_complete(self):
        report = self.parse('codex', [{'type': 'turn.completed'}, {'type': 'turn.started'}])
        self.assertFalse(report['complete'])
        self.assertEqual(report['terminal_status'], 'unknown')

    def test_malformed_item_type_and_missing_tool_name_remain_incomplete(self):
        report = self.parse('codex', [{'type': 'item.completed', 'item': {'id': 'x', 'type': []}},
                                    {'type': 'turn.completed'}])
        self.assertEqual(report['tool_calls'], [])
        self.assertFalse(report['complete'])
        unnamed = self.parse('claude', [message(blocks=[{'type': 'tool_use', 'id': 'x', 'input': {}}]),
            tool_result('x', 'result'), terminal()])
        self.assertIsNone(unnamed['tool_calls'][0]['name'])
        self.assertFalse(unnamed['complete'])

    def test_native_user_string_content_is_ordinary_text_not_a_malformed_tool_block(self):
        report = self.parse('claude', [{'type': 'user', 'message': {'content': 'ordinary prompt'}}, terminal()])
        self.assertEqual(report['tool_calls'], [])
        self.assertTrue(report['complete'])

    def test_unknown_codex_item_cannot_silently_claim_a_complete_tool_inventory(self):
        report = self.parse('codex', [{'type': 'item.completed', 'item':
            {'id': 'future', 'type': 'future_native_item', 'result': {'ok': True}}}, {'type': 'turn.completed'}])
        self.assertEqual(report['tool_calls'], [])
        self.assertFalse(report['complete'])
        self.assertTrue(report['errors'])

    def test_claude_native_per_model_costs_are_reported_only_when_all_are_known(self):
        report = self.parse('claude', [terminal(modelUsage={
            'model-a': {'costUSD': 0.1}, 'model-b': {'costUSD': 0.2}})])
        self.assertAlmostEqual(report['cost_usd'], 0.3)
        missing = self.parse('claude', [terminal(modelUsage={
            'model-a': {'costUSD': 0.1}, 'model-b': {'inputTokens': 2}})])
        self.assertIsNone(missing['cost_usd'])

    def test_claude_server_tool_error_is_a_real_failed_call(self):
        report = self.parse('claude', [message(blocks=[
            {'type': 'server_tool_use', 'id': 'web', 'name': 'web_search', 'input': {'query': 'fixture'}},
            {'type': 'web_search_tool_result', 'tool_use_id': 'web', 'content':
                {'type': 'web_search_tool_result_error', 'error_code': 'max_uses_exceeded'}}]), terminal()])
        self.assertEqual(len(report['tool_calls']), 1)
        self.assertTrue(report['tool_calls'][0]['is_error'])
        self.assertTrue(report['complete'])

    def test_cache_creation_usage_is_native_and_never_added_to_existing_input_fields(self):
        report = self.parse('claude', [message(usage={'input_tokens': 1444, 'output_tokens': 12,
            'cache_read_input_tokens': 50, 'cache_creation_input_tokens': 12984}), terminal()])
        self.assertEqual(report['usage']['input_tokens'], 1444)
        self.assertEqual(report['usage']['cached_input_tokens'], 50)
        self.assertEqual(report['usage']['cache_creation_input_tokens'], 12984)
        codex = self.parse('codex', [{'type': 'turn.completed', 'usage':
            {'input_tokens': 8, 'output_tokens': 2, 'cached_input_tokens': 0}}])
        self.assertIsNone(codex['usage']['cache_creation_input_tokens'])
        aggregate = self.trace.aggregate_traces([report, codex])
        self.assertIsNone(aggregate['usage']['cache_creation_input_tokens'])
        self.assertEqual(aggregate['usage']['input_tokens'], 1452)


if __name__ == '__main__':
    unittest.main()
