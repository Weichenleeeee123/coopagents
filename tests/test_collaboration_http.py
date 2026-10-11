import unittest
from transport_support import LiveService


class CollaborationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    def test_authenticated_http_checkpoint_and_strict_inputs(self):
        self.assertTrue('checkpoint' in self.live.app.state.service.operations, 'checkpoint endpoint missing')
        payload = {'session_key': 'native', 'tool': 'claude-code', 'event': 'UserPromptSubmit'}
        status, result, _ = self.live.request('POST', '/api/checkpoints', self.owner['agent_token'], payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['checkpoint']['member_id'], self.owner['member_id'])
        for token in (self.owner['web_token'], 'revoked'):
            self.assertEqual(self.live.request('POST', '/api/checkpoints', token, payload)[0], 401)
        self.assertEqual(self.live.request('POST', '/api/checkpoints', self.owner['agent_token'], dict(payload, prompt='secret'))[0], 400)
        view = self.live.request('GET', '/api/snapshot', self.owner['web_token'])[1]
        self.assertEqual(len(view['collaboration']['checkpoints']), 1)

    def test_real_challenge_exchange_exposed_to_web(self):
        self.assertTrue('diagnostic_start' in self.live.app.state.service.operations, 'diagnostic endpoint missing')
        token = self.owner['agent_token']
        status, start, _ = self.live.request('POST', '/api/diagnostics/start', token, {'challenge': 'native-doctor'})
        self.assertEqual(status, 200, start)
        args = {'diagnostic_id': start['diagnostic_id']}
        read = self.live.request('POST', '/api/diagnostics/read', token, args)[1]
        done = self.live.request('POST', '/api/diagnostics/complete', token, dict(args, proof=read['proof']))[1]
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(self.live.request('GET', '/api/snapshot', self.owner['web_token'])[1]['collaboration']['diagnostics'][0]['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
