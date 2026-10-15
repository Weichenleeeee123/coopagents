"""Two-machine acceptance helper: collect evidence without credentials.

Run on each computer with the installed release environment:

  python scripts/two_machine_check.py report --profile <private-profile> --out <evidence.json>
  python scripts/two_machine_check.py ping   --profile <private-profile> --to <member-id> --marker <WORD>

`report` records version, runtime/p2p status (direct or relay), wake watchers
and recent wakes, pending counts and the request/reply trail. `ping` sends one
request to a teammate so their agent can be woken. Outputs never include tokens.
"""
import argparse
import json
from importlib.metadata import version
import platform
import sys
import time


def report(profile_path):
    from coopagents.space_runtime import request, status
    from coopagents.space_wake import WakeState, remote_digest
    from coopagents.spaces import read_profile
    from coopagents.p2p import member_link
    profile = read_profile(profile_path)
    result = {'collected_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'coopagents': version('coopagents'),
              'python': sys.version.split()[0], 'platform': platform.platform(),
              'member_id': profile['member_id'], 'room_id': profile['room_id'],
              'runtime': status(profile_path), 'wake': WakeState(profile_path).summary()}
    with member_link(profile):
        try:
            result['pending'] = remote_digest(profile_path)['counts']
        except Exception as error:
            result['pending'] = 'unavailable: ' + type(error).__name__
        team = request(profile['origin'], '/api/operations/read_git_team', token=profile['agent_token'], data={})
    names = {m['member_id']: m['display_name'] for m in team.get('members', []) if isinstance(m, dict) and 'member_id' in m}
    result['members'] = names
    result['requests'] = [{'id': r['id'], 'from': names.get(r['sender_member_id'], r['sender_member_id']),
                           'to': names.get(r['receiver_member_id'], r['receiver_member_id']), 'created_at': r['created_at'],
                           'read_at': r['read_at'], 'replies': [{'at': y['created_at'], 'body': y['body'][:200]} for y in r['replies']]}
                          for r in team['requests']]
    return result


def ping(profile_path, to, marker):
    from coopagents.space_runtime import request
    from coopagents.spaces import read_profile
    from coopagents.p2p import member_link
    profile = read_profile(profile_path)
    with member_link(profile):
        sent = request(profile['origin'], '/api/operations/send_request', token=profile['agent_token'], data={
            'request_key': 'two-machine-' + marker, 'receiver_member_id': to, 'context_version': 1,
            'body': f'Two-machine acceptance. Please reply with "Received {marker}". Marker: {marker}'})
    return {'sent_request': sent['id'], 'to': to, 'marker': marker, 'sent_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    r = commands.add_parser('report')
    r.add_argument('--profile', required=True)
    r.add_argument('--out')
    p = commands.add_parser('ping')
    p.add_argument('--profile', required=True)
    p.add_argument('--to', required=True, help='Teammate member id (see report.members)')
    p.add_argument('--marker', required=True)
    args = parser.parse_args(argv)
    result = report(args.profile) if args.command == 'report' else ping(args.profile, args.to, args.marker)
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if getattr(args, 'out', None):
        with open(args.out, 'x', encoding='utf-8') as f:
            f.write(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
