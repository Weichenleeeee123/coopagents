import base64
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents import invite_message, p2p
from coopagents import space_runtime as runtime
from coopagents.spaces import read_json


RELAY = 'https://relay.example.com'
LOOPBACK = 'http://127.0.0.1:3340'


def descriptor(**overrides):
    token = base64.urlsafe_b64encode(b'\x01' * 32).decode().rstrip('=')
    data = dict(schema_version=1, origin='http://127.0.0.1:8765',
                room_id='48ee6bc1-ba4d-4c9f-ad97-fd38688c8669',
                invite_token=token, expires_at='2026-10-28T12:00:00+00:00')
    data.update(overrides)
    return data


class ValidateRelayUrls(unittest.TestCase):
    def test_accepts_https_loopback_http_and_ports(self):
        self.assertEqual(p2p.validate_relay_urls([RELAY]), [RELAY])
        self.assertEqual(p2p.validate_relay_urls(['https://relay.example.com:3443', LOOPBACK]),
                         ['https://relay.example.com:3443', LOOPBACK])
        self.assertEqual(p2p.validate_relay_urls(('https://a.example',)), ['https://a.example'])
        self.assertEqual(p2p.validate_relay_urls(['http://localhost:3340', 'http://[::1]:3340']),
                         ['http://localhost:3340', 'http://[::1]:3340'])

    def test_rejects_plain_http_off_loopback(self):
        for url in ['http://relay.example.com', 'http://192.168.1.1:3340', 'http://[2001:db8::1]:3340']:
            with self.assertRaises(ValueError, msg=url):
                p2p.validate_relay_urls([url])

    def test_rejects_malformed_urls(self):
        bad = ['', 'relay.example.com', 'ftp://relay.example.com', 'https://user@relay.example.com',
               'https://relay.example.com/?x=1', 'https://relay.example.com/#f',
               'https://relay.example.com/derp', 'https://', 'https://relay.example.com/pa th',
               'https://' + 'a' * 2050 + '.example']
        for url in bad:
            with self.assertRaises(ValueError, msg=url):
                p2p.validate_relay_urls([url])

    def test_rejects_wrong_shapes(self):
        for value in [None, RELAY, [], ['https://a.example'] * 5, [None], [123]]:
            with self.assertRaises(ValueError, msg=repr(value)):
                p2p.validate_relay_urls(value)


class ValidateLink(unittest.TestCase):
    def test_plain_link_unchanged(self):
        self.assertEqual(p2p.validate_link({'endpoint_id': 'a' * 64}), {'endpoint_id': 'a' * 64})

    def test_link_with_relay_urls(self):
        link = p2p.validate_link({'endpoint_id': 'a' * 64, 'relay_urls': [RELAY, LOOPBACK]})
        self.assertEqual(link, {'endpoint_id': 'a' * 64, 'relay_urls': [RELAY, LOOPBACK]})

    def test_rejects_unknown_keys_and_bad_relays(self):
        with self.assertRaises(ValueError):
            p2p.validate_link({'endpoint_id': 'a' * 64, 'other': 1})
        with self.assertRaises(ValueError):
            p2p.validate_link({'endpoint_id': 'a' * 64, 'relay_urls': ['http://relay.example.com']})
        with self.assertRaises(ValueError):
            p2p.validate_link({'relay_urls': [RELAY]})


class FakeRelayMode:
    def __init__(self, record):
        self.record = record

    def custom_from_urls(self, urls):
        self.record['relay_mode_urls'] = list(urls)
        return 'relay-mode'


class FakeIroh:
    def __init__(self):
        self.record = {}
        self.RelayMode = FakeRelayMode(self.record)

    def preset_n0(self):
        return 'preset-n0'

    def preset_minimal(self):
        return 'preset-minimal'

    def EndpointOptions(self, **kwargs):
        self.record['options'] = kwargs
        return 'endpoint-options'


class OptionsWiring(unittest.TestCase):
    def options(self, **kwargs):
        fake = FakeIroh()
        with patch.object(p2p, '_iroh', return_value=fake):
            result = p2p._options(secret='00' * 32, **kwargs)
        self.assertEqual(result, 'endpoint-options')
        return fake.record

    def test_default_uses_n0_preset_without_relay_mode(self):
        record = self.options()
        self.assertEqual(record['options']['preset'], 'preset-n0')
        self.assertNotIn('relay_mode', record['options'])
        self.assertNotIn('relay_mode_urls', record)

    def test_local_only_uses_minimal_preset(self):
        record = self.options(local_only=True)
        self.assertEqual(record['options']['preset'], 'preset-minimal')

    def test_relay_urls_use_custom_mode(self):
        record = self.options(relay_urls=[RELAY, LOOPBACK])
        self.assertEqual(record['options']['preset'], 'preset-n0')
        self.assertEqual(record['options']['relay_mode'], 'relay-mode')
        self.assertEqual(record['relay_mode_urls'], [RELAY, LOOPBACK])

    def test_relay_urls_conflict_with_local_only(self):
        with self.assertRaises(ValueError):
            self.options(local_only=True, relay_urls=[RELAY])

    def test_invalid_relay_urls_rejected(self):
        with self.assertRaises(ValueError):
            self.options(relay_urls=['http://relay.example.com'])


