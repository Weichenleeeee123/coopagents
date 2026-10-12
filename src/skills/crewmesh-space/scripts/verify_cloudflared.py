"""Download a pinned official Cloudflare asset only with its published digest."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request


def install(tag, asset_name, destination):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Use an explicit Cloudflare release version')
    if not re.fullmatch(r'cloudflared-[A-Za-z0-9_.-]+', asset_name):
        raise ValueError('Invalid Cloudflare asset name')
    target = Path(destination).absolute()
    if target.exists():
        raise FileExistsError('Destination already exists; choose a new path')
    api = 'https://api.github.com/repos/cloudflare/cloudflared/releases/tags/' + tag
    req = urllib.request.Request(api, headers={'Accept':'application/vnd.github+json','User-Agent':'crewmesh-space'})
    with urllib.request.urlopen(req, timeout=15) as response:
        release = json.loads(response.read(2_000_000))
    asset = next(a for a in release['assets'] if a['name'] == asset_name)
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Official release asset lacks a SHA-256 digest; do not install')
    expected = 'https://github.com/cloudflare/cloudflared/releases/download/' + tag + '/' + asset_name
    if asset['browser_download_url'] != expected:
        raise ValueError('Unexpected official asset URL')
    # GitHub release delivery redirects to GitHub-owned signed CDN storage; no
    # credentials are sent. The official API digest verifies the final bytes.
    with urllib.request.urlopen(expected, timeout=30) as response:
        binary = response.read(100_000_001)
    if len(binary) > 100_000_000 or hashlib.sha256(binary).hexdigest() != digest[7:]:
        raise ValueError('Cloudflare asset checksum mismatch')
    from crewmesh.spaces import checked_path, private_directory, protect
    target = checked_path(target)
    private_directory(target.parent)
    with target.open('xb') as stream:
        protect(target)
        stream.write(binary)
    if target.suffix != '.exe':
        target.chmod(0o700)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--asset', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({'verified_executable':str(install(args.tag, args.asset, args.destination))}))
    except Exception:
        parser.exit(1, 'Official Cloudflare asset verification failed; retain existing files and inspect release metadata.\n')


if __name__ == '__main__':
    main()
