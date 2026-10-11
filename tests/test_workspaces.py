import unittest
from pathlib import Path
from uuid import uuid4
from crewmesh.identity import IdentityStore
from crewmesh.accounts import AccountStore
from crewmesh.workspaces import WorkspaceStore
from crewmesh.errors import AccessDenied


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        root = Path('.local/c1-tests'); root.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(root / (str(uuid4()) + '.sqlite'))
        self.accounts = AccountStore(self.identity)
        self.accounts.bootstrap('owner', 'long password 123')
        self.owner = self.accounts.login('owner', 'long password 123')['session_token']
        self.workspaces = WorkspaceStore(self.accounts)
        self.team = self.workspaces.create_team(self.owner, 'Team')['team_id']

    def join(self, name='member', role='member', projects=()):
        invite = self.workspaces.create_invite(self.owner, self.team, role, projects)
        result = self.workspaces.accept_invite(invite['invite_token'], username=name, password='long password 123')
        return result['account']['id'], self.accounts.login(name, 'long password 123')['session_token']

    def test_explicit_project_scope_and_revocation(self):
        project = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        member, session = self.join()
        self.assertEqual([], self.workspaces.list_projects(session, self.team))
        with self.assertRaises(AccessDenied): self.workspaces.project_credential(session, project)
        self.workspaces.grant_project(self.owner, project, member)
        credential = self.workspaces.project_credential(session, project)
        agent = self.identity.rotate_agent(credential['web_token'])['agent_token']
        self.workspaces.remove_member(self.owner, self.team, member)
        for token in (credential['web_token'], agent):
            with self.assertRaises(AccessDenied): self.identity.authenticate(token)
        with self.assertRaises(AccessDenied): self.workspaces.project_credential(session, project)

    def test_roles_last_owner_and_invite_invalidation(self):
        admin, session = self.join('admin', 'admin')
        with self.assertRaises(AccessDenied): self.workspaces.remove_member(session, self.team, self.accounts.authenticate(self.owner)['id'])
        with self.assertRaises(AccessDenied): self.workspaces.change_role(self.owner, self.team, self.accounts.authenticate(self.owner)['id'], 'member')
        invite = self.workspaces.create_invite(session, self.team)
        self.workspaces.change_role(self.owner, self.team, admin, 'member')
        with self.assertRaises(AccessDenied): self.workspaces.accept_invite(invite['invite_token'], username='late', password='long password 123')

    def test_single_use_invites_and_scope(self):
        project = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        invite = self.workspaces.create_invite(self.owner, self.team, project_ids=[project])
        accepted = self.workspaces.accept_invite(invite['invite_token'], username='new', password='long password 123')
        with self.assertRaises(AccessDenied): self.workspaces.accept_invite(invite['invite_token'], session_token=self.owner)
        session = self.accounts.login('new', 'long password 123')['session_token']
        self.assertEqual(project, self.workspaces.list_projects(session, self.team)[0]['room_id'])

    def test_legacy_claim_preserves_collaborator_but_blocks_invites(self):
        old = self.identity.create_room('legacy', 'old')
        collaborator = self.identity.add_member(old['web_token'], 'colleague')
        pending = self.identity.create_invite(old['web_token'])
        with self.assertRaises(AccessDenied): self.workspaces.claim_legacy_project(self.owner, self.team, collaborator['web_token'])
        self.workspaces.claim_legacy_project(self.owner, self.team, old['web_token'])
        self.identity.authenticate(collaborator['agent_token'])
        with self.assertRaises(AccessDenied): self.identity.join_invite(pending['invite_token'], 'intruder')
        with self.assertRaises(AccessDenied): self.identity.create_invite(old['web_token'])
        with self.assertRaises(AccessDenied): self.workspaces.claim_legacy_project(self.owner, self.team, old['web_token'])

    def test_admin_password_reset_revokes_all_sessions(self):
        member, session = self.join()
        admin, admin_session = self.join('admin', 'admin')
        with self.assertRaises(AccessDenied): self.workspaces.reset_password(admin_session, self.team, admin, 'new long password')
        self.workspaces.reset_password(admin_session, self.team, member, 'new long password')
        with self.assertRaises(AccessDenied): self.accounts.authenticate(session)
        self.accounts.login('member', 'new long password')

    def test_project_removal_prevents_agent_rotation(self):
        project = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        member, session = self.join(projects=[project])
        token = self.workspaces.project_credential(session, project)['web_token']
        self.workspaces.remove_project_member(self.owner, project, member)
        with self.assertRaises(AccessDenied): self.identity.rotate_agent(token)

    def test_logout_revokes_project_web_but_preserves_agent(self):
        room = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        credential = self.workspaces.project_credential(self.owner, room)
        agent = self.identity.rotate_agent(credential['web_token'])['agent_token']
        self.accounts.logout(self.owner)
        with self.assertRaises(AccessDenied): self.identity.authenticate(credential['web_token'])
        self.identity.authenticate(agent)

    def test_forged_ids_and_cross_team_scope_rejected(self):
        other_team = self.workspaces.create_team(self.owner, 'two')['team_id']
        room = self.workspaces.create_project(self.owner, other_team, 'private')['room_id']
        member, session = self.join()
        with self.assertRaises(AccessDenied): self.workspaces.list_projects(session, other_team)
        with self.assertRaises(AccessDenied): self.workspaces.create_project(session, self.team, 'bad')
        with self.assertRaises(AccessDenied): self.workspaces.create_invite(self.owner, self.team, project_ids=[room])
        with self.assertRaises(AccessDenied): self.workspaces.grant_project(session, room, member)

    def test_expired_invite_creates_no_account(self):
        invite = self.workspaces.create_invite(self.owner, self.team)
        with self.accounts.db.connect(write=True) as c: c.execute("UPDATE team_invitations SET expires_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(AccessDenied): self.workspaces.accept_invite(invite['invite_token'], username='expired', password='long password 123')
        with self.accounts.db.connect() as c: self.assertEqual(1, c.execute('SELECT count(*) FROM accounts').fetchone()[0])

    def test_existing_account_accepts_and_owner_can_leave_with_successor(self):
        member, session = self.join()
        other_team = self.workspaces.create_team(self.owner, 'other')['team_id']
        invite = self.workspaces.create_invite(self.owner, other_team)
        self.workspaces.accept_invite(invite['invite_token'], session_token=session)
        self.workspaces.change_role(self.owner, self.team, member, 'owner')
        self.workspaces.remove_member(self.owner, self.team, self.accounts.authenticate(self.owner)['id'])
        self.assertEqual('owner', self.workspaces.list_teams(session)[0]['role'])

    def test_multiteam_password_reset_is_denied(self):
        member, session = self.join()
        self.workspaces.create_team(session, 'member owned')
        with self.assertRaises(AccessDenied): self.workspaces.reset_password(self.owner, self.team, member, 'new long password')

    def test_admin_cannot_grant_project_to_peer(self):
        room = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        peer, _ = self.join('peer', 'admin')
        _, admin_session = self.join('admin', 'admin')
        with self.assertRaises(AccessDenied): self.workspaces.grant_project(admin_session, room, peer)

    def test_manager_metadata_does_not_grant_context_and_owner_reset_denied(self):
        room = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        peer, peer_session = self.join('peer', 'owner')
        self.assertEqual(False, self.workspaces.list_managed_projects(peer_session, self.team)[0]['has_access'])
        with self.assertRaises(AccessDenied): self.workspaces.project_credential(peer_session, room)
        with self.assertRaises(AccessDenied): self.workspaces.reset_password(self.owner, self.team, peer, 'new long password')

    def test_concurrent_invite_redemption_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        invite = self.workspaces.create_invite(self.owner, self.team)
        def redeem(name):
            try:
                self.workspaces.accept_invite(invite['invite_token'], username=name, password='long password 123')
                return True
            except AccessDenied:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False, True], sorted(pool.map(redeem, ['race1','race2'])))
        with self.accounts.db.connect() as c: self.assertEqual(2, c.execute('SELECT count(*) FROM accounts').fetchone()[0])

    def test_session_expiry_blocks_project_web_and_rollback_preserves_invite(self):
        room = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        token = self.workspaces.project_credential(self.owner, room)['web_token']
        invite = self.workspaces.create_invite(self.owner, self.team)
        with self.assertRaises(Exception): self.workspaces.accept_invite(invite['invite_token'], username='bad', password='short')
        self.workspaces.accept_invite(invite['invite_token'], username='good', password='long password 123')
        with self.accounts.db.connect(write=True) as c: c.execute("UPDATE account_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(AccessDenied): self.identity.rotate_agent(token)

    def test_demoted_creator_cannot_revoke_other_member_agent(self):
        room = self.workspaces.create_project(self.owner, self.team, 'one')['room_id']
        member, session = self.join(projects=[room])
        peer, peer_session = self.join('successor', 'owner')
        self.workspaces.change_role(peer_session, self.team, self.accounts.authenticate(self.owner)['id'], 'member')
        creator = self.workspaces.project_credential(self.owner, room)
        target = self.workspaces.project_credential(session, room)
        with self.assertRaises(AccessDenied): self.identity.revoke_agent(creator['web_token'], target['member_id'])
        agent = self.identity.rotate_agent(creator['web_token'])['agent_token']
        self.identity.revoke_agent(creator['web_token'], creator['member_id'])
        with self.assertRaises(AccessDenied): self.identity.authenticate(agent)

    def test_managed_admin_can_revoke_ordinary_but_not_owner_agent(self):
        admin, admin_session = self.join('admin', 'admin')
        room = self.workspaces.create_project(admin_session, self.team, 'admin project')['room_id']
        member, session = self.join(projects=[room])
        owner_id = self.accounts.authenticate(self.owner)['id']
        self.workspaces.grant_project(self.owner, room, owner_id)
        admin_web = self.workspaces.project_credential(admin_session, room)
        member_web = self.workspaces.project_credential(session, room)
        owner_web = self.workspaces.project_credential(self.owner, room)
        self.identity.revoke_agent(admin_web['web_token'], member_web['member_id'])
        with self.assertRaises(AccessDenied): self.identity.revoke_agent(admin_web['web_token'], owner_web['member_id'])
