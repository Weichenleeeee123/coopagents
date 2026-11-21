"""Render, merge and persist native wake-hook settings for supported agent tools."""
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

from .spaces import checked_path


TOOLS = ('claude', 'codex', 'zcode', 'cursor', 'kimi-code')
# The Codex desktop app shares CODEX_HOME with the CLI (see
# space_connect.TOOL_ALIASES); codex-desktop is an alias for codex here too.
TOOL_ALIASES = {'codex-desktop': 'codex'}
CLAUDE_HOOK_TIMEOUT = 3600
CURSOR_SESSION_TIMEOUT = 60
DEADLINE_MARGIN = 120
DEFAULT_STANDBY = 900
# Kimi hook timeouts are capped at 600 seconds (docs range 1-600); the
# installed Stop-hook timeout and standby budget stay below that cap.
KIMI_HOOK_TIMEOUT_MAX = 600
KIMI_WAKE_MARKER = 'coopagents wake hook'
MARKER = 'coopagents.space_wake'
# Hooks installed before the rename to Coopagents; recognised so install replaces them and disable removes them.
LEGACY_MARKERS = ('crewmesh.space_wake',)


class WakeSetupError(RuntimeError):
    """A fixed, secret-free explanation shown to the user."""


def normalize_tool(tool):
    return TOOL_ALIASES.get(tool, tool)


def hook_command(profile_path, tool):
    executable = _portable(Path(sys.executable), shorten=True, quote=os.name != 'nt')
    profile = _portable(checked_path(profile_path), quote=os.name != 'nt')
    if os.name == 'nt':
        # A single encoded PowerShell command line avoids Git Bash's C:/ path lookup and slash conversion.
        script = (f'& {_powershell_literal(executable)} -I -m {MARKER} watch --tool {tool} '
                  f'--profile {_powershell_literal(profile)}; '
                  "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE } else { exit 1 }")
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return f'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}'
    return f'{executable} -I -m {MARKER} watch --tool {tool} --profile {profile}'


def hook_process(profile_path, tool):
    """argv for a ZCode process hook: executed directly without a shell, so paths need no quoting."""
    return str(Path(sys.executable)), ['-I', '-m', MARKER, 'watch', '--tool', tool,
                                       '--profile', str(checked_path(profile_path))]


def _portable(path, shorten=False, quote=True):
    """A shell-neutral path: forward slashes; optionally a Windows short name to avoid spaces."""
    text = str(path)
    if shorten and os.name == 'nt':
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer)):
            text = buffer.value
    text = text.replace('\\', '/')
    return f'"{text}"' if quote and ' ' in text else text


def _powershell_literal(value):
    return "'" + value.replace("'", "''") + "'"


def hook_config(profile_path, tool, standby=DEFAULT_STANDBY):
    if tool == 'kimi-code':
        # Kimi wake hooks are [[hooks]] TOML, not a JSON document; the
        # fragment comes from kimi_wake_hooks_text.
        raise ValueError('Kimi Code wake hooks are TOML; use kimi_wake_hooks_text')
    if tool == 'cursor':
        # Cursor hooks.json entries are flat per-event command definitions;
        # the same watch command baselines on sessionStart and checks on stop.
        command = hook_command(profile_path, tool)
        return {'sessionStart': [{'command': command, 'timeout': CURSOR_SESSION_TIMEOUT}],
                'stop': [{'command': command, 'timeout': standby + DEADLINE_MARGIN}]}
    if tool == 'zcode':
        command, args = hook_process(profile_path, tool)
        # SessionStart matches `source`; only startup/clear baseline, so a
        # compact never swallows items that arrived during the session.
        start = {'type': 'process', 'command': command, 'args': list(args)}
        # ZCode's default hook timeout is 60s; the Stop hook must cover the
        # standby budget, so its timeout is set in milliseconds.
        stop = {'type': 'process', 'command': command, 'args': list(args),
                'timeoutMs': (standby + DEADLINE_MARGIN) * 1000}
        return {'SessionStart': [{'matcher': 'startup|clear', 'hooks': [start]}],
                'Stop': [{'hooks': [stop]}]}
    command = hook_command(profile_path, tool)
    if tool == 'claude':
        handler = {'type': 'command', 'command': command, 'asyncRewake': True, 'timeout': CLAUDE_HOOK_TIMEOUT}
        return {'SessionStart': [{'hooks': [dict(handler)]}], 'Stop': [{'hooks': [dict(handler)]}]}
    return {'Stop': [{'hooks': [{'type': 'command', 'command': command, 'timeout': standby + DEADLINE_MARGIN}]}]}


