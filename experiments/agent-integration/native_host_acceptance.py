"""Real Codex owner lifecycle check after a synthetic cold-start run.

No configuration/credential output, file removal or sandbox policy changes.
Uses only the specified isolated run's native configuration and owned runtime.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import cold_start_acceptance as cold
from coopagents import space_runtime as runtime
from coopagents.onboarding_doctor import profile_checks
from coopagents.spaces import private_directory, private_write, read_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    run = args.run.resolve()
    allowed = (cold.REPO / '.local/cold-start-acceptance').resolve()
    if not run.is_relative_to(allowed) or run == allowed:
        parser.error('Use a retained synthetic cold-start run in this checkout')
    report = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
    if report.get('host') != 'codex':
        parser.error('The run must belong to a synthetic Codex owner')
    native = run / 'codex'
    evidence = private_directory(run / ('host-lifecycle-' + uuid4().hex[:8]))
    real_home = Path.home()
    env = cold.prepare_homes(evidence / 'provider',
                             Path(os.environ.get('CODEX_HOME') or real_home / '.codex'),
                             real_home / '.claude/settings.json', tool='codex')
    for key, folder in (('HOME', 'home'), ('USERPROFILE', 'home'), ('CODEX_HOME', 'codex-home'),
                        ('COOPAGENTS_HOME', 'coopagents-home'), ('TMP', 'tmp'), ('TEMP', 'tmp')):
        env[key] = str(native / folder)
    entry = cold.registrations(env, 'codex', native / 'repo')
    profile_path = Path(entry['profile'])
    if not profile_path.resolve().is_relative_to(native / 'coopagents-home'):
        parser.error('The registered profile must belong to this synthetic run')
    profile = read_profile(profile_path)
    original = profile_path.read_bytes()
    checks = []

    def check(name, ok):
        checks.append({'check': name, 'ok': bool(ok)})
        private_write(evidence / 'summary.json', {'checks': checks}, update=(evidence / 'summary.json').exists())
        print(name + ': ' + ('PASS' if ok else 'FAIL'), flush=True)
        if not ok:
            raise RuntimeError('Native lifecycle acceptance failed; inspect private evidence')

    def session(stage, expect_live):
        target = evidence / (stage + '.jsonl')
        prompt = ('Use only the registered native Coopagents MCP tools. Call whoami then read_team. '
                  'Do not run commands, change files, or enable wake-up. If the connection is explicitly '
                  'stopped, report that fact and stop; do not recover it yourself.')
        doctor_ok = False
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(cold.bounded,
                                   cold.model_command('codex', args.codex, native, Path(sys.executable),
                                                      require=('whoami', 'read_team')),
                                   prompt, target, env, native / 'repo', args.timeout)
            while not pending.done():
                if expect_live and not doctor_ok and runtime.status(profile_path)['status'] == 'running':
                    live_checks = profile_checks(profile_path)['checks']
                    doctor_ok = all(next(c for c in live_checks if c['id'] == name)['status'] == 'pass'
                                    for name in ('runtime_reachability', 'challenge_round_trip'))
                time.sleep(.2)
            code = pending.result()
        events = cold.events_from(target)
        tools = cold.successful_tools('codex', events)
        if expect_live:
            check(stage + ' native identity and team', code == 0 and {'whoami', 'read_team'} <= tools
                  and cold.native_identity_proven('codex', events, profile))
            check(stage + ' independent doctor while native session is open', doctor_ok)
        else:
            check(stage + ' has no successful native access', code == 0 and not tools)

    try:
        # Deliberate loss after an explicit start, distinct from user stop intent.
        if runtime.status(profile_path)['status'] != 'running':
            runtime.start(profile_path)
        runtime.request(profile['control_origin'], '/stop', token=profile['control_token'], data={})
        deadline = time.monotonic() + 20
        while not runtime.runtime_unlocked(profile_path) and time.monotonic() < deadline:
            time.sleep(.1)
        check('host lost without pausing native recovery', runtime.status(profile_path)['status'] == 'unreachable')
        session('01-recover', True)
        check('recovery preserves private profile', profile_path.read_bytes() == original)
        runtime.stop(profile_path)
        session('02-stopped', False)
        check('new native session cannot resurrect explicit stop', runtime.runtime_unlocked(profile_path)
              and runtime.status(profile_path)['status'] == 'unreachable')
        runtime.start(profile_path)
        session('03-explicit-resume', True)
        check('explicit resume preserves identity', profile_path.read_bytes() == original)
    finally:
        runtime.stop(profile_path)
        print('Owned synthetic runtime stopped; retained evidence: ' + str(evidence), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
