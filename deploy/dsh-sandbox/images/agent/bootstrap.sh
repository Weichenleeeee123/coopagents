#!/bin/sh
set -eu
umask 077
# Run inside the image only. Package installation and verified pins belong to the builder.
# No network access, login setup, secrets, service enablement or VM creation occurs here.
[ "$(id -u)" = 0 ] || exit 1
: "${RUN_ID:?required non-sensitive run alias}"
: "${AGENT_ALIAS:?required non-sensitive member alias}"
case "$RUN_ID:$AGENT_ALIAS" in *[!a-zA-Z0-9_.:-]*|:*|*:) exit 1 ;; esac
for account in dsh dsh-gateway; do
  if ! id "$account" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "/var/lib/$account" --shell /usr/sbin/nologin "$account"
  fi
done
install -d -m 0700 -o dsh -g dsh /var/lib/dsh
install -d -m 0700 -o dsh-gateway -g dsh-gateway /var/lib/dsh-gateway
DSH_HOME="/var/lib/dsh/profiles/$RUN_ID/$AGENT_ALIAS"
install -d -m 0700 -o dsh -g dsh "/var/lib/dsh/profiles" "/var/lib/dsh/profiles/$RUN_ID" "$DSH_HOME" "$DSH_HOME/cache" "$DSH_HOME/worktree"
if [ -e "$DSH_HOME/cordis.patch.yml" ]; then
  # Existing configuration is preserved; the operator must review a merge separately.
  exit 0
fi
# noclobber protects an existing file, including concurrent reruns.
(set -C; cat > "$DSH_HOME/cordis.patch.yml" <<'PATCH'
- insert:
  - id: "sandbox-local-member"
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: "coopagents"
      transport: "streamable-http"
      url: "http://127.0.0.1:8769/mcp"
PATCH
)
chown dsh:dsh "$DSH_HOME/cordis.patch.yml"
chmod 0600 "$DSH_HOME/cordis.patch.yml"