def kimi_wake_hooks_text(profile_path, standby=DEFAULT_STANDBY):
    """The [[hooks]] TOML fragment install appends to ~/.kimi-code/config.toml.

    SessionStart only baselines (it is observation-only); Stop blocks with
    the notice on stderr. The Stop timeout must cover the standby budget,
    and Kimi caps hook timeouts at 600 seconds, so the budget is capped
    below it. The command is a JSON string, which is also valid TOML.
    """
    command = hook_command(profile_path, 'kimi-code')
    budget = min(standby, KIMI_HOOK_TIMEOUT_MAX - DEADLINE_MARGIN)
    blocks = []
    for event, timeout in (('SessionStart', CURSOR_SESSION_TIMEOUT),
                           ('Stop', budget + DEADLINE_MARGIN)):
        blocks.append('\n'.join((
            '# %s (managed; do not edit)' % KIMI_WAKE_MARKER,
            '[[hooks]]',
            'event = %s' % json.dumps(event),
            'command = %s' % json.dumps(command),
            'timeout = %d' % timeout,
        )))
    return '\n\n'.join(blocks) + '\n'


def merge_kimi_wake_hooks(existing_text, fragment_text):
    """Merge wake [[hooks]] blocks into a Kimi config.toml, preserving the rest.

    Checkpoint hook blocks and foreign rules are kept: the merge only drops
    blocks carrying the wake marker or the space_wake command.
    """
    from .checkpoint_hook import merge_kimi_hooks
    return merge_kimi_hooks(existing_text, fragment_text, marker=KIMI_WAKE_MARKER,
                            needles=(MARKER,) + LEGACY_MARKERS)


def _load_text(path):
    return path.read_text(encoding='utf-8') if path.exists() else ''


