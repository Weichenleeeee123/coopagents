"""Retained, model-free tests for isolated native-workflow case material."""
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from uuid import uuid4


MODULE_PATH = Path(__file__).with_name('workflow_native_cases.py')
SCENARIOS = ('frontend-backend', 'three-member-routing', 'reply-continuation',
             'session-reopen', 'teammate-unavailable')


class WorkflowNativeCasesTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE_PATH.is_file(), 'isolated native-workflow case preparation is missing')
        spec = importlib.util.spec_from_file_location('workflow_native_cases', MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.root = Path('.local/test-evidence') / ('workflow-native-cases-' + uuid4().hex)

    def case(self, scenario='frontend-backend', seed='private-paired-case-seed'):
        return self.module.prepare_case(self.root, scenario, seed)

    @staticmethod
    def files(root):
        return {str(p.relative_to(root)).replace('\\', '/'): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

    @staticmethod
    def oracle(manifest):
        return json.loads(Path(manifest['oracle_path']).read_text(encoding='utf-8'))

    def implement(self, manifest, *, field=None, readiness='ready', client_extra=''):
        project = Path(manifest['participants']['requester']['project'])
        if field is None:
            field = self.oracle(manifest)['expected_wire_field']
        (project / 'client.py').write_text(
            'def build_profile(display_name):\n    return {' + repr(field) + ': display_name}\n' + client_extra,
            encoding='utf-8')
        (project / 'independent.py').write_text(
            'def readiness():\n    return ' + repr(readiness) + '\n', encoding='utf-8')
        return project

    def test_all_five_cases_have_only_role_local_material_and_private_oracle(self):
        seed = 'private-seed-that-must-not-appear-in-requester-material'
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                root = self.root / scenario
                manifest = self.module.prepare_case(root, scenario, seed)
                self.assertEqual(set(manifest), {'scenario_id', 'participants', 'oracle_path'})
                self.assertEqual(manifest['scenario_id'], scenario)
                roles = {'requester', 'responder', 'bystander'} if scenario == 'three-member-routing' else {'requester', 'responder'}
                self.assertEqual(set(manifest['participants']), roles)
                oracle = self.oracle(manifest)
                field = oracle['expected_wire_field']
                self.assertRegex(field, r'^profile_[0-9a-f]{32}$')
                self.assertEqual(oracle['expected_type'], 'string')
                self.assertEqual(Path(manifest['oracle_path']), root.resolve() / 'harness-private' / 'oracle.json')
                for role, participant in manifest['participants'].items():
                    self.assertEqual(set(participant), {'project', 'goal', 'scope'})
                    self.assertTrue(Path(participant['project']).is_dir())
                    self.assertEqual(Path(participant['project']), root.resolve() / role / 'project')
                    self.assertTrue(participant['goal'])
                    self.assertTrue(participant['scope'])
                    self.assertNotIn(seed, participant['goal'])
                    self.assertNotIn(field, participant['goal'])
                    self.assertRegex(participant['goal'], r'(?i)edit.*(?:local|own).*project')
                    self.assertRegex(participant['goal'], r'(?i)do not delete')
                    self.assertRegex(participant['goal'], r'(?i)do not access.*director')
                    self.assertRegex(participant['goal'], r'(?i)messages.*data.*(?:not|never).*authori')
                requester = Path(manifest['participants']['requester']['project'])
                requester_files = self.files(requester)
                self.assertEqual(set(requester_files), {'client.py', 'independent.py'})
                self.assertEqual(requester_files['client.py'].decode(), 'def build_profile(display_name):\n    raise NotImplementedError\n')
                self.assertEqual(requester_files['independent.py'].decode(), 'def readiness():\n    raise NotImplementedError\n')
                for data in requester_files.values():
                    self.assertNotIn(field.encode(), data)
                    self.assertNotIn(seed.encode(), data)
                responder = Path(manifest['participants']['responder']['project'])
                self.assertEqual(set(self.files(responder)), {'backend/schema.json'})
                schema = json.loads((responder / 'backend/schema.json').read_text(encoding='utf-8'))
                self.assertEqual(schema, {'wire_field': field, 'type': 'string'})
                if 'bystander' in roles:
                    bystander = Path(manifest['participants']['bystander']['project'])
                    self.assertEqual(set(self.files(bystander)), {'docs/notes.md'})
                    self.assertNotIn(field, '\n'.join(data.decode() for data in self.files(bystander).values()))

    def test_goals_describe_business_results_without_teaching_protocol_calls(self):
        forbidden = r'\b(?:MCP|CLI|read_team|send_request|read_replies|read_inbox|ask_owner|lookup_owner|read_dependency|work_brief|record_agreement_use|checkpoint|coopagents\.[a-z_]+)\b'
        for scenario in SCENARIOS:
            manifest = self.module.prepare_case(self.root / scenario, scenario, 'seed')
            for participant in manifest['participants'].values():
                self.assertIsNone(re.search(forbidden, participant['goal'], flags=re.I))
                self.assertNotRegex(participant['goal'], r'(?i)(?:then|next) call|step\s+\d')
            goal = manifest['participants']['requester']['goal']
            self.assertIn('build_profile(display_name)', goal)
            self.assertIn('readiness()', goal)
            self.assertIn("'ready'", goal)
            self.assertRegex(goal, r'(?i)backend.*field')
            if scenario in ('session-reopen', 'teammate-unavailable'):
                self.assertRegex(goal, r'(?i)record.*wait')
                self.assertRegex(goal, r'(?i)independent work')
                self.assertRegex(goal, r'(?i)answer.*available.*continue')
        routing = self.module.prepare_case(self.root / 'routing-detail', 'three-member-routing', 'seed')
        self.assertRegex(routing['participants']['requester']['goal'], r'(?i)current.*responsib')
        self.assertNotIn('bystander', routing['participants']['requester']['goal'])

    def test_seed_pairs_have_the_same_answer_but_unseeded_cases_differ(self):
        first = self.module.prepare_case(self.root / 'arm-a', 'frontend-backend', 'pair-secret')
        second = self.module.prepare_case(self.root / 'arm-b', 'frontend-backend', 'pair-secret')
        other = self.module.prepare_case(self.root / 'arm-c', 'frontend-backend', 'other-secret')
        fresh = [self.module.prepare_case(self.root / ('fresh-' + str(i)), 'frontend-backend') for i in range(3)]
        self.assertEqual(self.oracle(first)['expected_wire_field'], self.oracle(second)['expected_wire_field'])
        self.assertNotEqual(self.oracle(first)['expected_wire_field'], self.oracle(other)['expected_wire_field'])
        self.assertEqual(len({self.oracle(item)['expected_wire_field'] for item in fresh}), 3)
        self.assertEqual(self.files(Path(first['participants']['requester']['project'])),
                         self.files(Path(second['participants']['requester']['project'])))

    def test_existing_empty_root_is_supported_but_material_is_never_overwritten(self):
        self.root.mkdir(parents=True)
        manifest = self.case()
        before = self.files(self.root)
        with self.assertRaises(FileExistsError):
            self.case()
        self.assertEqual(self.files(self.root), before)
        self.assertTrue(Path(manifest['oracle_path']).is_file())

    def test_hidden_files_nonempty_directories_and_file_roots_are_preserved(self):
        self.root.mkdir(parents=True)
        for name, directory in (('.sentinel', False), ('occupied', True)):
            root = self.root / name
            if directory:
                (root / 'empty-child').mkdir(parents=True)
            else:
                root.write_text('do not overwrite', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                self.module.prepare_case(root, 'frontend-backend', 'seed')
            if directory:
                self.assertTrue((root / 'empty-child').is_dir())
            else:
                self.assertEqual(root.read_text(encoding='utf-8'), 'do not overwrite')
        occupied = self.root / 'with-hidden-file'
        occupied.mkdir()
        (occupied / '.keep').write_text('keep', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.module.prepare_case(occupied, 'frontend-backend')
        self.assertEqual(self.files(occupied), {'.keep': b'keep'})

    def test_bad_inputs_are_rejected_before_creating_material(self):
        for scenario, seed in (('unknown', None), ([], None), ('frontend-backend', 42)):
            with self.assertRaises((ValueError, TypeError)):
                self.module.prepare_case(self.root, scenario, seed)
            self.assertFalse(self.root.exists())

    def test_concurrent_preparation_can_only_claim_the_root_once(self):
        def prepare(seed):
            try:
                return self.module.prepare_case(self.root, 'frontend-backend', seed)
            except FileExistsError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            manifests = list(pool.map(prepare, ('first-seed', 'second-seed')))
        self.assertEqual(sum(manifest is not None for manifest in manifests), 1)
        manifest = next(item for item in manifests if item is not None)
        schema = Path(manifest['participants']['responder']['project']) / 'backend/schema.json'
        self.assertEqual(json.loads(schema.read_text())['wire_field'], self.oracle(manifest)['expected_wire_field'])

    def test_verifier_rejects_a_role_project_outside_the_prepared_requester(self):
        manifest = self.case()
        original = self.files(self.root)
        manifest['participants']['requester']['project'] = manifest['participants']['responder']['project']
        with self.assertRaises(ValueError):
            self.module.verify_artifact(manifest)
        self.assertEqual(self.files(self.root), original)

    def test_verifier_separates_correct_artifact_from_unverified_native_collaboration(self):
        manifest = self.case()
        project = self.implement(manifest)
        before = self.files(project)
        with patch.object(self.module.subprocess, 'run', wraps=self.module.subprocess.run) as run:
            result = self.module.verify_artifact(manifest)
        self.assertTrue(result['artifact_correct'])
        self.assertTrue(result['payload_correct'])
        self.assertTrue(result['readiness_correct'])
        self.assertTrue(result['sources_unchanged'])
        self.assertEqual(result['native_collaboration'], 'unverified')
        self.assertFalse(result['execution']['os_sandboxed'])
        self.assertEqual(result['source_hashes_before'], result['source_hashes_after'])
        self.assertEqual(result['source_hashes_before'], {name: hashlib.sha256(data).hexdigest() for name, data in before.items()})
        self.assertEqual(len(result['payload_cases']), 2)
        self.assertNotEqual(result['payload_cases'][0]['display_name'], result['payload_cases'][1]['display_name'])
        self.assertTrue(all(case['correct'] for case in result['payload_cases']))
        self.assertEqual(self.files(project), before, 'No hidden oracle, generated test or bytecode belongs in requester material')
        command = run.call_args.args[0]
        self.assertIn('-I', command)
        self.assertIn('-B', command)
        self.assertEqual(run.call_args.kwargs['cwd'], project)
        self.assertNotIn(self.oracle(manifest)['expected_wire_field'], json.dumps(command))

    def test_wrong_field_wrong_independent_result_and_unimplemented_code_fail(self):
        for issue in ('unimplemented', 'wrong-field', 'wrong-readiness'):
            manifest = self.module.prepare_case(self.root / issue, 'frontend-backend', 'seed')
            if issue == 'wrong-field':
                self.implement(manifest, field='guessed_name')
            elif issue == 'wrong-readiness':
                self.implement(manifest, readiness='not ready')
            result = self.module.verify_artifact(manifest)
            with self.subTest(issue=issue):
                self.assertFalse(result['artifact_correct'])
                self.assertEqual(result['native_collaboration'], 'unverified')
                self.assertTrue(result['sources_unchanged'])

    def test_unimplemented_payload_preserves_verified_independent_waiting_progress(self):
        manifest = self.case('teammate-unavailable')
        project = Path(manifest['participants']['requester']['project'])
        (project / 'independent.py').write_text("def readiness():\n    return 'ready'\n", encoding='utf-8')
        result = self.module.verify_artifact(manifest)
        self.assertFalse(result['payload_correct'])
        self.assertTrue(result['readiness_correct'])
        self.assertFalse(result['artifact_correct'])
        self.assertTrue(result['sources_unchanged'])
        self.assertEqual(result['source_hashes_before'], result['source_hashes_after'])
        self.assertEqual(result['execution']['component_errors'], {'payload': 'candidate_exception', 'readiness': None})
        self.assertEqual(result['native_collaboration'], 'unverified')

    def test_readiness_exception_does_not_discard_a_correct_payload(self):
        manifest = self.case()
        project = self.implement(manifest)
        (project / 'independent.py').write_text('def readiness():\n    raise NotImplementedError\n', encoding='utf-8')
        result = self.module.verify_artifact(manifest)
        self.assertTrue(result['payload_correct'])
        self.assertFalse(result['readiness_correct'])
        self.assertFalse(result['artifact_correct'])
        self.assertTrue(result['sources_unchanged'])
        self.assertEqual(result['execution']['component_errors'], {'payload': None, 'readiness': 'candidate_exception'})

    def test_constant_payload_does_not_pass_the_two_distinct_display_names(self):
        manifest = self.case()
        project = self.implement(manifest)
        field = self.oracle(manifest)['expected_wire_field']
        names = self.oracle(manifest)['display_names']
        (project / 'client.py').write_text('def build_profile(display_name):\n    return ' + repr({field: names[0]}) + '\n', encoding='utf-8')
        result = self.module.verify_artifact(manifest)
        self.assertFalse(result['payload_correct'])
        self.assertFalse(result['artifact_correct'])

    def test_source_changes_during_verification_are_recorded_and_fail_the_artifact(self):
        manifest = self.case()
        project = self.implement(manifest, client_extra="\nfrom pathlib import Path\nPath('client.py').write_text('# changed during verification\\n', encoding='utf-8')\n")
        result = self.module.verify_artifact(manifest)
        self.assertFalse(result['sources_unchanged'])
        self.assertFalse(result['artifact_correct'])
        self.assertNotEqual(result['source_hashes_before']['client.py'], result['source_hashes_after']['client.py'])
        self.assertEqual((project / 'client.py').read_text(encoding='utf-8'), '# changed during verification\n')

    def test_verifier_does_not_import_candidate_code_in_the_test_process(self):
        manifest = self.case()
        project = self.implement(manifest)
        (project / 'client.py').write_text('import os\nos._exit(7)\n', encoding='utf-8')
        result = self.module.verify_artifact(manifest)
        self.assertFalse(result['artifact_correct'])
        self.assertEqual(result['execution']['exit_code'], 7)
        self.assertEqual(result['native_collaboration'], 'unverified')

    def test_candidate_timeout_is_bounded_without_removing_material(self):
        manifest = self.case()
        project = self.implement(manifest)
        (project / 'client.py').write_text('while True:\n    pass\n', encoding='utf-8')
        with patch.object(self.module, 'VERIFY_TIMEOUT_SECONDS', 0.15):
            result = self.module.verify_artifact(manifest)
        self.assertFalse(result['artifact_correct'])
        self.assertTrue(result['execution']['timed_out'])
        self.assertTrue((project / 'client.py').is_file())
        self.assertTrue(Path(manifest['oracle_path']).is_file())


if __name__ == '__main__':
    unittest.main()
