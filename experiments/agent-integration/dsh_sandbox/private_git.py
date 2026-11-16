"""Role-isolated synthetic Git repositories and restricted SSH commands."""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROLES = ("frontend", "backend", "integration")
_COMMAND = re.compile(r"^git-(upload-pack|receive-pack) '([A-Za-z0-9_-]+\.git)'$")


def _git(*args, cwd=None):
    return subprocess.run(["git", *map(str, args)], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=30)


def _role(value):
    if value not in ROLES:
        raise ValueError("unknown registered Git role")
    return value


def prepare_private_git(runtime_root, role_projects):
    """Create one role-only bare repo, import its fixture branch, and install hooks."""
    if set(role_projects) != set(ROLES):
        raise ValueError("exactly the registered role repositories are required")
    root = Path(runtime_root).expanduser().resolve()
    repos = {}
    for role in ROLES:
        role = _role(role)
        project = Path(role_projects[role]).expanduser().resolve()
        repo = root / (role + ".git")
        repo.parent.mkdir(parents=True, exist_ok=True)
        _git("init", "--bare", "--quiet", "--template=", f"--initial-branch=agent/{role}", repo)
        _git("--git-dir", repo, "fetch", "--quiet", str(project), f"refs/heads/agent/{role}:refs/heads/agent/{role}")
        _git("--git-dir", repo, "symbolic-ref", "HEAD", f"refs/heads/agent/{role}")
        hook = repo / "hooks" / "pre-receive"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(_pre_receive_hook(role), encoding="utf-8", newline="\n")
        if os.name != "nt":
            hook.chmod(0o755)
        repos[role] = repo
    return repos


def _pre_receive_hook(role):
    # Git supplies old/new/ref triples on stdin. Check ancestry for every update.
    return "#!/bin/sh\n" + (
        "while read old new ref; do\n"
        f"  [ \"$ref\" = \"refs/heads/agent/{role}\" ] || {{ echo 'ref denied' >&2; exit 1; }}\n"
        "  [ \"$new\" != 0000000000000000000000000000000000000000 ] || { echo 'deletion denied' >&2; exit 1; }\n"
        "  if [ \"$old\" != 0000000000000000000000000000000000000000 ]; then\n"
        "    git merge-base --is-ancestor \"$old\" \"$new\" || { echo 'non-fast-forward denied' >&2; exit 1; }\n"
        "  fi\n"
        "done\n"
    )


def command_for(role, runtime_root, original_command):
    """Resolve an SSH_ORIGINAL_COMMAND to a fixed executable and role repo path."""
    role = _role(role)
    match = _COMMAND.fullmatch(original_command or "")
    if not match or match.group(2) != role + ".git":
        raise ValueError("Git command is not permitted for this role")
    operation = match.group(1)
    repo = (Path(runtime_root).expanduser().resolve() / (role + ".git")).resolve()
    if not repo.is_dir() or repo.parent != Path(runtime_root).expanduser().resolve():
        raise ValueError("role repository is unavailable")
    return ["git", "--git-dir", str(repo), operation]


def sshd_config_fragment(runtime_root, bind_address):
    """Emit private-listener config; provision one Unix account and SSH key per role."""
    try:
        address = ipaddress.ip_address(bind_address)
    except ValueError as exc:
        raise ValueError("SSH listener must use an explicit private IP") from exc
    private = ((address.version == 4 and any(address in network for network in (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"))))
        or (address.version == 6 and address in ipaddress.ip_network("fc00::/7")))
    if not private or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError("SSH listener must use an explicit private IP")
    helper = str(Path(__file__).resolve())
    python = shlex.quote(sys.executable)
    helper = shlex.quote(helper)
    root = str(Path(runtime_root).expanduser().resolve())
    if any(character in root for character in "\r\n"):
        raise ValueError("invalid runtime root")
    root = shlex.quote(root)
    blocks = ["# Provision one Unix account per role; install only that member's public key in its authorized_keys.",
              "# Keep private keys with members; do not share accounts or keys.",
              f"ListenAddress {address}", "PasswordAuthentication no", "PubkeyAuthentication yes",
              "AllowUsers " + " ".join(f"git-{role}" for role in ROLES)]
    for role in ROLES:
        blocks.extend((f"Match User git-{role}", f"    ForceCommand {python} {helper} --role {role} --root {root}",
                       "    DisableForwarding yes", "    PermitTTY no", "    X11Forwarding no", "    AllowAgentForwarding no", ""))
    return "\n".join(blocks).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--root", default=os.environ.get("DSH_PRIVATE_GIT_ROOT"))
    args = parser.parse_args(argv)
    try:
        role = _role(args.role)
        if not args.root:
            raise ValueError("runtime root is not configured")
        command = command_for(role, args.root, os.environ.get("SSH_ORIGINAL_COMMAND"))
        os.execvp(command[0], command)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("private Git command denied", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
