# Tidal DL Pro

[![Release](https://img.shields.io/github/v/release/rgnet1/tidal-dl)](https://github.com/rgnet1/tidal-dl/releases)
[![Docker](https://img.shields.io/docker/v/rgnet1/tidal-dl/latest)](https://hub.docker.com/r/rgnet1/tidal-dl)
[![License](https://img.shields.io/github/license/rgnet1/tidal-dl)](https://github.com/rgnet1/tidal-dl/blob/master/LICENSE)

**Tidal DL Pro** is a browser-based TIDAL downloader. Run it in Docker, sign in to TIDAL once, then search, browse your library, and download from any device on your network.

**A paid TIDAL subscription is required.** Audio quality goes up to Hi-Res Lossless (24-bit / 192 kHz) when available.

## Features

- **Search** tracks, albums, artists, playlists, and videos — or paste a TIDAL URL
- **Your TIDAL library** — playlists, mixes, and favorites in the sidebar
- **Download queue** with live progress over WebSocket
- **Settings** for download engine, audio/video quality, lyrics, and FLAC extraction
- **Dark / light mode**

## Quick start

```bash
git clone https://github.com/rgnet1/tidal-dl.git
cd tidal-dl

mkdir -p config downloads
docker compose up -d --build
```

Open **http://localhost:8001** (default host port), click **Login to TIDAL**, complete OAuth, then search or browse your library.

Or use the helper script:

```bash
./scripts/start-web.sh
```

### Common commands

| Action | Command |
| --- | --- |
| View logs | `docker compose logs -f tidal-dl-pro-web` |
| Stop | `docker compose down` |
| Rebuild after code changes | `docker compose up -d --build` |
| Check health | `curl -sf http://localhost:8001/api/status` |

## Docker Compose

The project ships with `docker-compose.yml` at the repo root. It defines one service:

```yaml
services:
  tidal-dl-pro-web:
    build: .                    # build image from the Dockerfile in this repo
    container_name: tidal-dl-pro-web
    ports:
      - "${TIDAL_DL_PRO_PORT:-8001}:8000"   # host:container
    environment:
      PUID: "${PUID:-1000}"     # match your host user for file ownership
      PGID: "${PGID:-1000}"
    volumes:
      - ./config:/config        # TIDAL login + app settings (persisted)
      - ./downloads:/downloads  # downloaded media (persisted)
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/api/status"]
```

**Service name:** `tidal-dl-pro-web`

**Port mapping:** the app listens on port `8000` inside the container. By default it is published on host port **8001** so it does not clash with other services. Override with `TIDAL_DL_PRO_PORT` in a `.env` file or shell:

```bash
TIDAL_DL_PRO_PORT=8080 docker compose up -d
```

**Volumes:**

| Host path | Container path | What it stores |
| --- | --- | --- |
| `./config` | `/config` | OAuth tokens, settings, and per-engine config mirrors |
| `./downloads` | `/downloads` | Downloaded audio and video files |

Both directories are created automatically on first run. Data survives `docker compose down` and image rebuilds as long as these bind mounts stay in place.

**Health check:** Docker polls `/api/status` every 30 seconds. If the container is unhealthy, check logs with `docker compose logs tidal-dl-pro-web`.

### Run the published image (no local build)

Production images are pushed to Docker Hub as [`rgnet1/tidal-dl:latest`](https://hub.docker.com/r/rgnet1/tidal-dl) on every merge to `master` (except README-only changes).

```bash
mkdir -p config downloads
docker run -d \
  --name tidal-dl-pro-web \
  -p 8001:8000 \
  -e PUID=1000 \
  -e PGID=1000 \
  -v "$(pwd)/config:/config" \
  -v "$(pwd)/downloads:/downloads" \
  --restart unless-stopped \
  rgnet1/tidal-dl:latest
```

Or use `docker-compose.release.yml`, which pulls the published image instead of building locally:

```bash
APP_IMAGE=rgnet1/tidal-dl:latest docker compose -f docker-compose.release.yml up -d
```

## Configuration

Set these in a `.env` file next to `docker-compose.yml`, or export them in your shell:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIDAL_DL_PRO_PORT` | `8001` | Host port mapped to the web UI |
| `PUID` | `1000` | UID the container runs as — set to `id -u` on Linux if files end up owned by root |
| `PGID` | `1000` | GID to run as — set to `id -g` on Linux |
| `ACTIVE_ENGINE` | _(unset)_ | Force engine on boot: `tidal-dl-ng` or `tiddl`; overridden once you change it in Settings |

Inside the container (set automatically by compose, rarely changed manually):

| Variable | Default | Purpose |
| --- | --- | --- |
| `XDG_CONFIG_HOME` | `/config` | Where settings and tokens are stored |
| `DOWNLOAD_PATH` | `/downloads` | Default download folder for new installs |
| `TIDDL_PATH` | `/config/tiddl` | tiddl engine config mirror |

On first boot the entrypoint remaps the container user to `PUID:PGID` and chowns `/config`. Your TIDAL OAuth token lives at `./config/tidal_dl_ng/token.json` on the host.

## Web UI settings

Open the gear icon (top-right):

- **Download engine** — `tidal-dl-ng` (default; full library + mixes) or `tiddl` (experimental). Tokens are mirrored so you can switch without logging in again.
- **Audio quality** — Low up to Hi-Res Lossless (requires TIDAL HiFi Plus)
- **Video quality** — 360p–1080p
- **Skip existing**, **download delay**, and concurrency
- **Metadata** — embed lyrics, save `.lrc` files, FLAC extraction (FFmpeg is bundled in the image)

## API

Interactive docs: **http://localhost:8001/docs**

Key endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Health and auth state |
| `POST` | `/api/auth/login` | Start TIDAL OAuth |
| `POST` | `/api/search` | Search TIDAL |
| `GET` | `/api/library/lists` | Playlists, mixes, favorites |
| `POST` | `/api/download/add` | Queue items |
| `POST` | `/api/download/start` | Start the queue |
| `GET`/`PUT` | `/api/settings` | Read or update settings |
| WebSocket | `/ws` | Live download progress |

## Troubleshooting

**Port already in use**

Another service is bound to port 8001. Pick a different port:

```bash
TIDAL_DL_PRO_PORT=8002 docker compose up -d
```

**Wrong file ownership on `./config` or `./downloads`**

Set `PUID` and `PGID` to your host user, then restart:

```bash
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

**Container won't start**

```bash
docker compose logs tidal-dl-pro-web
docker compose build --no-cache && docker compose up -d
```

**WebSocket errors / `/ws` returns 404**

Rebuild the image — the Dockerfile installs the WebSocket stack explicitly:

```bash
docker compose build --no-cache && docker compose up -d
```

**FLAC extraction failed**

FFmpeg is included in the image. If extraction still fails, check the download logs in the web UI queue panel.

## Disclaimer

- For educational purposes only.
- Do not use this to distribute or pirate music.
- It may be illegal to use this application in your country.

## Credits

Built on [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng) by @exislow.