class MemberLinkRelayUrls(unittest.TestCase):
    def link_with(self, profile, fake):
        with patch.object(p2p, 'MemberLink', fake):
            with p2p.member_link(profile):
                pass

    def test_relay_urls_reach_member_link(self):
        seen = {}

        class FakeLink:
            def __init__(self, endpoint_id, port, **kwargs):
                seen.update(endpoint_id=endpoint_id, port=port, kwargs=kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        profile = {'origin': 'http://127.0.0.1:8765', 'room_id': 'room',
                   'p2p': {'endpoint_id': 'a' * 64, 'relay_urls': [RELAY]}}
        self.link_with(profile, FakeLink)
        self.assertEqual(seen['kwargs'], {'relay_urls': [RELAY]})

    def test_plain_link_constructs_member_link_without_relay_kwarg(self):
        seen = {}

        class StrictLink:
            def __init__(self, endpoint_id, port):
                seen.update(endpoint_id=endpoint_id, port=port)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        profile = {'origin': 'http://127.0.0.1:8765', 'room_id': 'room',
                   'p2p': {'endpoint_id': 'a' * 64}}
        self.link_with(profile, StrictLink)
        self.assertEqual(seen, {'endpoint_id': 'a' * 64, 'port': 8765})


class InviteCodec(unittest.TestCase):
    def test_relay_descriptor_uses_version_1_code_and_round_trips(self):
        data = descriptor(p2p={'endpoint_id': 'a' * 64, 'relay_urls': [RELAY]})
        code = invite_message.encode(data)
        self.assertTrue(code.startswith(invite_message.CODE_PREFIX))
        self.assertEqual(invite_message.decode(code), data)

    def test_plain_p2p_descriptor_still_compacts(self):
        data = descriptor(p2p={'endpoint_id': 'a' * 64})
        code = invite_message.encode(data)
        self.assertTrue(code.startswith(invite_message.CODE_PREFIX_2))
        self.assertEqual(invite_message.decode(code), data)


class RuntimeRelayUrls(unittest.TestCase):
    def setUp(self):
        self.directory = Path('.local/runtime-tests') / uuid4().hex
        self.directory.mkdir(parents=True)

    def test_create_rejects_relay_urls_off_p2p(self):
        with self.assertRaises(ValueError):
            runtime.create('Test', 'Owner', self.directory, network='local', relay_urls=[RELAY])
        self.assertFalse((self.directory / 'space.sqlite3').exists())
        self.assertFalse((self.directory / 'profile.json').exists())
        self.assertFalse((self.directory / 'host.json').exists())

    def test_create_stores_relay_urls_in_host_file(self):
        with patch.object(runtime, 'start', return_value={'status': 'started'}) as started:
            runtime.create('Test', 'Owner', self.directory, relay_urls=[RELAY, LOOPBACK])
        started.assert_called_once()
        host = read_json(self.directory / 'host.json')
        self.assertEqual(host['relay_urls'], [RELAY, LOOPBACK])

    def test_create_without_relay_urls_stores_none(self):
        with patch.object(runtime, 'start', return_value={'status': 'started'}):
            runtime.create('Test', 'Owner', self.directory)
        host = read_json(self.directory / 'host.json')
        self.assertNotIn('relay_urls', host)

    def test_space_link_carries_relay_urls(self):
        secret = p2p.new_secret()
        host = dict(schema_version=1, network='p2p', local_origin='http://127.0.0.1:1',
                    cloudflared=None, p2p_secret=secret, relay_urls=[RELAY])
        (self.directory / 'host.json').write_text(json.dumps(host))
        link = runtime.space_link(self.directory / 'profile.json', {'control_token': 'x'})
        self.assertEqual(link, {'endpoint_id': p2p.endpoint_id(secret), 'relay_urls': [RELAY]})

    def test_space_link_without_relay_urls_is_plain(self):
        secret = p2p.new_secret()
        host = dict(schema_version=1, network='p2p', local_origin='http://127.0.0.1:1',
                    cloudflared=None, p2p_secret=secret)
        (self.directory / 'host.json').write_text(json.dumps(host))
        link = runtime.space_link(self.directory / 'profile.json', {'control_token': 'x'})
        self.assertEqual(link, {'endpoint_id': p2p.endpoint_id(secret)})

    def test_space_link_rejects_invalid_relay_urls_in_host_file(self):
        secret = p2p.new_secret()
        host = dict(schema_version=1, network='p2p', local_origin='http://127.0.0.1:1',
                    cloudflared=None, p2p_secret=secret, relay_urls=['http://relay.example.com'])
        (self.directory / 'host.json').write_text(json.dumps(host))
        with self.assertRaises(ValueError):
            runtime.space_link(self.directory / 'profile.json', {'control_token': 'x'})

    def test_member_link_passes_through_unchanged(self):
        link = {'endpoint_id': 'a' * 64, 'relay_urls': [RELAY]}
        self.assertEqual(runtime.space_link(self.directory / 'profile.json', {'p2p': link}), link)


if __name__ == '__main__':
    unittest.main()
