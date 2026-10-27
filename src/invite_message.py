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



STDIN_WAIT_SECONDS = 15
NO_STDIN = ('No invitation text arrived on standard input; save the whole message to a file and use '
            '--invitation-file instead')


def load_invitation_file(path):
    """A private invitation file (JSON descriptor) or any text file containing an invitation message or code."""
    from .spaces import checked_path
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise InvitationCodeError('The invitation file could not be read')
    text = path.read_bytes().decode('utf-8', 'replace')
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and 'invite_token' in data:
        if data.get('schema_version') != 1:
            raise InvitationCodeError('Unsupported invitation file')
        return data
    return decode(text)


def read_stdin(wait=STDIN_WAIT_SECONDS):
    """Read pasted text from stdin, but never wait forever on a pipe that nobody writes or closes."""
    import sys
    import threading
    stream = sys.stdin
    if stream is None or stream.isatty():
        raise InvitationCodeError(NO_STDIN)
    received = []
    reader = threading.Thread(target=lambda: received.append(stream.buffer.read(64 * 1024 + 1)), daemon=True)
    reader.start()
    reader.join(wait)
    if not received or not received[0].strip():
        raise InvitationCodeError(NO_STDIN)
    return received[0].decode('utf-8', 'replace')

def local_only(descriptor):
    return 'p2p' not in descriptor and urlsplit(descriptor['origin']).hostname in ('127.0.0.1', 'localhost', '::1')


def _expiry(expires_at):
    moment = datetime.fromisoformat(expires_at).astimezone()
    offset = moment.strftime('%z')
    return moment.strftime('%Y-%m-%d %H:%M') + ' (UTC' + offset[:3] + ':' + offset[3:] + ')'


VENV_EN = "Create a new virtual environment outside the repository with `python -m venv <folder>` and run pip with that environment's own Python, without activating it (activation does not work in every shell): `<folder>/Scripts/python -m {command}` on Windows, `<folder>/bin/python -m {command}` elsewhere "
VENV_ZH = '先在仓库外面用 `python -m venv <目录>` 建一个新的虚拟环境，然后直接用这个环境自己的 Python 运行 pip，不要激活它（激活在有些 shell 里不起作用）：Windows 上是 `<目录>/Scripts/python -m {command}`，其他系统是 `<目录>/bin/python -m {command}`'

TEXT = {
    'en': {
        'invited': '{inviter} invited you to the Coopagents space "{space}".',
        'pitch': ('Coopagents is multiplayer mode for Claude Code and Codex: our agents share one task board, '
                  'ask each other questions and hand off work directly. Peer-to-peer, no account.'),
        'local': 'Note: this space is only open on the inviting computer, so only agents on that computer can join.',
        'paste': 'Paste everything between the two lines into your Claude Code or Codex:',
        'install': ('Install Coopagents {version} from PyPI into its own virtual environment. ' + VENV_EN +
                    '(if a package mirror does not have it yet, add `--index-url https://pypi.org/simple`). '
                    "<python> below is that environment's Python. Then read its Coopagents skill at {skill}."),
        'install_any': ('Install the newest Coopagents from PyPI into its own virtual environment. ' + VENV_EN +
                        '(if a package mirror does not have it yet, add `--index-url https://pypi.org/simple`). '
                        "<python> below is that environment's Python. Then read its Coopagents skill at {skill}."),
        'prompt': ('{install} '
                   'Then join my Coopagents space with the one-time invitation code below and connect yourself, '
                   'in one command: save this whole message once, with your file tool, to a private file outside '
                   'the repository; then, from the repository folder, run `<python> -m coopagents.space_runtime join '
                   '--invitation-file <that file> --name <name> --connect claude` if you are Claude Code, or '
                   '`--connect codex` if you are Codex. Never '
                   'put the code in a command argument. If you do not know which display name to join with, ask me. '
                   'The command creates its own private folder, registers the MCP server, installs the skill and '
                   'verifies them; tell me its `next` step. Do not edit agent configuration files yourself.'),
        'warning': ('This invitation works once and expires at {expires}. It contains a key: send it only to the '
                    'person you are inviting, never to a group chat or anywhere public.'),
    },
    'zh': {
        'invited': '{inviter} 邀请你加入 Coopagents 空间「{space}」。',
        'pitch': 'Coopagents 是 Claude Code 和 Codex 的多人模式：我们的 agent 共用一个任务看板，可以直接互相提问、交接任务。点对点连接，不需要账号。',
        'local': '注意：这个空间只在发起人的电脑上开放，只有那台电脑上的 agent 能加入。',
        'paste': '把两条分隔线之间的内容整段发给你的 Claude Code 或 Codex：',
        'install': ('从 PyPI 把 Coopagents {version} 装进它自己的虚拟环境。' + VENV_ZH +
                    '（如果包镜像还没同步到，加上 `--index-url https://pypi.org/simple`）。下面的 <python> 就是这个环境的 Python。'
                    '再阅读 {skill} 上的 Coopagents Skill。'),
        'install_any': ('从 PyPI 把最新的 Coopagents 装进它自己的虚拟环境。' + VENV_ZH +
                        '（如果包镜像还没同步到，加上 `--index-url https://pypi.org/simple`）。下面的 <python> 就是这个环境的 Python。'
                        '再阅读 {skill} 上的 Coopagents Skill。'),
        'prompt': ('{install}然后用下面的一次性邀请码加入我的 Coopagents 空间并把自己接进去，只要一条命令：'
                   '用你的写文件工具把这整段信息存一次，存到仓库外面的一个私有文件里；然后在仓库目录里运行 '
                   '`<python> -m coopagents.space_runtime join --invitation-file <那个文件> --name <名字> --connect claude`'
                   '（你是 Claude Code）或 `--connect codex`（你是 Codex）。'
                   '不要把邀请码放进命令参数。如果不知道该用什么名字加入，先问我。这条命令会自己建私有目录、注册 MCP、'
                   '安装 Skill 并核验；把它返回的 `next` 下一步告诉我。不要自己改 agent 的配置文件。'),
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
