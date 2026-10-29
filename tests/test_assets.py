import hashlib
import unittest
import os
from pathlib import Path
import stat
from uuid import uuid4
from unittest.mock import patch

from coopagents.assets import AssetStore, asset_limits_from_env
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

    def test_upload_enforces_total_service_limit(self):
        limited = AssetStore(self.identity, self.blobs, max_file_bytes=32,
                             max_project_bytes=32, max_total_bytes=32)
        limited.upload(self.owner['web_token'], 'first.txt', 'text/plain', b'a' * 20)
        with self.assertRaises(ValidationError):
            limited.upload(self.other['web_token'], 'second.txt', 'text/plain', b'b' * 13)
        self.assertEqual(len(limited.list_assets(self.other['web_token'])), 0)

    def test_retained_unreferenced_blobs_count_toward_service_limit(self):
        (self.blobs / 'retained-partial.blob').write_bytes(b'x' * 15)
        limited = AssetStore(self.identity, self.blobs, max_file_bytes=32,
                             max_project_bytes=32, max_total_bytes=32)
        with self.assertRaises(ValidationError):
            limited.upload(self.owner['web_token'], 'too-much.txt', 'text/plain', b'y' * 18)

    def test_asset_limits_are_positive_integer_environment_settings(self):
        with patch.dict('os.environ', {'COOPAGENTS_ASSET_MAX_FILE_BYTES':'10',
                                       'COOPAGENTS_ASSET_MAX_PROJECT_BYTES':'20',
                                       'COOPAGENTS_ASSET_MAX_TOTAL_BYTES':'30'}, clear=True):
            self.assertEqual(asset_limits_from_env(), {'max_file_bytes':10,'max_project_bytes':20,'max_total_bytes':30})
        with patch.dict('os.environ', {'COOPAGENTS_ASSET_MAX_FILE_BYTES':'0'}, clear=True):
            with self.assertRaises(ValueError):
                asset_limits_from_env()
        with patch.dict('os.environ', {'COOPAGENTS_ASSET_MAX_FILE_BYTES':str(10 * 1024 * 1024 + 1)}, clear=True):
            with self.assertRaises(ValueError):
                asset_limits_from_env()

    @unittest.skipIf(os.name == 'nt', 'Windows does not expose POSIX mode bits')
    def test_asset_storage_is_private_on_posix(self):
        asset = self.assets.upload(self.owner['web_token'], 'private.txt', 'text/plain', b'secret')
        mode = stat.S_IMODE(self.blobs.stat().st_mode)
        blob = next(self.blobs.glob(asset['sha256'][:0] + '*.blob'))
        self.assertEqual(mode & 0o077, 0)
        self.assertEqual(stat.S_IMODE(blob.stat().st_mode) & 0o077, 0)

    def test_upload_rejects_path_names_and_unsupported_content(self):
        for filename, media_type in (('../secret.txt', 'text/plain'), ('safe.txt', 'text/html')):
            with self.subTest(filename=filename, media_type=media_type):
                with self.assertRaises(ValidationError):
                    self.assets.upload(self.owner['web_token'], filename, media_type, b'x')

    def test_repository_source_references_are_explicit_and_relative(self):
        asset = self.assets.upload(self.owner['web_token'], 'guide.md', 'text/markdown', b'asset',
                                   source_type='path', source_ref='docs/guide.md')
        self.assertEqual(asset['source_type'], 'path')
        self.assertEqual(asset['source_ref'], 'docs/guide.md')
        for source_ref in ('', '../secrets.txt', '/etc/passwd', 'C:/Users/alice/private.txt', 'docs\\private.txt'):
            with self.subTest(source_ref=source_ref), self.assertRaises(ValidationError):
                self.assets.upload(self.owner['web_token'], 'other.md', 'text/markdown', b'x',
                                   source_type='path', source_ref=source_ref)

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
