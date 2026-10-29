"""Unattended real-agent acceptance of the README's solo flow (steps 1-4) against the committed source.

    python solo_acceptance.py [--repeat N] [--steps 1234] [--codex-model gpt-6-luna] [--root D:/coop-e2e]

The harness builds a wheel from `git archive HEAD` with a unique dev version and offers it to pip through
PIP_FIND_LINKS, so the README and invitation prompts run unchanged apart from the version and the Skill link
(the message's GitHub link is replaced by the local source Skill, because the dev tag does not exist on GitHub).

Claude Code runs with an isolated CLAUDE_CONFIG_DIR. Its credentials come from the `env` block of
~/.claude/settings.json and are passed to the child process in memory only, so nothing is written to the
user's Claude configuration and no personal CLAUDE.md applies. Codex needs its real home for authentication:
the harness removes the MCP entries it added (those whose profile lies in the run folder) with
`codex mcp remove` at the end; the Codex skill folder is updated by `connect` with a dated backup, as for a user.
Every check reads state (configuration, hooks, the space's own records), never only what an agent says.
Step 4 drives an interactive, idle Claude Code session in a pseudo terminal and needs `pywinpty`. That session
runs in the default permission mode with only the Coopagents MCP server allowed.

Nothing is deleted. Each run keeps its folder with transcripts and a summary.json.
"""
import argparse
import base64
import functools
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import tomllib

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / 'src' / 'skills' / 'coopagents-space'
CODE = re.compile(r'coopagents-invite-(?:1\.[A-Za-z0-9_-]+|2\.[0-9ABCDEFGHJKMNPQRSTVWXYZ-]+)', re.I)
ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[@-_]')

def readme_step1(version, skill):
    """README step 1 exactly as published, with the version under test and the local Skill."""
    text = (REPO / 'README.md').read_text(encoding='utf-8')
    after = text[text.index('**1. In Claude Code**'):]
    prompt = next(line[2:] for line in after.splitlines() if line.startswith('> '))
    current = re.search(r'Install Coopagents (\S+) from PyPI', prompt).group(1)
    prompt = prompt.replace(current, version)
    return re.sub(r'https://github\.com/Weichenleeeee123/coopagents/tree/[^/\s]+/src/skills/coopagents-space', skill, prompt)


STEP2 = '{message}\n\nJoin as "Codex".'
STEP3 = 'Turn on Coopagents wake-up for this repo.'
STEP4 = "Ask Claude through Coopagents which command runs this repo's tests, then wait for the answer."


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


# ---------- tools and environment ----------

@functools.cache
def find_claude():
    for path in [os.environ.get('COOPAGENTS_E2E_CLAUDE'),
                 *glob.glob(os.path.expandvars(r'%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe')),
                 str(Path.home() / '.local' / 'bin' / 'claude.exe'), shutil.which('claude.exe')]:
        if path and Path(path).is_file():
            return path
    raise SystemExit('Claude Code executable not found; set COOPAGENTS_E2E_CLAUDE')


@functools.cache
def find_codex():
    # WindowsApps cannot be listed, so ask Windows where the desktop app is installed.
    found = []
    try:
        location = subprocess.run(['powershell', '-NoProfile', '-Command',
                                   '(Get-AppxPackage -Name OpenAI.Codex).InstallLocation'],
                                  capture_output=True, text=True, timeout=60).stdout.strip()
        found = [str(Path(location) / 'app' / 'resources' / 'codex.exe')] if location else []
    except (OSError, subprocess.TimeoutExpired):
        pass
    for path in [os.environ.get('COOPAGENTS_E2E_CODEX'), *found, shutil.which('codex')]:
        if path and Path(path).is_file():
            return path
    raise SystemExit('Codex executable not found; set COOPAGENTS_E2E_CODEX')


def base_env(run):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE', 'CODEX_THREAD', 'COOPAGENTS'))}
    env.update(COOPAGENTS_HOME=str(run / 'coopagents-home'), PIP_FIND_LINKS=str(run.parents[1] / 'dist'),
               PYTHONUTF8='1')
    return env


