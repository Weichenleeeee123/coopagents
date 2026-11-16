#!/bin/sh
set -eu
umask 077
# Local image account/directory preparation only. Services remain stopped until review.
[ "$(id -u)" = 0 ] || exit 1
for account in sandbox-coordinator sandbox-proxy sandbox-git sandbox-evidence; do
  if ! id "$account" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "/var/lib/$account" --shell /usr/sbin/nologin "$account"
  fi
  install -d -m 0700 -o "$account" -g "$account" "/var/lib/$account"
done
# No DSH installation, participant profile, credential retrieval or login service.
