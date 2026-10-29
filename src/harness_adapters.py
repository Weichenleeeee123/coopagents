"""Safe, capability-reported MCP configuration for supported coding harnesses.

The adapters only edit explicit project configuration files. They never inspect
agent conversations or copy private credentials into a config file.
"""
from copy import deepcopy
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import os
import re
from urllib.parse import urlsplit


SUPPORTED_HARNESSES = ('cursor', 'opencode', 'pi', 'kimi-code', 'zcode')


class ConfigConflict(ValueError):
    """An existing MCP entry differs from the Coopagents entry being installed."""


@dataclass(frozen=True)
class HarnessSpec:
    harness: str
    config_path: str
    format: str
    config_scope: str = 'project'
    native_hook: str = 'unknown'
    idle_wake: str = 'unsupported'
    notes: str = ''


SPECS = {
    'cursor': HarnessSpec('cursor', '.cursor/mcp.json', 'mcpServers', native_hook='unknown',
                          notes='Project MCP configuration is supported; Cursor hooks are not verified here.'),
    'opencode': HarnessSpec('opencode', 'opencode.json', 'opencode', native_hook='unknown',
                            notes='Local and remote MCP servers use the opencode mcp object.'),
    'pi': HarnessSpec('pi', '.pi/mcp.json', 'mcpServers', native_hook='unsupported',
                      notes='Pi project MCP configuration is supported; extension lifecycle is not installed by this adapter.'),
    'kimi-code': HarnessSpec('kimi-code', '.kimi-code/mcp.json', 'mcpServers', native_hook='unsupported',
                             notes='Kimi Code project MCP configuration is supported; ACP is not required for MCP.'),
    'zcode': HarnessSpec('zcode', '.zcode/config.json', 'zcode', native_hook='unsupported',
                         notes='ZCode workspace config uses mcp.servers; project hooks are not claimed.'),
}


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('%s must be a nonempty string' % name)
    return value.strip()


def _args(args):
    if not isinstance(args, (list, tuple)) or any(not isinstance(item, str) for item in args):
        raise ValueError('MCP arguments must be strings')
    return list(args)


def _remote_url(url):
    url = _string(url, 'MCP URL')
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    loopback = host in ('127.0.0.1', 'localhost', '::1')
    if not (parsed.scheme == 'https' or (parsed.scheme == 'http' and loopback)):
        raise ValueError('MCP URL must be HTTPS or loopback HTTP')
    if parsed.username or parsed.password or parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('MCP URL is invalid')
    if any(char.isspace() for char in url) or len(url) > 2048:
        raise ValueError('MCP URL is invalid')
    return url


def _env_name(value):
    value = _string(value, 'Token environment variable')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('Token environment variable must be a shell variable name')
    return value


