import base64
import json
from pathlib import Path
import unittest

from coopagents import invite_message
from coopagents.invite_message import InvitationCodeError


DESCRIPTOR = dict(schema_version=1, origin='http://127.0.0.1:8765', room_id='room-1',
                  invite_token='SECRET-token_value', expires_at='2026-10-15T12:00:00+00:00')
P2P = DESCRIPTOR | {'p2p': {'endpoint_id': 'a' * 64}}


class Codes(unittest.TestCase):
    def test_round_trip_keeps_only_descriptor_fields(self):
        noisy = P2P | {'web_token': 'never', 'extra': 1}
        code = invite_message.encode(noisy)
        self.assertTrue(code.startswith(invite_message.CODE_PREFIX))
        self.assertNotIn('never', base64.urlsafe_b64decode(code.split('.', 1)[1] + '==').decode())
        self.assertEqual(invite_message.decode(code), P2P)
        self.assertEqual(invite_message.decode(invite_message.encode(DESCRIPTOR)), DESCRIPTOR)

    def test_finds_the_code_inside_a_whole_pasted_message(self):
        for lang in ('en', 'zh'):
            with self.subTest(lang=lang):
                message = invite_message.compose(P2P, 'Alice', 'Hack', lang)
                self.assertEqual(invite_message.decode(message), P2P)
                self.assertEqual(invite_message.decode('\r\n  ' + message + '\n\n'), P2P)

    def test_codes_made_before_the_rename_still_decode(self):
        legacy = invite_message.encode(P2P).replace(invite_message.CODE_PREFIX, 'crewmesh-invite-1.')
        self.assertEqual(invite_message.decode('Join me:\n' + legacy + '\n'), P2P)

    def test_same_code_pasted_twice_is_accepted_but_two_codes_are_not(self):
        code = invite_message.encode(DESCRIPTOR)
        self.assertEqual(invite_message.decode(code + '\n' + code), DESCRIPTOR)
        other = invite_message.encode(DESCRIPTOR | {'room_id': 'room-2'})
        with self.assertRaises(InvitationCodeError):
            invite_message.decode(code + '\n' + other)

    def test_rejects_missing_truncated_and_malformed_codes(self):
        code = invite_message.encode(DESCRIPTOR)
        wrap = lambda data: invite_message.CODE_PREFIX + base64.urlsafe_b64encode(
            json.dumps(data).encode()).decode().rstrip('=')
        bad = ['', 'hello', None, 'x' * (70 * 1024), code[:len(invite_message.CODE_PREFIX) + 10],
               invite_message.CODE_PREFIX + 'A' * 5000,
               wrap([1, 2]), wrap(DESCRIPTOR | {'schema_version': 2}),
               wrap({k: v for k, v in DESCRIPTOR.items() if k != 'invite_token'}),
               wrap(DESCRIPTOR | {'origin': ''}), wrap(DESCRIPTOR | {'room_id': 5}),
               wrap(DESCRIPTOR | {'p2p': 'endpoint'}), wrap(DESCRIPTOR | {'control_token': 'x'})]
        for value in bad:
            with self.subTest(value=str(value)[:40]), self.assertRaises(InvitationCodeError):
                invite_message.decode(value)

    def test_error_messages_never_echo_the_input(self):
        secret = invite_message.CODE_PREFIX + 'SECRETSECRET'
        with self.assertRaises(InvitationCodeError) as raised:
            invite_message.decode(secret)
        self.assertNotIn('SECRET', str(raised.exception))


