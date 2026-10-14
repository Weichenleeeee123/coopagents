"""Acceptance host on a GitHub Actions runner: a real p2p space joined from another network.

setup: create the space, add a fictional task, write an invitation encrypted to the
       tester's public key (the invitation never appears in logs or Git).
drive: react to the remote member: new task after join, host restart after the
       member claims, a third task after restart; stop when the member reports done.
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crewmesh import space_runtime as rt
from crewmesh.spaces import read_profile

root = Path('.local/accept')
profile_path = root / 'owner' / 'profile.json'
out = Path('out')
out.mkdir(exist_ok=True)


def log(**row):
    print(json.dumps({'t': round(time.time(), 1)} | row), flush=True)


def owner():
    return read_profile(profile_path)


def op(name, data, web=False):
    p = owner()
    return rt.request(p['origin'], '/api/operations/' + name, token=p['web_token' if web else 'agent_token'], data=data)


def snapshot():
    p = owner()
    return rt.request(p['origin'], '/api/snapshot', token=p['agent_token'])


def setup():
    rt.create('Acceptance space', 'Runner host', root / 'owner')
    status = rt.status(profile_path)
    log(event='host_ready', status=status['status'], p2p=status.get('p2p'))
    op('create_task', {'intent_key': 'accept-1', 'title': 'Fictional acceptance task 1', 'scope': 'acceptance/one'}, web=True)
    invitation = rt.invite(profile_path, share=True)['invitation']
    public = serialization.load_pem_public_key(Path(sys.argv[2]).read_bytes())
    key, nonce = AESGCM.generate_key(256), os.urandom(12)
    sealed = {
        'ek': base64.b64encode(public.encrypt(key, padding.OAEP(padding.MGF1(hashes.SHA256()), hashes.SHA256(), None))).decode(),
        'nonce': base64.b64encode(nonce).decode(),
        'ct': base64.b64encode(AESGCM(key).encrypt(nonce, json.dumps(invitation).encode(), None)).decode(),
    }
    (out / 'invite.enc.json').write_text(json.dumps(sealed))
    log(event='invite_sealed', endpoint_id=invitation['p2p']['endpoint_id'])


def drive():
    stage, deadline, last_status = 'wait_join', time.time() + 13 * 60, 0
    while time.time() < deadline:
        try:
            snap = snapshot()
        except Exception as error:
            log(event='snapshot_error', error=type(error).__name__)
            time.sleep(2)
            continue
        if time.time() - last_status > 20:
            status = rt.status(profile_path)
            log(event='host_status', stage=stage, p2p=status.get('p2p'), members=len(snap['members']))
            last_status = time.time()
        if stage == 'wait_join' and len(snap['members']) >= 2:
            log(event='member_joined')
            op('create_task', {'intent_key': 'accept-2', 'title': 'Fictional task after join', 'scope': 'acceptance/two'}, web=True)
            stage = 'wait_claim'
        elif stage == 'wait_claim' and any(t['title'] == 'Fictional acceptance task 1' and t.get('owner_member_id')
                                           and t['owner_member_id'] != owner()['member_id'] for t in snap['tasks']):
            log(event='member_claimed; restarting host')
            rt.stop(profile_path)
            time.sleep(8)
            rt.start(profile_path)
            status = rt.status(profile_path)
            log(event='host_restarted', status=status['status'], p2p=status.get('p2p'))
            time.sleep(10)
            op('create_task', {'intent_key': 'accept-3', 'title': 'Fictional task after restart', 'scope': 'acceptance/three'}, web=True)
            stage = 'wait_done'
        elif stage == 'wait_done':
            inbox = op('read_inbox', {})
            items = inbox.get('requests', inbox) if isinstance(inbox, dict) else inbox
            if any('acceptance-done' in json.dumps(item) for item in items):
                log(event='member_reported_done')
                break
        time.sleep(2)
    else:
        log(event='deadline_reached', stage=stage)
    rt.stop(profile_path)
    log(event='host_stopped')


{'setup': setup, 'drive': drive}[sys.argv[1]]()
