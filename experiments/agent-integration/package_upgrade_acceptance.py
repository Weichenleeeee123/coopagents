"""Seed with published 0.9, then verify a separately installed candidate wheel.

All records are synthetic and retained. Run seed/verify with their respective
isolated interpreters; this script never installs packages or removes files.
"""
import argparse
import asyncio
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

from coopagents import space_runtime as runtime
from coopagents.coordination import CoordinationService
from coopagents.spaces import private_directory, private_write, read_json, read_profile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation(profile, name, data, *, web=False):
    return runtime.request(profile['origin'], '/api/operations/' + name,
                           token=profile['web_token' if web else 'agent_token'], data=data)


def seed(root, install_report):
    if metadata.version('coopagents') != '0.9.0':
        raise ValueError('Seed must run with the published 0.9.0 distribution')
    import coopagents
    if not Path(coopagents.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError('The baseline must import from its isolated environment')
    report = json.loads(install_report.read_text(encoding='utf-8'))
    package = next(p for p in report['install'] if p['metadata']['name'] == 'coopagents')
    download = package['download_info']
    origin = urlsplit(download['url'])
    artifact_hash = download['archive_info']['hashes']['sha256']
    if (package['metadata']['version'] != '0.9.0' or origin.scheme != 'https'
            or origin.hostname != 'files.pythonhosted.org' or not artifact_hash
            or metadata.distribution('coopagents').read_text('direct_url.json')):
        raise ValueError('Use the published PyPI 0.9 baseline and retain its pip install report')
    created = runtime.create('Upgrade acceptance', 'Baseline owner', root / 'owner', network='p2p')
    path = Path(created['profile'])
    owner = read_profile(path)
    try:
        invitation = runtime.invite(path)
        joined = runtime.join(invitation['invitation_file'], 'Baseline peer', root / 'peer')
        peer = read_profile(joined['profile'])
        task = operation(owner, 'create_task', dict(intent_key='upgrade-task', title='Retain this task', scope='Synthetic upgrade'), web=True)
        claimed = operation(peer, 'claim_task', dict(task_id=task['id'], session_key='baseline-session'))
        operation(peer, 'register_session', dict(session_key='baseline-session', tool='codex-cli',
                  repository='synthetic', branch='upgrade', task_id=task['id'], ownership_epoch=claimed['ownership_epoch']))
        operation(peer, 'report_progress', dict(task_id=task['id'], state='working', summary='Recorded under published 0.9',
                  session_key='baseline-session', ownership_epoch=claimed['ownership_epoch']))
        request = operation(owner, 'send_request', dict(request_key='upgrade-question', context_version=1,
                            body='Retain the baseline answer', receiver_member_id=peer['member_id']))
        operation(peer, 'read_inbox', {})
        reply = operation(peer, 'reply', dict(request_id=request['id'], request_key='upgrade-reply',
                          context_version=1, body='baseline-answer-preserved'))
        service = CoordinationService(path.with_name('space.sqlite3'))
        asset = service.assets.upload(owner['web_token'], 'baseline.txt', 'text/plain', b'baseline-asset-preserved')
        state = runtime.request(owner['origin'], '/api/snapshot', token=owner['web_token'])
        private_write(root / 'baseline-snapshot.json', state)
        private_write(root / 'baseline-manifest.json', dict(
            schema_version=1, version='0.9.0', baseline_artifact_sha256=artifact_hash,
            room_id=owner['room_id'], owner_member_id=owner['member_id'],
            peer_member_id=peer['member_id'], owner_profile_sha256=digest(path),
            peer_profile_sha256=digest(Path(joined['profile'])), host_sha256=digest(path.with_name('host.json')),
            task_id=task['id'], request_id=request['id'], reply_id=reply['id'], asset_id=asset['id'],
            ownership_epoch=claimed['ownership_epoch']))
    finally:
        runtime.stop(path)
    backup = private_directory(root / 'baseline-backup')
    shutil.copytree(root / 'owner', backup / 'owner')
    shutil.copytree(root / 'peer', backup / 'peer')
    private_write(root / 'baseline-backup-hashes.json', {str(p.relative_to(backup)): digest(p)
                  for p in backup.rglob('*') if p.is_file()})
    print('Published 0.9 synthetic state seeded, stopped and backed up', flush=True)


def verify(root, wheel):
    from cold_start_acceptance import installed_wheel_identity
    identity = installed_wheel_identity(wheel)
    baseline = read_json(root / 'baseline-manifest.json')
    owner_path, peer_path = root / 'owner/profile.json', root / 'peer/profile.json'
    owner, peer = read_profile(owner_path), read_profile(peer_path)
    checks = []

    def check(name, ok):
        checks.append({'check': name, 'ok': bool(ok)})
        print(name + ': ' + ('PASS' if ok else 'FAIL'), flush=True)
        private_write(root / 'upgrade-summary.json', {'distribution': identity, 'checks': checks},
                      update=(root / 'upgrade-summary.json').exists())
        if not ok:
            raise RuntimeError('Upgrade acceptance failed; inspect retained synthetic evidence')

    runtime.start(owner_path)
    try:
        check('original private profiles and P2P host key retained', digest(owner_path) == baseline['owner_profile_sha256']
              and digest(peer_path) == baseline['peer_profile_sha256'] and digest(owner_path.with_name('host.json')) == baseline['host_sha256'])
        for profile in (owner, peer):
            me = runtime.request(profile['origin'], '/api/me', token=profile['agent_token'])['me']
            check('existing personal agent identity accepted: ' + profile['member_id'],
                  (me['room_id'], me['member_id']) == (baseline['room_id'], profile['member_id']))
        state = runtime.request(owner['origin'], '/api/snapshot', token=owner['web_token'])
        task = next(t for t in state['tasks'] if t['id'] == baseline['task_id'])
        check('task ownership and epoch retained', task['owner_member_id'] == baseline['peer_member_id']
              and task['ownership_epoch'] == baseline['ownership_epoch'])
        request = next(r for r in state['requests'] if r['id'] == baseline['request_id'])
        check('original request and reply retained', any(r['id'] == baseline['reply_id']
              and r['body'] == 'baseline-answer-preserved' for r in request['replies']))
        service = CoordinationService(owner_path.with_name('space.sqlite3'))
        asset, content = service.assets.read_asset(owner['web_token'], baseline['asset_id'])
        check('original explicit asset retained', content == b'baseline-asset-preserved')
        report = operation(peer, 'report_progress', dict(task_id=task['id'], state='working', summary='Existing session works after upgrade',
                           session_key='baseline-session', ownership_epoch=baseline['ownership_epoch']))
        check('existing claimed session can continue without rejoin', report['summary'] == 'Existing session works after upgrade')
        async def native():
            from mcp import Client
            from mcp.client.stdio import StdioServerParameters
            async with Client(StdioServerParameters(command=sys.executable,
                              args=['-m', 'coopagents.space_bridge', '--profile', str(peer_path)]), cache=None) as client:
                tools = {t.name for t in (await client.list_tools()).tools}
                me = await client.call_tool('whoami', {})
                team = await client.call_tool('read_team', {})
                return {'whoami', 'read_team'} <= tools and not me.is_error and not team.is_error \
                    and me.structured_content['me']['member_id'] == baseline['peer_member_id']
        check('candidate stdio MCP uses existing peer identity', asyncio.run(native()))
        private_write(root / 'upgraded-snapshot.json', runtime.request(owner['origin'], '/api/snapshot', token=owner['web_token']))
    finally:
        runtime.stop(owner_path)
    backup = root / 'baseline-backup'
    hashes = json.loads((root / 'baseline-backup-hashes.json').read_text(encoding='utf-8'))
    check('baseline backup remains unchanged', all(digest(backup / name) == value for name, value in hashes.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('seed', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--baseline-report', type=Path)
    args = parser.parse_args()
    root = private_directory(args.root).resolve()
    if args.stage == 'seed':
        if not args.baseline_report:
            parser.error('seed requires the retained --baseline-report from pip install --report')
        seed(root, args.baseline_report)
    else:
        if not args.wheel:
            parser.error('verify requires --wheel')
        verify(root, args.wheel)


if __name__ == '__main__':
    main()
