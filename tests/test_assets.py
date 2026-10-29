import hashlib
import unittest
from pathlib import Path
from uuid import uuid4

from coopagents.assets import AssetStore
from coopagents.errors import AccessDenied, NotFound, ValidationError
from coopagents.identity import IdentityStore


class AssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.local/test-evidence') / ('assets-' + str(uuid4()))
        self.root.mkdir(parents=True)
        self.database = self.root / 'coopagents.sqlite3'
        self.blobs = self.root / 'blobs'
        self.identity = IdentityStore(self.database)
        self.owner = self.identity.create_room('Project A', 'Alice')
        self.member = self.identity.add_member(self.owner['web_token'], 'Bob')
        self.other = self.identity.create_room('Project B', 'Carol')
        self.assets = AssetStore(self.identity, self.blobs, max_file_bytes=32, max_project_bytes=48)

    def test_explicit_upload_is_hashed_project_scoped_and_persistent(self):
        content = b'architecture decision'
        asset = self.assets.upload(self.member['agent_token'], 'decision.md', 'text/markdown', content)

        self.assertEqual(asset['room_id'], self.owner['room_id'])
        self.assertEqual(asset['filename'], 'decision.md')
        self.assertEqual(asset['size_bytes'], len(content))
        self.assertEqual(asset['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual([row['id'] for row in self.assets.list_assets(self.owner['web_token'])], [asset['id']])
        self.assertEqual(self.assets.read_asset(self.owner['agent_token'], asset['id'])[1], content)
        self.assertEqual(AssetStore(IdentityStore(self.database), self.blobs).read_asset(
            self.member['web_token'], asset['id'])[1], content)

    def test_asset_is_invisible_across_projects_and_after_member_revocation(self):
        asset = self.assets.upload(self.owner['web_token'], 'notes.txt', 'text/plain', b'private')

        with self.assertRaises(NotFound):
            self.assets.read_asset(self.other['web_token'], asset['id'])
        self.identity.revoke_member(self.owner['web_token'], self.member['member_id'])
        with self.assertRaises(AccessDenied):
            self.assets.list_assets(self.member['agent_token'])

    def test_upload_enforces_file_and_project_limits(self):
        self.assets.upload(self.owner['web_token'], 'first.txt', 'text/plain', b'a' * 30)
        with self.assertRaises(ValidationError):
            self.assets.upload(self.owner['web_token'], 'too-big.txt', 'text/plain', b'a' * 33)
        with self.assertRaises(ValidationError):
            self.assets.upload(self.owner['web_token'], 'second.txt', 'text/plain', b'b' * 19)
        self.assertEqual(len(self.assets.list_assets(self.owner['web_token'])), 1)

    def test_upload_rejects_path_names_and_unsupported_content(self):
        for filename, media_type in (('../secret.txt', 'text/plain'), ('safe.txt', 'text/html')):
            with self.subTest(filename=filename, media_type=media_type):
                with self.assertRaises(ValidationError):
                    self.assets.upload(self.owner['web_token'], filename, media_type, b'x')

    def test_download_detects_missing_or_modified_content(self):
        asset = self.assets.upload(self.owner['web_token'], 'notes.txt', 'text/plain', b'original')
        blob = next(self.blobs.glob('*.blob'))
        blob.write_bytes(b'modified')

        with self.assertRaises(ValidationError):
            self.assets.read_asset(self.owner['web_token'], asset['id'])
        blob.write_bytes(b'original')

    def test_upload_rejects_malformed_metadata_types(self):
        for filename, media_type, content, source_type, source_ref in (
            ('notes.txt', [], b'x', 'upload', ''),
            ('notes.txt', 'text/plain', bytearray(b'x'), 'upload', ''),
            ('notes.txt', 'text/plain', b'x', [], ''),
        ):
            with self.subTest(filename=filename, media_type=media_type, source_type=source_type):
                with self.assertRaises(ValidationError):
                    self.assets.upload(self.owner['web_token'], filename, media_type, content,
                                       source_type=source_type, source_ref=source_ref)


if __name__ == '__main__':
    unittest.main()
