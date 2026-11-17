"""Release inputs retain the doctor CLI and ship the maintained setup guide."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tomllib
import unittest

from coopagents import onboarding_doctor, space_runtime


class OnboardingPackageTests(unittest.TestCase):
    def test_setuptools_includes_doctor_module_and_setup_guides(self):
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / 'pyproject.toml').read_text())['tool']['setuptools']
        self.assertEqual(config['packages'], ['coopagents'])
        self.assertEqual(config['package-dir']['coopagents'], 'src')
        self.assertEqual(Path(onboarding_doctor.__file__).name, 'onboarding_doctor.py')
        for name in ('agent-first-setup.md', 'agent-first-setup.zh-CN.md'):
            self.assertIn('docs/' + name, config['data-files']['share/coopagents'])
            self.assertTrue((root / 'docs' / name).is_file())

    def test_runtime_exposes_doctor_without_native_configuration(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            space_runtime.main(['doctor', '--help'])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn('--profile', output.getvalue())

    def test_skill_contains_essential_commands_and_one_version_rule(self):
        root = Path(__file__).resolve().parents[1]
        rule = ('Use the exact version named in the invitation or requested by the user; '
                'otherwise use the newest stable release on PyPI. '
                'Use a pre-release only when the invitation or user explicitly names it.')
        for name in ('README.md', 'src/skills/coopagents-space/SKILL.md',
                     'src/skills/coopagents-space/protocol.md'):
            with self.subTest(name=name):
                text = (root / name).read_text()
                self.assertIn(rule, text)
                self.assertNotIn('including pre-releases', text)
        skill = (root / 'src/skills/coopagents-space/SKILL.md').read_text()
        for command in ('create', 'join', 'connect', 'status', 'doctor'):
            self.assertIn('<python> -m coopagents.space_runtime ' + command + ' ', skill)


if __name__ == '__main__':
    unittest.main()