def claude_env(run):
    env = base_env(run)
    settings = json.loads((Path.home() / '.claude' / 'settings.json').read_text(encoding='utf-8'))
    env.update({k: str(v) for k, v in (settings.get('env') or {}).items()})
    env['CLAUDE_CONFIG_DIR'] = str(run / 'claude-home')
    return env


def seed_claude_home(run, folders):
    home = run / 'claude-home'
    home.mkdir(parents=True, exist_ok=True)
    # Only this run's own test folders are marked trusted.
    document = {'hasCompletedOnboarding': True, 'theme': 'dark',
                'projects': {str(f).replace('\\', '/'): {'hasTrustDialogAccepted': True} for f in folders}}
    (home / '.claude.json').write_text(json.dumps(document), encoding='utf-8')


def make_repo(path):
    (path / 'tests').mkdir(parents=True)
    (path / 'calc.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    (path / 'tests' / 'test_calc.py').write_text(
        'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n', encoding='utf-8')
    (path / 'README.md').write_text('# calc\n\nRun the tests with `python -m pytest -q`.\n', encoding='utf-8')
    git = ['git', '-c', 'user.name=e2e', '-c', 'user.email=e2e@example.invalid']
    subprocess.run(['git', 'init', '-q'], cwd=path, check=True)
    subprocess.run(git + ['add', '-A'], cwd=path, check=True)
    subprocess.run(git + ['commit', '-qm', 'init'], cwd=path, check=True)


def build_wheel(root):
    """A wheel of HEAD with a unique dev version that no index has, so pip must take it from find-links."""
    head = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    if subprocess.run(['git', 'status', '--porcelain', '--', 'src', 'pyproject.toml'], cwd=REPO,
                      capture_output=True, text=True).stdout.strip():
        log('warning: uncommitted changes in src/ or pyproject.toml are not part of the tested wheel')
    source = root / ('source-' + head)
    if not source.exists():
        archive = root / ('source-' + head + '.tar')
        subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), 'HEAD'], cwd=REPO, check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(source, filter='data')
    pyproject = source / 'pyproject.toml'
    # Always start from the committed file: the extracted source is reused and was rewritten before.
    text = subprocess.run(['git', 'show', 'HEAD:pyproject.toml'], cwd=REPO, capture_output=True, text=True,
                          encoding='utf-8', check=True).stdout
    base = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    version = '%s.dev%s' % (base.split('rc')[0], time.strftime('%Y%m%d%H%M%S'))
    pyproject.write_text(re.sub(r'^version = "[^"]+"', 'version = "%s"' % version, text, count=1, flags=re.M),
                         encoding='utf-8')
    dist = root / 'dist'
    dist.mkdir(exist_ok=True)
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '-q', '-w', str(dist), str(source)], check=True)
    return version, head


# ---------- agents ----------

def bounded(command, path, timeout, **options):
    """Run with output in a file and kill the whole process tree on timeout.

    With pipes, a grandchild (pip, a bridge) keeps the harness waiting long after the deadline."""
    with open(path, 'wb') as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, **options)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)], capture_output=True)
            process.wait(timeout=30)
            return 'timeout'


def claude_model_args(model):
    return ['--model', model] if model else []


def run_claude(run, name, prompt, cwd, model, timeout=1500):
    started = time.time()
    path = run / (name + '.json')
    code = bounded([find_claude(), *claude_model_args(model), '-p', prompt, '--permission-mode', 'bypassPermissions',
                    '--output-format', 'json'],
                   path, timeout, cwd=cwd, env=claude_env(run), stdin=subprocess.DEVNULL)
    output = path.read_text(encoding='utf-8', errors='replace')
    try:
        text = json.loads(output).get('result') or ''
    except ValueError:
        text = output
    return {'exit': code, 'seconds': round(time.time() - started), 'text': text}


def run_codex(run, name, prompt, cwd, model, timeout=1500):
    started = time.time()
    last = run / (name + '-last.txt')
    prompt_file = run / (name + '-prompt.txt')
    prompt_file.write_text(prompt, encoding='utf-8')
    with open(prompt_file, 'rb') as stdin:
        code = bounded([find_codex(), 'exec', '-m', model, '--dangerously-bypass-approvals-and-sandbox',
                        '--skip-git-repo-check', '-o', str(last), '-'], run / (name + '.log'), timeout,
                       cwd=cwd, env=base_env(run), stdin=stdin)
    text = last.read_text(encoding='utf-8', errors='replace') if last.exists() else ''
    return {'exit': code, 'seconds': round(time.time() - started), 'text': text}