class InvitationSources(unittest.TestCase):
    def setUp(self):
        import uuid
        self.directory = (Path('.local/invite-source-tests') / uuid.uuid4().hex).resolve()
        self.directory.mkdir(parents=True)

    def write(self, name, text):
        path = self.directory / name
        path.write_bytes(text.encode('utf-8'))
        return path

    def test_file_with_whole_message_code_or_descriptor(self):
        message = invite_message.compose(P2P, 'Alice', 'Hack', 'zh')
        self.assertEqual(invite_message.load_invitation_file(self.write('message.txt', message)), P2P)
        self.assertEqual(invite_message.load_invitation_file(self.write('code.txt', invite_message.encode(P2P))), P2P)
        self.assertEqual(invite_message.load_invitation_file(self.write('invite.json', json.dumps(P2P))), P2P)

    def test_bad_files_get_fixed_reasons(self):
        for name, text in (('empty.txt', ''), ('noise.txt', 'hello'), ('old.json', json.dumps(P2P | {'schema_version': 2}))):
            with self.subTest(name=name), self.assertRaises(InvitationCodeError):
                invite_message.load_invitation_file(self.write(name, text))
        with self.assertRaises(InvitationCodeError):
            invite_message.load_invitation_file(self.write('huge.txt', 'x' * (70 * 1024)))

    def test_stdin_that_never_closes_fails_fast(self):
        import io, os, sys, threading, time
        from unittest.mock import patch
        read_end, write_end = os.pipe()
        stream = io.TextIOWrapper(io.BufferedReader(io.FileIO(read_end, 'rb')))
        started = time.monotonic()
        try:
            with patch.object(sys, 'stdin', stream), self.assertRaises(InvitationCodeError) as raised:
                invite_message.read_stdin(wait=0.5)
        finally:
            os.close(write_end)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn('--invitation-file', str(raised.exception))


class Messages(unittest.TestCase):
    def test_message_has_pitch_skill_prompt_code_and_warning(self):
        message = invite_message.compose(P2P, 'Alice', 'Hack night', 'en')
        lines = message.splitlines()
        self.assertEqual(lines[0], 'Alice invited you to the Coopagents space "Hack night".')
        self.assertIn(invite_message.PROJECT_URL, lines)
        self.assertIn(invite_message.skill_url(invite_message.installed_version()), message)
        self.assertIn('--invitation-file <that file>', message)
        self.assertIn('--connect codex', message)
        self.assertIn('Never put the code in a command argument', message)
        self.assertIn('read its Coopagents skill', message)
        self.assertNotIn('set up its', message)
        self.assertIn(invite_message.encode(P2P), lines)
        self.assertIn('works once', message)
        self.assertNotIn('only agents on that computer', message)
        first, second = [i for i, line in enumerate(lines) if line == '----------']
        self.assertTrue(first < lines.index(invite_message.encode(P2P)) < second)

    def test_invitee_installs_the_inviters_exact_version_from_pypi(self):
        for lang in ('en', 'zh'):
            with self.subTest(lang=lang):
                message = invite_message.compose(P2P, 'A', 'B', lang, version='0.7.0rc1')
                self.assertIn('pip install "coopagents[space]==0.7.0rc1"', message)
                self.assertIn(invite_message.PROJECT_URL + '/tree/v0.7.0rc1/src/skills/coopagents-space', message)
                self.assertIn('--index-url https://pypi.org/simple', message)
                self.assertNotIn('latest release', message)
                self.assertNotIn('/tree/main/', message)

    def test_unknown_version_falls_back_to_newest_pre_release(self):
        message = invite_message.compose(P2P, 'A', 'B', 'en', version=None)
        self.assertIn('pip install --pre "coopagents[space]"', message)
        self.assertIn('/tree/main/src/skills/coopagents-space', message)

    def test_default_version_is_the_installed_package(self):
        version = invite_message.installed_version()
        self.assertTrue(version)
        self.assertIn(f'coopagents[space]=={version}', invite_message.compose(P2P, 'A', 'B', 'en'))

    def test_chinese_message_and_local_only_note(self):
        message = invite_message.compose(DESCRIPTOR, '围城', '黑客松', 'zh')
        self.assertTrue(message.startswith('围城 邀请你加入 Coopagents 空间「黑客松」。'))
        self.assertIn('只有那台电脑上的 agent 能加入', message)
        self.assertIn('只能用一次', message)
        self.assertTrue(invite_message.local_only(DESCRIPTOR))
        self.assertFalse(invite_message.local_only(P2P))
        self.assertFalse(invite_message.local_only(DESCRIPTOR | {'origin': 'https://space.example.com'}))

    def test_expiry_is_shown_in_local_time_with_offset(self):
        message = invite_message.compose(P2P, 'A', 'B', 'en')
        self.assertRegex(message, r'expires at 2026-10-1[45] \d\d:\d\d \(UTC[+-]\d\d:\d\d\)')

    def test_unknown_language_is_refused(self):
        with self.assertRaises(ValueError):
            invite_message.compose(P2P, 'A', 'B', 'fr')


if __name__ == '__main__':
    unittest.main()
