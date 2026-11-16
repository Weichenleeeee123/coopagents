"""Pure local recovery-view checks; no service, native process or connection."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from coopagents.space_bridge import Bridge


class RecoveryViewContractTests(unittest.TestCase):
    def test_transport_observation_time_is_recorded_and_not_invented_by_reading_status(self):
        bridge = Bridge.__new__(Bridge)
        with patch('coopagents.space_bridge.time.time', return_value=1234):
            bridge.status = 'offline'
        self.assertEqual(getattr(bridge, 'status_observed_at', None), 1234)
        with patch('coopagents.space_bridge.time.time', return_value=9999):
            self.assertEqual(bridge.status, 'offline')
        self.assertEqual(bridge.status_observed_at, 1234)

    def test_local_changes_passes_the_stored_observation_to_read_only_diagnostics(self):
        bridge = Bridge.__new__(Bridge)
        bridge.identity = ('room', 'member')
        bridge.profile_path = Path('unused-synthetic-profile.json')
        bridge._local_profile = Mock(return_value={'room_id': 'room', 'member_id': 'member'})
        bridge.cache = SimpleNamespace(read=Mock(return_value={'events': [], 'cursor': 0}))
        with patch('coopagents.space_bridge.time.time', return_value=1234):
            bridge.status = 'offline'
        with patch('coopagents.space_bridge.local_diagnostics', return_value={'diagnostics': []}) as diagnostics:
            result = bridge.local_changes({})
        self.assertEqual(diagnostics.call_args.kwargs.get('observed_at'), 1234)
        self.assertFalse(result['fresh'])
        self.assertFalse(result['authorization_revalidated'])


if __name__ == '__main__':
    unittest.main()
