---
name: tidal-dl-pro-local-http-api
description: Documents the Tidal DL Pro FastAPI HTTP and WebSocket surface for automation on a LAN (default port 8000), including how to queue and start a single-track download. Use when the user or an LLM agent must discover endpoints, payloads, auth flow, queue control, search, library, download a song, or settings without reading the Python source.
---

# Tidal DL Pro — local HTTP API (LLM / automation)

Single FastAPI app (`web.main:app`) serves **HTML** at `/` and **JSON** under `/api/*`. Default bind: **`0.0.0.0:8000`** (see `web/main.py` and Docker compose).

## Base URL

- **This machine:** `http://127.0.0.1:8000` or `http://localhost:8000`
- **Another device on the LAN:** `http://<host-ip>:8000` (firewall must allow TCP 8000)

No API key: security is **network exposure** + **TIDAL OAuth session** stored under config (see repo `docker-compose.yml` and the README's "Docker (web UI)" section).

## Content type

- JSON bodies: `Content-Type: application/json`
- Responses: JSON unless noted

## Authentication flow (browser-style; automatable)

1. **`GET /api/status`** — see if already logged in.
2. **`POST /api/auth/login`** — start OAuth.
   - If already authenticated: `{"authenticated": true}`
   - Else: `{"authenticated": false, "login_url": "<https URL>", "expires_in": <int>}` — open `login_url` for the user (or headless browser).
3. **`POST /api/auth/finalize`** — poll every few seconds until TIDAL completes login.
   - Returns `{"authenticated": true|false}` (`false` while still pending is normal).
4. **`POST /api/auth/logout`** — clears session; returns `{"ok": true}`.

Most catalog endpoints return **401** if not authenticated.

## Engine selection

- **`GET /api/status`** includes `"engine": "tidal-dl-ng" | "tiddl"`.
- Active engine comes from persisted settings or env **`ACTIVE_ENGINE`** (`tidal-dl-ng` or `tiddl`). Engines share unified auth in `/config` when using the Docker layout.

---

## HTTP reference

### `GET /api/status`

**200** — `{ "authenticated": bool, "queued": int, "engine": "tidal-dl-ng" | "tiddl" }`

### `POST /api/auth/login`

**200** — login payload as in Authentication flow above.

### `POST /api/auth/finalize`

**200** — `{ "authenticated": bool }`  
**400** — no login in progress

### `POST /api/auth/logout`

**200** — `{ "ok": true }`

### `POST /api/search`

**Body:** `{ "query": string, "media_type": string }`  
- `media_type` (tidal-dl-ng path): **`Track`**, **`Album`**, **`Playlist`**, **`Artist`**, **`Video`** (case-insensitive in engine; sent as given from UI).  
- If `query` is a **TIDAL URL**, the server resolves it and returns **one** matching item when possible.

**200** — `{ "results": [ ... ] }`  
**401** — not authenticated  
**502** — upstream search failure

**Item shape** (typical keys; omit if absent): `id`, `title`, `type` (e.g. `Track`, `Album`), `artist`, `album`, `duration`, `explicit`, `image_url`, `quality_badge`, `num_tracks`, `description`, `available`.

### `GET /api/library/lists`

**200** — `{ "playlists": [...], "mixes": [...], "favorites": [...] }`  
Each list entry is an item dict (`id`, `title`, `type`, …). Favorites are synthetic rows with ids like `fav_tracks`, `fav_albums`, `fav_artists`, `fav_videos`.  
**401** / **502** as above.

### `GET /api/library/items/{list_id}`

Path param **`list_id`**: playlist id, mix id, album id (numeric string), or favorite id (`fav_tracks`, …).

**200** — `{ "items": [ ... ] }`  
**400** — unknown favorite key  
**404** — list not found  
**401** / **502** as above.

### `POST /api/download/add`

**Body:** `{ "media_id": string, "media_type": string, "engine": string | null }`

- **`media_id`**: single id or **comma-separated** ids for batch add.
- **`media_type`**: tidal class style, e.g. `track`, `album`, `playlist`, `video`, `mix` (engine resolves; align with UI which lowercases).
- **`engine`**: optional `"tidal-dl-ng"` or `"tiddl"`; default is active engine from settings.

**200** — `{ "added": int, "queue_size": int }`  
**400** — unknown engine  
**401** — not authenticated

Queue entry shape: `id`, `title`, `type`, `status` (`waiting` | `downloading` | `finished` | `failed`), `progress` (0–100 or `-1` on failure), `error` (string or null), `engine`.

### `GET /api/download/queue`

**200** — `{ "queue": [ ... ] }`

### `POST /api/download/start`

Starts background processing of **all** `waiting` items (respects concurrency from settings). Safe to call if already running; empty queue returns a message.

**200** — `{ "message": string }` (e.g. queue empty or processing started)

### `DELETE /api/download/queue`

**200** — `{ "ok": true }` — clears queue and resets client “downloading” state when UI polls.

### `GET /api/settings`

**200** — settings object: `download_base_path`, `quality_audio`, `quality_video`, `skip_existing`, `download_delay`, `lyrics_embed`, `lyrics_file`, `video_download`, `extract_flac`, `downloads_concurrent_max`, `active_engine`, path template strings (`path_template_track`, …), `use_single_path_template`.

### `PUT /api/settings`

**Body:** full settings payload matching **`SettingsPayload`** in `web/main.py` (same keys as `GET` response; audio quality enum strings `LOW` | `HIGH` | `LOSSLESS` | `HI_RES_LOSSLESS`; video `360` | `480` | `720` | `1080`).

**200** — `{ "saved": true }`  
**400** — invalid quality values

### `GET /`

**200** — HTML shell (`web/index.html`), `Cache-Control: no-store`.

---

## WebSocket — `WS /ws`

- Connect to `ws://<host>:8000/ws` (or `wss://` if TLS terminates in front).
- Server **accepts** then **ignores incoming text** (keep-alive / ping from client is fine).
- Server pushes **JSON text** frames when download state changes.

**Message `type` values** (string):

| `type` | Meaning | Typical follow-up |
|--------|---------|-------------------|
| `download_started` | Item began | Poll `GET /api/download/queue` |
| `download_finished` | Item completed | Poll queue |
| `download_failed` | Item failed | Poll queue |
| `all_done` | Batch finished | Poll queue; UI sets idle |

Payload includes at least **`title`** and often **`progress`**. Treat WebSocket as a **hint**; **`GET /api/download/queue`** is source of truth.

---

## Download one song (end-to-end)

Prerequisites: **`GET /api/status`** shows `"authenticated": true` (complete OAuth via login/finalize if not).

### 1) Get the TIDAL track id

**Option A — search by text**

```http
POST /api/search
Content-Type: application/json

{"query": "Artist Name Track Title", "media_type": "Track"}
```

Read **`results[0].id`** (string) from `{"results":[...]}`. Confirm **`results[0].type`** is `Track` (or use the id you care about).

**Option B — you already have the id or a TIDAL link**

- Numeric **track id**: use it directly as `media_id`.
- **TIDAL share URL**: same search endpoint — set `"query": "<paste URL>"` and `"media_type": "Track"`; the server resolves the URL to **one** result when possible, then use **`results[0].id`**.

### 2) Queue the track

```http
POST /api/download/add
Content-Type: application/json

{"media_id": "<track_id>", "media_type": "track"}
```

Use lowercase **`track`** for `media_type` (matches what the UI sends). Optional `"engine": "tidal-dl-ng"` or `"tiddl"` if you must override the active engine.

**200:** `{"added": 1, "queue_size": N}` — if `added` is `0`, the id did not resolve (wrong id/type or engine).

### 3) Start the downloader

```http
POST /api/download/start
```

This processes **all** rows in the queue with status **`waiting`**. For a single song, the queue can contain just that one item.

### 4) Wait until finished

Poll **`GET /api/download/queue`** until that row’s **`status`** is **`finished`** or **`failed`**, and check **`error`** on failure.

Optionally open **`WS /ws`** and react to `download_*` / `all_done`, then still confirm via **`GET /api/download/queue`**.

### 5) Where the file appears

Output directory comes from **`GET /api/settings`** → **`download_base_path`** (path templates and quality also apply). With Docker Compose in this repo, downloads are typically under the host **`./downloads`** bind mount.

---

## Minimal LLM automation recipe

```bash
BASE=http://127.0.0.1:8000

curl -sS "$BASE/api/status"

curl -sS -X POST "$BASE/api/auth/login"
# Open login_url from JSON, then poll:
curl -sS -X POST "$BASE/api/auth/finalize"

curl -sS -X POST "$BASE/api/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"artist name","media_type":"Track"}'

curl -sS -X POST "$BASE/api/download/add" \
  -H 'Content-Type: application/json' \
  -d '{"media_id":"123456789","media_type":"track"}'

curl -sS -X POST "$BASE/api/download/start"
curl -sS "$BASE/api/download/queue"
```

---

## Operational notes for agents

1. **Rate limits:** TIDAL may throttle rapid search/download; respect `download_delay` and concurrency in settings.
2. **Idempotency:** `download/add` appends duplicates unless the client dedupes.
3. **CORS:** There is **no** general browser CORS middleware in this app; call the API from the **same origin** (browser opened to the app) or from **server-side / curl / LAN tools**.
4. **Health:** Docker healthcheck uses `GET http://localhost:8000/api/status` inside the container.

## Source of truth

Route definitions and models: **`web/main.py`**. Engine behavior: **`web/engines/tdlng.py`**, **`web/engines/tiddl.py`**.
