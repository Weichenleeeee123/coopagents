import json
import unittest

from transport_support import LiveService


class AssetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    def multipart(self, filename='guide.md', media_type='text/markdown', content=b'asset body', extra=''):
        boundary = 'coopagents-test-boundary'
        chunks = [
            ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + filename + '"\r\nContent-Type: ' + media_type + '\r\n\r\n').encode(),
            content,
            ('\r\n--' + boundary + '--\r\n').encode(),
        ]
        return b''.join(chunks), {'Content-Type': 'multipart/form-data; boundary=' + boundary}

    def test_explicit_upload_list_download_and_hash_headers(self):
        body, headers = self.multipart(content=b'# shared decision\n')
        status, uploaded, _ = self.live.request('POST', '/api/assets', self.member['agent_token'],
                                                 headers=headers, raw=body, parse_json=True)

        self.assertEqual(status, 201, uploaded)
        self.assertEqual(uploaded['filename'], 'guide.md')
        self.assertEqual(uploaded['source_type'], 'upload')
        status, listing, _ = self.live.request('GET', '/api/assets', self.owner['web_token'])
        self.assertEqual(status, 200)
        self.assertEqual([row['id'] for row in listing['assets']], [uploaded['id']])
        status, content, response_headers = self.live.request('GET', '/api/assets/' + uploaded['id'],
            self.owner['agent_token'], parse_json=False)
        self.assertEqual(status, 200)
        self.assertEqual(content, b'# shared decision\n')
        self.assertEqual(response_headers['X-Content-SHA256'], uploaded['sha256'])
        self.assertEqual(response_headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('attachment', response_headers['Content-Disposition'])

    def test_asset_routes_enforce_auth_project_membership_and_upload_limits(self):
        other = self.live.request('POST', '/api/rooms', data={'name': 'Other', 'owner_name': 'Other'})[1]
        body, headers = self.multipart()
        status, uploaded, _ = self.live.request('POST', '/api/assets', self.owner['web_token'],
                                                 headers=headers, raw=body)
        self.assertEqual(status, 201, uploaded)
        asset_id = uploaded['id']
        self.assertEqual(self.live.request('GET', '/api/assets/' + asset_id, other['web_token'], parse_json=False)[0], 404)
        self.assertEqual(self.live.request('GET', '/api/assets', None)[0], 401)
        self.assertEqual(self.live.request('POST', '/api/assets', self.owner['web_token'],
            headers={'Content-Type': 'application/json'}, raw=b'{}')[0], 400)

    def test_oversized_upload_is_rejected_before_storage(self):
        body, headers = self.multipart(content=b'x' * (10 * 1024 * 1024 + 1))
        status, result, _ = self.live.request('POST', '/api/assets', self.owner['web_token'],
                                               headers=headers, raw=body)
        self.assertEqual(status, 413, result)
        self.assertEqual(self.live.request('GET', '/api/assets', self.owner['web_token'])[1]['assets'], [])


if __name__ == '__main__':
    unittest.main()