class IdleClaude:
    """An interactive Claude Code session left idle in a pseudo terminal, as a user would leave it."""
    def __init__(self, run, cwd, server, model):
        from winpty import PtyProcess
        self.screen = []
        self.process = PtyProcess.spawn([find_claude(), *claude_model_args(model), '--allowedTools', 'mcp__' + server],
                                        cwd=str(cwd),
                                        env=claude_env(run), dimensions=(40, 160))
        threading.Thread(target=self._pump, daemon=True).start()
        self.path = run / 'step4-claude-screen.txt'

    def _pump(self):
        while True:
            try:
                self.screen.append(self.process.read(4096))
            except EOFError:
                return

    def text(self):
        return ANSI.sub('', ''.join(self.screen))

    def close(self):
        self.path.write_text(self.text(), encoding='utf-8')
        if self.process.isalive():
            self.process.terminate(force=True)


# ---------- state checks ----------

def bridges(entries):
    found = []
    for name, server in (entries or {}).items():
        args = [str(a) for a in (server.get('args') or [])] if isinstance(server, dict) else []
        if args[:2] == ['-m', 'coopagents.space_bridge'] and '--profile' in args:
            found.append({'server': name, 'python': server.get('command'),
                          'profile': args[args.index('--profile') + 1]})
    return found


def claude_bridges(run):
    document = json.loads((run / 'claude-home' / '.claude.json').read_text(encoding='utf-8'))
    groups = [document.get('mcpServers')] + [p.get('mcpServers') for p in (document.get('projects') or {}).values()
                                             if isinstance(p, dict)]
    return [b for group in groups for b in bridges(group)]


def codex_bridges(run):
    path = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
    servers = tomllib.loads(path.read_text(encoding='utf-8')).get('mcp_servers') or {}
    inside = str(run).lower()
    return [b for b in bridges(servers) if str(Path(b['profile']).resolve()).lower().startswith(inside)]


def space(python, profile):
    """Members and requests as the host records them (owner's web credential, read in the child only)."""
    code = ('import json,sys;from coopagents.spaces import read_profile;from coopagents.space_runtime import request;'
            'p=read_profile(sys.argv[1]);s=request(p["origin"],"/api/snapshot",token=p["web_token"]);'
            'print(json.dumps({"members":s.get("members"),"requests":s.get("requests")}))')
    result = subprocess.run([python, '-c', code, profile], capture_output=True, text=True, timeout=60, cwd=neutral(python))
    return json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr[-500:]}


def neutral(python):
    """A working folder without a source checkout, whose egg-info would shadow the installed package."""
    return str(Path(python).parent)


def installed_version(python):
    """The version and whether it lives in its own virtual environment (not a global or user-site install)."""
    code = ('import importlib.metadata as m,sys,coopagents;'
            'print(m.version("coopagents"), sys.prefix != sys.base_prefix, coopagents.__file__)')
    result = subprocess.run([python, '-c', code], capture_output=True, text=True, timeout=60, cwd=neutral(python))
    parts = result.stdout.split(' ', 2)
    if len(parts) != 3:
        return {'error': result.stderr[-300:]}
    return {'version': parts[0], 'venv': parts[1] == 'True', 'path': parts[2].strip()}


def wake_status(python, profile):
    result = subprocess.run([python, '-m', 'coopagents.space_wake', 'status', '--profile', profile],
                            capture_output=True, text=True, timeout=60, cwd=neutral(python))
    return json.loads(result.stdout) if result.returncode == 0 else {}


