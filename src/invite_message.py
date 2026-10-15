"""Shareable invitation messages: one paste carries the pitch, the agent prompt and a one-time code."""
import base64
import binascii
import json
import re
from datetime import datetime
from importlib import metadata
from urllib.parse import urlsplit

PROJECT_URL = 'https://github.com/Weichenleeeee123/coopagents'
CODE_PREFIX = 'coopagents-invite-1.'
# Codes made before the rename (0.6.0rc2 shipped as Crewmesh) are still accepted.
LEGACY_CODE_PREFIXES = ('crewmesh-invite-1.',)
MAX_CODE_LENGTH = 4096
DESCRIPTOR_FIELDS = ('schema_version', 'origin', 'room_id', 'invite_token', 'expires_at')
# A code is one unbroken base64url run, so surrounding text and separator lines never join it.
CODE_PATTERN = re.compile('(?:' + '|'.join(re.escape(p) for p in (CODE_PREFIX,) + LEGACY_CODE_PREFIXES)
                          + r')([A-Za-z0-9_-]+)')


class InvitationCodeError(ValueError):
    """A fixed, secret-free explanation that the CLI may show to the user."""

def encode(descriptor):
    data = {key: descriptor[key] for key in DESCRIPTOR_FIELDS}
    if 'p2p' in descriptor:
        data['p2p'] = descriptor['p2p']
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode(text):
    """Find the code in a code or a whole pasted message and return its descriptor."""
    if not isinstance(text, str) or len(text) > 64 * 1024:
        raise InvitationCodeError('Invitation code not found')
    found = set(CODE_PATTERN.findall(text))
    if not found:
        raise InvitationCodeError('Invitation code not found')
    if len(found) > 1:
        raise InvitationCodeError('Expected exactly one invitation code')
    body = found.pop()
    if len(body) > MAX_CODE_LENGTH:
        raise InvitationCodeError('Invitation code is incomplete or damaged')
    try:
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvitationCodeError('Invitation code is incomplete or damaged') from None
    if not isinstance(data, dict) or set(data) - set(DESCRIPTOR_FIELDS) - {'p2p'}:
        raise InvitationCodeError('Invitation code is incomplete or damaged')
    if data.get('schema_version') != 1 or any(
            not isinstance(data.get(key), str) or not data[key] for key in DESCRIPTOR_FIELDS[1:]):
        raise InvitationCodeError('Invitation code is incomplete or damaged')
    if 'p2p' in data and not isinstance(data['p2p'], dict):
        raise InvitationCodeError('Invitation code is incomplete or damaged')
    return data


def local_only(descriptor):
    return 'p2p' not in descriptor and urlsplit(descriptor['origin']).hostname in ('127.0.0.1', 'localhost', '::1')


def _expiry(expires_at):
    moment = datetime.fromisoformat(expires_at).astimezone()
    offset = moment.strftime('%z')
    return moment.strftime('%Y-%m-%d %H:%M') + ' (UTC' + offset[:3] + ':' + offset[3:] + ')'


TEXT = {
    'en': {
        'invited': '{inviter} invited you to the Coopagents space "{space}".',
        'pitch': ('Coopagents is multiplayer mode for Claude Code and Codex: our agents share one task board, '
                  'ask each other questions and hand off work directly. Peer-to-peer, no account.'),
        'local': 'Note: this space is only open on the inviting computer, so only agents on that computer can join.',
        'paste': 'Paste everything between the two lines into your Claude Code or Codex:',
        'install': ('Install Coopagents {version} from PyPI into an isolated Python environment: `{command}` '
                    '(if a package mirror does not have it yet, add `--index-url https://pypi.org/simple`). '
                    'Then set up its Coopagents skill from {skill}.'),
        'install_any': ('Install the newest Coopagents from PyPI into an isolated Python environment: `{command}` '
                        '(if a package mirror does not have it yet, add `--index-url https://pypi.org/simple`). '
                        'Then set up its Coopagents skill from {skill}.'),
        'prompt': ('{install} '
                   'Then join my Coopagents space with the one-time invitation code below. Pass the code to '
                   '`space_runtime join --invitation-code-stdin` on standard input, never as a command argument. '
                   'If you do not know which display name to join with, ask me.'),
        'warning': ('This invitation works once and expires at {expires}. It contains a key: send it only to the '
                    'person you are inviting, never to a group chat or anywhere public.'),
    },
    'zh': {
        'invited': '{inviter} 邀请你加入 Coopagents 空间「{space}」。',
        'pitch': 'Coopagents 是 Claude Code 和 Codex 的多人模式：我们的 agent 共用一个任务看板，可以直接互相提问、交接任务。点对点连接，不需要账号。',
        'local': '注意：这个空间只在发起人的电脑上开放，只有那台电脑上的 agent 能加入。',
        'paste': '把两条分隔线之间的内容整段发给你的 Claude Code 或 Codex：',
        'install': ('从 PyPI 把 Coopagents {version} 装进独立的 Python 环境：`{command}`'
                    '（如果包镜像还没同步到，加上 `--index-url https://pypi.org/simple`），再按 {skill} 配置它的 Coopagents Skill。'),
        'install_any': ('从 PyPI 把最新的 Coopagents 装进独立的 Python 环境：`{command}`'
                        '（如果包镜像还没同步到，加上 `--index-url https://pypi.org/simple`），再按 {skill} 配置它的 Coopagents Skill。'),
        'prompt': ('{install}然后用下面的一次性邀请码加入我的 Coopagents 空间：'
                   '通过标准输入把邀请码交给 `space_runtime join --invitation-code-stdin`，不要放进命令参数。'
                   '如果不知道该用什么名字加入，先问我。'),
        'warning': '这条邀请只能用一次，{expires} 过期。里面含有密钥：只发给你要邀请的人，不要发到群里或任何公开的地方。',
    },
}


def installed_version():
    """The inviter's own Coopagents version, so the invitee installs the same one."""
    try:
        return metadata.version('coopagents')
    except metadata.PackageNotFoundError:
        return None


def skill_url(version):
    return f'{PROJECT_URL}/tree/{"v" + version if version else "main"}/src/skills/coopagents-space'


def install_command(version):
    if version:
        return f'pip install "coopagents[space]=={version}"'
    return 'pip install --pre "coopagents[space]"'


_INSTALLED = object()


def compose(descriptor, inviter, space, lang='en', version=_INSTALLED):
    if lang not in TEXT:
        raise ValueError('Unsupported language')
    if version is _INSTALLED:
        version = installed_version()
    text = TEXT[lang]
    install = text['install' if version else 'install_any'].format(
        version=version, command=install_command(version), skill=skill_url(version))
    lines = [text['invited'].format(inviter=inviter, space=space), '', text['pitch'], PROJECT_URL]
    if local_only(descriptor):
        lines += ['', text['local']]
    lines += ['', text['paste'], '----------', text['prompt'].format(install=install), encode(descriptor),
              '----------', '', text['warning'].format(expires=_expiry(descriptor['expires_at']))]
    return '\n'.join(lines)