def _write_text_settings(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # Keep the previous file next to it; never delete user configuration.
        backup = path.with_name(f'{path.name}.coopagents-{time.strftime("%Y%m%d%H%M%S")}-{uuid4().hex[:6]}.bak')
        backup.write_bytes(path.read_bytes())
    staging = path.with_name(path.name + '.' + uuid4().hex + '.pending')
    staging.write_text(text, encoding='utf-8')
    os.replace(staging, path)


def settings_path(tool, scope, project_dir=None):
    if tool == 'kimi-code':
        if scope != 'user':
            raise WakeSetupError('Kimi Code has no project-level hook file; install wake-up with --scope user')
        return Path.home() / '.kimi-code' / 'config.toml'
    if tool == 'cursor':
        if scope == 'user':
            return Path.home() / '.cursor' / 'hooks.json'
        # Agents run from the repository folder, so that is the default project.
        return Path(project_dir or os.getcwd()).absolute() / '.cursor' / 'hooks.json'
    if tool == 'zcode':
        # ZCode ignores project-level hooks as a whole (logged as
        # config_project_hooks_ignored); only the user config runs them.
        if scope != 'user':
            raise WakeSetupError('ZCode ignores project-level hooks; install wake-up with --scope user')
        return Path.home() / '.zcode' / 'cli' / 'config.json'
    if scope == 'user':
        return Path.home() / ('.claude/settings.json' if tool == 'claude' else '.codex/hooks.json')
    # Agents run from the repository folder, so that is the default project.
    base = Path(project_dir or os.getcwd()).absolute()
    return base / ('.claude/settings.local.json' if tool == 'claude' else '.codex/hooks.json')


def managed_hook_command(text):
    text = str(text)
    if any(marker in text for marker in (MARKER,) + LEGACY_MARKERS):
        return True
    encoded = re.search(r'(?:^|\s)-EncodedCommand\s+([A-Za-z0-9+/=]+)(?:\s|$)', text, re.I)
    if encoded:
        try:
            script = base64.b64decode(encoded.group(1), validate=True).decode('utf-16-le')
        except (ValueError, UnicodeDecodeError):
            return False
        return any(marker in script for marker in (MARKER,) + LEGACY_MARKERS)
    return False


def managed_hook_group(group):
    for hook in group.get('hooks', []):
        if not isinstance(hook, dict):
            continue
        text = str(hook.get('command', ''))
        args = hook.get('args')
        if isinstance(args, list):
            # Process hooks carry the marker in argv, not in the command.
            text = text + ' ' + ' '.join(str(item) for item in args)
        if managed_hook_command(text):
            return True
    return False


def merge_hooks(document, additions):
    """Replace only our own hook groups; keep every other setting and hook."""
    document = dict(document)
    hooks = dict(document.get('hooks') or {})
    for event in list(hooks):
        kept = [g for g in hooks[event] if not (isinstance(g, dict) and managed_hook_group(g))]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    for event, groups in additions.items():
        hooks[event] = list(hooks.get(event, [])) + groups
    if hooks:
        document['hooks'] = hooks
    else:
        document.pop('hooks', None)
    return document


def _merge_events(existing, additions, tool_name, is_managed):
    events = {}
    for event, entries in existing.items():
        if not isinstance(entries, list):
            events[event] = entries  # Preserve malformed, unrelated sections.
            continue
        kept = [entry for entry in entries if not (isinstance(entry, dict) and is_managed(entry))]
        if kept:
            events[event] = kept
    for event, entries in additions.items():
        current = events.get(event)
        if current is None:
            current = []
        if not isinstance(current, list):
            raise ValueError(f'{tool_name} hook event {event} must be a list')
        events[event] = current + list(entries)
    return events


def merge_cursor_hooks(document, additions):
    """Merge hook definitions into a Cursor hooks.json, preserving its version and other hooks.

    Cursor definitions are flat per-event command entries (no nested hooks
    list). A fresh file gets ``version: 1``; an existing version is never
    downgraded. Removing our hooks never removes the file's other content.
    """
    document = dict(document)
    hooks = document.get('hooks')
    if hooks is None:
        hooks = {}
    elif not isinstance(hooks, dict):
        raise ValueError('Cursor hooks configuration must be an object')
    hooks = _merge_events(hooks, additions, 'Cursor', lambda entry: managed_hook_command(entry.get('command', '')))
    if hooks:
        document['hooks'] = hooks
    else:
        document.pop('hooks', None)
    if 'version' not in document:
        document['version'] = 1
    return document


def merge_zcode_hooks(document, additions):
    """Merge hook events into a ZCode config file, preserving MCP servers and other settings.

    ZCode reads hooks from ``hooks.events`` and requires ``hooks.enabled``;
    project-level hooks are ignored, so this merge is only used for the user
    config file.  Installing sets ``enabled``; removing our hooks never flips
    it back, because the previous value is not ours to restore.
    """
    document = dict(document)
    had_hooks = 'hooks' in document
    hooks = document.get('hooks')
    if hooks is None:
        hooks = {}
    elif not isinstance(hooks, dict):
        raise ValueError('ZCode hooks configuration must be an object')
    hooks = dict(hooks)
    events = hooks.get('events')
    if events is None:
        events = {}
    elif not isinstance(events, dict):
        raise ValueError('ZCode hook events must be an object')
    events = _merge_events(events, additions, 'ZCode', managed_hook_group)
    if events:
        hooks['events'] = events
    else:
        hooks.pop('events', None)
    if additions:
        hooks['enabled'] = True
    if hooks or had_hooks:
        document['hooks'] = hooks
    else:
        document.pop('hooks', None)
    return document


def _load(path):
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding='utf-8') or '{}')
    if not isinstance(document, dict):
        raise ValueError('Existing settings are not a JSON object')
    return document


def _merge_json(tool, document, additions):
    if tool == 'cursor':
        return merge_cursor_hooks(document, additions)
    if tool == 'zcode':
        return merge_zcode_hooks(document, additions)
    return merge_hooks(document, additions)


def install_settings(path, profile_path, tool, standby):
    if tool == 'kimi-code':
        fragment = kimi_wake_hooks_text(profile_path, standby)
        _write_text_settings(path, merge_kimi_wake_hooks(_load_text(path), fragment))
        return ['SessionStart', 'Stop']
    config = hook_config(profile_path, tool, standby)
    document = _merge_json(tool, _load(path), config)
    _write_text_settings(path, json.dumps(document, indent=2) + '\n')
    return sorted(config)


def disable_settings(path, tool):
    if not path.exists():
        return False
    if tool == 'kimi-code':
        before = _load_text(path)
        after = merge_kimi_wake_hooks(before, '')
        if before == after:
            return False
        _write_text_settings(path, after)
    else:
        before = _load(path)
        after = _merge_json(tool, before, {})
        if before == after:
            return False
        _write_text_settings(path, json.dumps(after, indent=2) + '\n')
    return True