def hooks_from_config(document):
    installed = []
    for event, groups in (document.get('hooks') or {}).items():
        commands = [str(hook.get('command', '')) for group in groups if isinstance(group, dict)
                    for hook in group.get('hooks', []) if isinstance(hook, dict)]
        scripts = []
        for command in commands:
            encoded = re.search(r'(?:^|\s)-EncodedCommand\s+([A-Za-z0-9+/=]+)(?:\s|$)', command, re.I)
            if not encoded:
                scripts.append(command)
                continue
            try:
                scripts.append(base64.b64decode(encoded.group(1), validate=True).decode('utf-16-le'))
            except (ValueError, UnicodeDecodeError):
                scripts.append('')
        if any('coopagents.space_wake' in script and ' watch ' in script for script in scripts):
            installed.append(event)
    return sorted(installed)


def hooks(path):
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return hooks_from_config(document)


def names(members):
    return sorted(m.get('display_name') for m in members or [])


def invitation(text, skill):
    """What a user pastes: the whole message, or the part between its two divider lines (as the message says)."""
    match = CODE.search(text or '')
    if not match:
        return None
    lines = text.splitlines()
    at = next(i for i, l in enumerate(lines) if match.group(0) in l)
    first = next((i for i, l in enumerate(lines) if 'invited you to the Coopagents space' in l), None)
    last = next((i for i, l in enumerate(lines) if 'This invitation works once' in l), None)
    above = [i for i in range(at) if lines[i].strip().strip('`').strip() == '----------']
    below = [i for i in range(at + 1, len(lines)) if lines[i].strip().strip('`').strip() == '----------']
    if first is not None and last is not None and first < at < last:
        message = '\n'.join(lines[first:last + 1])
    elif above and below:
        message = '\n'.join(lines[above[-1] + 1:below[0]])
    else:
        return None  # a bare code is not what the user would paste
    # The dev tag is not on GitHub; point at the same Skill in the tested source.
    return re.sub(r'https://github\.com/Weichenleeeee123/coopagents/tree/[^/\s]+/src/skills/coopagents-space', skill, message)


# ---------- the flow ----------

def check(report, step, name, ok, detail=None):
    report['checks'].append({'step': step, 'check': name, 'ok': bool(ok), **({'detail': detail} if detail else {})})
    log(('PASS' if ok else 'FAIL'), step, name, '' if ok or detail is None else json.dumps(detail)[:300])
    return bool(ok)


