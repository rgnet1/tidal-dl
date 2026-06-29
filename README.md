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

## Quick start (Docker Hub)

The published image is **[`rgnet1/tidal-dl:latest`](https://hub.docker.com/r/rgnet1/tidal-dl)** on Docker Hub. You do **not** need to clone this repo or build anything locally.

### Option A — Docker Compose (recommended)

Create a folder for persistent data, download the compose file, and start:

```bash
mkdir -p tidal-dl-pro/config tidal-dl-pro/downloads
cd tidal-dl-pro

curl -fsSLO https://raw.githubusercontent.com/rgnet1/tidal-dl/master/docker-compose.yml

docker compose pull
docker compose up -d
```

Open **http://localhost:8001**, click **Login to TIDAL**, complete OAuth, then search or browse your library.

To update to the latest image later:

```bash
docker compose pull && docker compose up -d
```

### Option B — `docker pull` and `docker run`

```bash
docker pull rgnet1/tidal-dl:latest

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

Open **http://localhost:8001**.

### Common commands

| Action | Command |
| --- | --- |
| View logs | `docker compose logs -f tidal-dl-pro-web` |
| Stop | `docker compose down` |
| Update image | `docker compose pull && docker compose up -d` |
| Check health | `curl -sf http://localhost:8001/api/status` |

## Docker Compose file

The repo's `docker-compose.yml` pulls the published image — it does **not** build locally:

```yaml
services:
  tidal-dl-pro-web:
    image: rgnet1/tidal-dl:latest   # pulled from Docker Hub
    pull_policy: always             # check for updates on every `docker compose up`
    container_name: tidal-dl-pro-web
    ports:
      - "${TIDAL_DL_PRO_PORT:-8001}:8000"
    environment:
      PUID: "${PUID:-1000}"
      PGID: "${PGID:-1000}"
    volumes:
      - ./config:/config
      - ./downloads:/downloads
    restart: unless-stopped
```

**Image:** `rgnet1/tidal-dl:latest` — always use the `:latest` tag unless you are pinning a specific version.

**Port mapping:** the app listens on port `8000` inside the container and is published on host port **8001** by default. Override with `TIDAL_DL_PRO_PORT`:

```bash
TIDAL_DL_PRO_PORT=8080 docker compose up -d
```

**Volumes:**

| Host path | Container path | What it stores |
| --- | --- | --- |
| `./config` | `/config` | OAuth tokens, settings, and per-engine config mirrors |
| `./downloads` | `/downloads` | Downloaded audio and video files |

Both directories must exist (or are created with `mkdir -p`) before first run. Data survives `docker compose down` and image updates as long as these bind mounts stay in place.

**Health check:** Docker polls `/api/status` every 30 seconds. If the container is unhealthy, check logs with `docker compose logs tidal-dl-pro-web`.

## Configuration

Set these in a `.env` file next to `docker-compose.yml`, or export them in your shell:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIDAL_DL_PRO_PORT` | `8001` | Host port mapped to the web UI |
| `PUID` | `1000` | UID the container runs as — set to `id -u` on Linux if files end up owned by root |
| `PGID` | `1000` | GID to run as — set to `id -g` on Linux |
| `ACTIVE_ENGINE` | _(unset)_ | Force engine on boot: `tidal-dl-ng` or `tiddl`; overridden once you change it in Settings |

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

```bash
TIDAL_DL_PRO_PORT=8002 docker compose up -d
```

**Wrong file ownership on `./config` or `./downloads`**

```bash
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

**Container won't start**

```bash
docker compose logs tidal-dl-pro-web
docker compose pull && docker compose up -d
```

**Pulling a stale image**

Force Docker to fetch the latest from Hub:

```bash
docker compose pull --ignore-buildable
docker compose up -d
```

**FLAC extraction failed**

FFmpeg is included in the image. If extraction still fails, check the download logs in the web UI queue panel.

## Building locally (developers)

Only needed if you are modifying the source code. Clone the repo and use `docker-compose.build.yml`:

```bash
git clone https://github.com/rgnet1/tidal-dl.git
cd tidal-dl

mkdir -p config downloads
docker compose -f docker-compose.build.yml up -d --build
```

## Disclaimer

- For educational purposes only.
- Do not use this to distribute or pirate music.
- It may be illegal to use this application in your country.

## Credits

Built on [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng) by @exislow.
