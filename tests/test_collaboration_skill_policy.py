"""Lifecycle wording stays aligned without running or installing native tools."""
from pathlib import Path
import unittest

from coopagents.collaboration_policy import POLICY_VERSION


ROOT = Path(__file__).resolve().parents[1]
GUIDES = ('src/skills/coopagents-connect/SKILL.md', 'src/skills/coopagents-connect/protocol.md',
          'src/skills/coopagents-space/SKILL.md', 'src/skills/coopagents-space/protocol.md')


class CollaborationSkillPolicyTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding='utf-8')

    def test_both_skills_and_protocols_follow_one_versioned_four_phase_policy(self):
        for path in GUIDES:
            with self.subTest(path=path):
                text = self.read(path)
                self.assertIn(POLICY_VERSION, text)
                self.assertIn('policy_for_event', text)
                for phase in ('startup', 'blocker', 'reply', 'completion'):
                    self.assertIn('`' + phase + '`', text)
                self.assertIn('Hooks never create read receipts or approvals.', text)

    def test_protocols_preserve_checkpoint_brief_and_explain_structured_policy_fields(self):
        for path in GUIDES:
            if not path.endswith('protocol.md'):
                continue
            with self.subTest(path=path):
                text = self.read(path)
                for field in ('checkpoint', 'brief', 'policy', 'policy.version', 'policy.phase',
                              'policy.required_actions', 'policy.instructions'):
                    self.assertIn('`' + field + '`', text)
                self.assertIn('PostToolUseFailure', text)
                self.assertIn('Stop', text)
                self.assertIn('not a new MCP operation', text)

    def test_read_and_human_authority_boundaries_remain_explicit(self):
        for path in GUIDES:
            with self.subTest(path=path):
                text = self.read(path)
                self.assertIn('read_replies', text)
                self.assertIn('human', text.lower())
                self.assertIn('model comprehension', text)
                self.assertIn('local trusted', text)

    def test_matrix_distinguishes_generated_event_support_from_native_acceptance(self):
        text = self.read('docs/harness-adapters-0.9.md')
        self.assertIn('Lifecycle checkpoint coverage (code contracts)', text)
        rows = {line.split('|')[1].strip(): line for line in text.splitlines()
                if line.startswith('| ') and line.count('|') >= 4}
        self.assertIn('PostToolUseFailure', rows['Claude Code'])
        self.assertIn('systemMessage', rows['Claude Code'])
        self.assertIn('Stop', rows['Codex CLI / desktop'])
        self.assertIn('systemMessage', rows['Codex CLI / desktop'])
        self.assertNotIn('PostToolUseFailure', rows['Codex CLI / desktop'])
        self.assertIn('PostToolUseFailure', rows['ZCode'])
        self.assertIn('returns `{}`', rows['ZCode'])
        self.assertIn('no checkpoint stop', rows['Cursor'])
        self.assertIn('no checkpoint Stop', rows['Kimi Code'])
        self.assertIn('session.idle', rows['OpenCode V1 / V2'])
        self.assertIn('agent_end', rows['Pi'])
        self.assertIn('No native reply hook is invented.', text)
        self.assertIn('do not establish native acceptance', text)

    def test_evaluation_guide_does_not_relabel_controlled_runs_as_policy_validation(self):
        text = self.read('docs/workflow-evaluation.md')
        shared = text.split('## Shared agent policy', 1)[1]
        for phase in ('startup', 'blocker', 'reply', 'completion'):
            self.assertIn('`' + phase + '`', shared)
        self.assertIn('policy_for_event', shared)
        self.assertIn('local trusted', shared)
        self.assertIn('does not certify the production initialization policy or hooks', text)
        self.assertIn('No new native validation was performed for this lifecycle update.', shared)


if __name__ == '__main__':
    unittest.main()