def one_run(root, index, version, args):
    run = root / 'runs' / (time.strftime('%Y%m%d-%H%M%S') + '-%d' % index)
    repo, other = run / 'repo', run / 'other-repo'
    make_repo(repo)
    make_repo(other)
    seed_claude_home(run, [repo, other])
    report = {'run': str(run), 'version': version, 'checks': [], 'agents': {}}
    host = member = None
    idle = None
    try:
        if '1' in args.steps:
            log('step 1: Claude creates, connects with wake-up and invites')
            out = run_claude(run, 'step1-claude', readme_step1(version, SKILL.as_posix()), repo, args.claude_model)
            report['agents']['step1'] = {k: out[k] for k in ('exit', 'seconds')}
            found = claude_bridges(run)
            check(report, 1, 'one Coopagents server registered with Claude Code', len(found) == 1, found)
            if not found:
                return report
            host = found[0]
            installed = installed_version(host['python'])
            check(report, 1, 'installed the requested version in its own virtual environment',
                  installed.get('version') == version and installed.get('venv'), installed)
            skills =sorted(p.name for p in (run / 'claude-home' / 'skills').glob('*coopagents*'))
            check(report, 1, 'skill installed once', skills == ['coopagents-space'], skills)
            check(report, 1, 'wake hooks in the repository', hooks(repo / '.claude' / 'settings.local.json') == ['SessionStart', 'Stop'],
                  hooks(repo / '.claude' / 'settings.local.json'))
            team = space(host['python'], host['profile'])
            check(report, 1, 'member is named Claude', names(team.get('members')) == ['Claude'], team.get('members'))
            report['message'] = message = invitation(out['text'], SKILL.as_posix())
            check(report, 1, 'invitation message returned', message, out['text'][-600:])
            if not message or '2' not in args.steps:
                return report

            log('step 2: Codex joins from the pasted message')
            out = run_codex(run, 'step2-codex', STEP2.format(message=message), repo, args.codex_model)
            report['agents']['step2'] = {k: out[k] for k in ('exit', 'seconds')}
            found = codex_bridges(run)
            check(report, 2, 'one Coopagents server registered with Codex', len(found) == 1, found)
            if found:
                member = found[0]
                installed = installed_version(member['python'])
                check(report, 2, 'installed the inviter\'s version in its own virtual environment',
                      installed.get('version') == version and installed.get('venv'), installed)
            team = space(host['python'], host['profile'])
            check(report, 2, 'members are Claude and Codex', names(team.get('members')) == ['Claude', 'Codex'], team.get('members'))
            check(report, 2, 'Codex state stays outside the repository',
                  member and not str(Path(member['profile']).resolve()).lower().startswith(str(repo).lower()), member)

        if '3' in args.steps and host:
            log('step 3: a new session turns wake-up on by itself')
            out = run_claude(run, 'step3-claude', STEP3, other, args.claude_model)
            report['agents']['step3_claude'] = {k: out[k] for k in ('exit', 'seconds')}
            installed = hooks(other / '.claude' / 'settings.local.json')
            check(report, 3, 'Claude installed hooks in the session folder', installed == ['SessionStart', 'Stop'],
                  {'hooks': installed, 'said': out['text'][-400:]})
            if member:
                out = run_codex(run, 'step3-codex', STEP3, repo, args.codex_model)
                report['agents']['step3_codex'] = {k: out[k] for k in ('exit', 'seconds')}
                installed = hooks(repo / '.codex' / 'hooks.json')
                check(report, 3, 'Codex installed its hook in the session folder', installed == ['Stop'],
                      {'hooks': installed, 'said': out['text'][-400:]})

        if '4' in args.steps and host and member:
            log('step 4: idle Claude is woken by a question from Codex')
            idle = IdleClaude(run, repo, host['server'], args.claude_model)
            deadline = time.time() + 90
            armed = False
            while time.time() < deadline and not armed:
                time.sleep(3)
                armed = any(w['tool'] == 'claude' and w['status'] == 'watching'
                            for w in wake_status(host['python'], host['profile']).get('watchers', []))
            check(report, 4, 'idle Claude session armed its watcher', armed)
            before = len(wake_status(host['python'], host['profile']).get('recent_wakes', []))
            out = run_codex(run, 'step4-codex', STEP4, repo, args.codex_model)
            report['agents']['step4_codex'] = {k: out[k] for k in ('exit', 'seconds')}
            woke = len(wake_status(host['python'], host['profile']).get('recent_wakes', [])) > before
            check(report, 4, 'Claude was woken', woke)
            team = space(host['python'], host['profile'])
            ids = {m['display_name']: m['member_id'] for m in team.get('members') or []}
            asked = [r for r in team.get('requests') or []
                     if r.get('receiver_member_id') == ids.get('Claude') and r.get('sender_member_id') == ids.get('Codex')]
            check(report, 4, 'Codex addressed its request to Claude', asked, team.get('requests'))
            replied = [r for r in asked if r.get('replies')]
            check(report, 4, 'Claude replied without the user', replied)
            check(report, 4, 'Codex got the answer', 'pytest' in out['text'], out['text'][-400:])
        return report
    finally:
        if idle:
            idle.close()
        if host:
            subprocess.run([host['python'], '-I', '-m', 'coopagents.space_runtime', 'stop', '--profile', host['profile']],
                           capture_output=True, timeout=120)
        for entry in codex_bridges(run):
            subprocess.run([find_codex(), 'mcp', 'remove', entry['server']], capture_output=True, timeout=60)
        (run / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='D:/coop-e2e')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--steps', default='1234')
    parser.add_argument('--codex-model', default='gpt-6-luna')
    parser.add_argument('--claude-model', default=None,
                        help='Override the configured Claude model (for example: sonnet5)')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    version, head = build_wheel(root)
    log('testing', head, 'as', version)
    reports = [one_run(root, i + 1, version, args) for i in range(args.repeat)]
    failed = [(r['run'], c['check']) for r in reports for c in r['checks'] if not c['ok']]
    print(json.dumps({'commit': head, 'version': version, 'runs': len(reports),
                      'checks': sum(len(r['checks']) for r in reports), 'failed': failed}, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