class HarnessAdapter:
    def __init__(self, spec):
        self.spec = spec

    def capabilities(self, project_root=None, detected_version=None):
        root = Path(project_root).resolve() if project_root is not None else None
        return {
            'harness': self.spec.harness,
            'version': detected_version if isinstance(detected_version, str) else 'unknown',
            'mcp': 'supported',
            'config_scope': self.spec.config_scope,
            'config_path': str(root / self.spec.config_path) if root else self.spec.config_path,
            'project_context': 'supported',
            'native_hook': self.spec.native_hook,
            'idle_wake': self.spec.idle_wake,
            'install_status': 'available',
            'notes': self.spec.notes,
        }

    def _entry(self, command, args):
        command = _string(command, 'MCP command')
        args = _args(args)
        if self.spec.format == 'opencode':
            return {'type': 'local', 'command': [command, *args], 'enabled': True}
        return {'command': command, 'args': args}

    def _remote_entry(self, url, token_env):
        url = _remote_url(url)
        token_env = _env_name(token_env)
        if self.spec.harness == 'kimi-code':
            return {'url': url, 'bearerTokenEnvVar': token_env}
        placeholder = '${env:%s}' % token_env if self.spec.harness in ('cursor', 'zcode') else '${%s}' % token_env
        headers = {'Authorization': 'Bearer ' + placeholder}
        if self.spec.format == 'opencode':
            return {'type': 'remote', 'url': url, 'headers': headers, 'enabled': True}
        return {'url': url, 'headers': headers}

    def _container(self, document):
        document = deepcopy(document)
        if not isinstance(document, dict):
            raise ValueError('MCP configuration must be a JSON object')
        if self.spec.format == 'zcode':
            mcp = document.get('mcp')
            if mcp is None:
                mcp = {}
                document['mcp'] = mcp
            if not isinstance(mcp, dict):
                raise ValueError('ZCode mcp configuration must be an object')
            servers = mcp.get('servers')
            if servers is None:
                servers = {}
                mcp['servers'] = servers
            if not isinstance(servers, dict):
                raise ValueError('ZCode mcp.servers must be an object')
            return document, servers
        key = 'mcp' if self.spec.format == 'opencode' else 'mcpServers'
        servers = document.get(key)
        if servers is None:
            servers = {}
            document[key] = servers
        if not isinstance(servers, dict):
            raise ValueError('%s must be an object' % key)
        return document, servers

    def _merge_entry(self, document, name, entry):
        name = _string(name, 'MCP server name')
        document, servers = self._container(document)
        current = servers.get(name)
        if current is not None and current != entry:
            raise ConfigConflict('MCP server %s already exists with a different configuration' % name)
        if current is None:
            servers[name] = entry
        return document

    def merge(self, document, name, command, args):
        return self._merge_entry(document, name, self._entry(command, args))

    def merge_remote(self, document, name, url, token_env='COOPAGENTS_AGENT_TOKEN'):
        return self._merge_entry(document, name, self._remote_entry(url, token_env))

    def config_target(self, project_root):
        root = Path(project_root).resolve()
        if not root.is_dir():
            raise ValueError('Project root must be an existing directory')
        return root / self.spec.config_path

    @staticmethod
    def _safe_target(target, project_root):
        root = Path(project_root).resolve()
        target = Path(target)
        if target.exists() and target.is_symlink():
            raise ValueError('MCP configuration path must not be a symlink')
        resolved = target.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('MCP configuration path must remain inside the project root')
        current = root
        for part in resolved.relative_to(root).parts[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError('MCP configuration parent must not be a symlink')
        return resolved

    def install(self, target, name, command, args, *, project_root):
        target = self._safe_target(target, project_root)
        document = {}
        if target.exists():
            try:
                document = json.loads(target.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError('Existing MCP configuration is not valid JSON') from error
        merged = self.merge(document, name, command, args)
        if target.exists() and merged == document:
            return {'status': 'already_configured', 'path': str(target), 'capabilities': self.capabilities(project_root)}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return {'status': 'installed', 'path': str(target), 'capabilities': self.capabilities(project_root)}

    def install_remote(self, target, name, url, *, token_env='COOPAGENTS_AGENT_TOKEN', project_root):
        target = self._safe_target(target, project_root)
        document = {}
        if target.exists():
            try:
                document = json.loads(target.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError('Existing MCP configuration is not valid JSON') from error
        merged = self.merge_remote(document, name, url, token_env)
        if target.exists() and merged == document:
            status = 'already_configured'
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            status = 'installed'
        return {'status': status, 'path': str(target), 'capabilities': self.capabilities(project_root)}

    def plan(self, project_root, server_name='coopagents', service_url=None, token_env='COOPAGENTS_AGENT_TOKEN'):
        root = Path(project_root).resolve()
        plan = self.capabilities(root) | {'server_name': _string(server_name, 'MCP server name')}
        if service_url is not None:
            plan['entry'] = self._remote_entry(service_url, token_env)
            plan['transport'] = 'streamable_http'
        else:
            plan['entry'] = None
            plan['transport'] = 'manual'
            plan['notes'] = 'Pass --service-url to generate an installable authenticated MCP entry.'
        return plan


def adapter_for(name):
    if name not in SPECS:
        raise ValueError('Unsupported harness: %s' % name)
    return HarnessAdapter(SPECS[name])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Plan or install a Coopagents MCP entry for a coding harness')
    parser.add_argument('--harness', choices=SUPPORTED_HARNESSES, required=False)
    parser.add_argument('--project', default='.', help='Existing project root')
    parser.add_argument('--name', default='coopagents')
    parser.add_argument('--service-url', help='HTTPS or loopback HTTP MCP endpoint')
    parser.add_argument('--token-env', default='COOPAGENTS_AGENT_TOKEN')
    parser.add_argument('--install', action='store_true', help='Write the project config after validation')
    parser.add_argument('--list', action='store_true', help='List supported harnesses')
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({'harnesses': [adapter_for(name).capabilities() for name in SUPPORTED_HARNESSES]}, ensure_ascii=False))
        return 0
    if not args.harness:
        parser.error('--harness is required unless --list is used')
    root = Path(args.project).resolve()
    adapter = adapter_for(args.harness)
    if args.install:
        if not args.service_url:
            parser.error('--service-url is required for installation; no local stdio runner is bundled')
        target = adapter.config_target(root)
        if args.service_url:
            result = adapter.install_remote(target, args.name, args.service_url,
                                            token_env=args.token_env, project_root=root)
    else:
        result = adapter.plan(root, args.name, args.service_url, args.token_env)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
