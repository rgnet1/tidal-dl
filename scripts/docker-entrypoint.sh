#!/usr/bin/env bash
# Entrypoint for the Tidal DL Pro web container.
#
# Responsibilities:
#   - Remap the in-container "app" user to the host-provided PUID/PGID so that
#     bind-mounted volumes (./config, ./downloads) remain writable regardless of
#     the host user running docker compose.
#   - Ensure /config and /downloads exist and are owned by the runtime user so
#     the app can persist settings.json and token.json across container
#     restarts and image rebuilds.
#   - Drop privileges to that user before exec'ing uvicorn.
#
# Controlled via env vars:
#   PUID   - numeric UID to run as (default 1000)
#   PGID   - numeric GID to run as (default 1000)
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Re-assign the app group/user to the requested IDs if they differ.
current_gid="$(id -g app)"
current_uid="$(id -u app)"

if [[ "${current_gid}" != "${PGID}" ]]; then
    groupmod -o -g "${PGID}" app
fi
if [[ "${current_uid}" != "${PUID}" ]]; then
    usermod -o -u "${PUID}" app >/dev/null
fi

mkdir -p /config /downloads

# /config tends to be tiny (settings.json, token.json) so always recursively
# fix ownership to keep things consistent with PUID/PGID.
chown -R "${PUID}:${PGID}" /config || true

# /downloads may be huge; only touch the top-level directory to avoid
# thrashing large library trees on every start.
if [[ "$(stat -c '%u:%g' /downloads)" != "${PUID}:${PGID}" ]]; then
    chown "${PUID}:${PGID}" /downloads || true
fi

exec gosu app "$@"
