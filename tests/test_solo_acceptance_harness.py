import base64
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'experiments' / 'agent-integration' / 'solo_acceptance.py'
SPEC = importlib.util.spec_from_file_location('solo_acceptance', SCRIPT)
solo_acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(solo_acceptance)


class SoloAcceptanceHarnessTests(unittest.TestCase):
    def test_extracts_v2_invitation_message_from_realistic_claude_output(self):
        message = '\n'.join((
            'Alice invited you to the Coopagents space "Team".',
            '',
            'Paste everything between the two lines into your Claude Code or Codex:',
            '----------',
            'Install Coopagents 0.7.3 from PyPI.',
            'coopagents-invite-2.09G02-071GZ-75SCY-14W94-QPCJP-XFGRW',
            '----------',
            '',
            'This invitation works once and expires soon.',
        ))
        result = solo_acceptance.invitation(message, 'file:///local/skill')
        self.assertIsNotNone(result)
        self.assertIn('coopagents-invite-2.09G02-071GZ-75SCY-14W94-QPCJP-XFGRW', result)
        self.assertIn('Install Coopagents 0.7.3', result)
        self.assertIn('This invitation works once', result)

    def test_detects_hooks_inside_windows_encoded_powershell_command(self):
        script = "& 'C:/Python/python.exe' -I -m coopagents.space_wake watch --tool claude"
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        config = {'hooks': {'Stop': [{'hooks': [{'command':
                  'powershell.exe -NoProfile -EncodedCommand ' + encoded}]}]}}
        self.assertEqual(solo_acceptance.hooks_from_config(config), ['Stop'])


if __name__ == '__main__':
    unittest.main()
