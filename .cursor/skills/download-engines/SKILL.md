---
name: download-engines
description: >-
  Layout and integration steps for Tidal DL Pro download engines under
  engines/tidal-dl-pro and engines/tidal-dl. Use when adding a download
  engine, moving engine code, changing engine imports, or wiring a new
  backend into the web queue.
---

# Download engines

Each download backend is one folder under `engines/`. The folder name uses hyphens. Python imports use underscores.

| Folder | Import | Runtime id (`ENGINES` key, settings, `ACTIVE_ENGINE`) | Class |
| --- | --- | --- | --- |
| `engines/tidal-dl-pro/` | `engines.tidal_dl_pro` | `tidal-dl-ng` | `TdlngEngine` |
| `engines/tidal-dl/` | `engines.tidal_dl` | `tiddl` | `TiddlEngine` |

The upstream source for each engine lives in that folder, next to the adapter `__init__.py`:

- `engines/tidal-dl-pro/tidal_dl_ng/` is the tidal-dl-ng tree. Import it as `tidal_dl_ng`.
- `engines/tidal-dl/tiddl/` is tiddl 3.4.4 (Apache-2.0, https://github.com/oskvr37/tiddl). Import it as `tiddl`.

`engines/_load.py` puts those two directories on `sys.path` and maps the hyphen folders onto `engines.tidal_dl_pro` and `engines.tidal_dl`. Shared helpers that both engines call stay beside the folders: `engines/base.py`, `engines/track_manifest.py`, `engines/dash.py`.

Do not rename a runtime id when moving files. Settings, `ACTIVE_ENGINE`, and `/api/status` already store `tidal-dl-ng` and `tiddl`.

A new engine's own repository goes in `engines/<hyphen-name>/<import_package>/`. Register that parent directory in `_prefer_vendored_engines()` so `import <import_package>` resolves to the copy in the folder, not to a pip install of the same name.

## Add an engine

1. Create `engines/<hyphen-name>/__init__.py`. Implement `Engine` from `engines.base`. Set `name` to the runtime id (the string stored in settings).
2. Register the folder in `engines/_load.py` `_ENGINE_MODULES`:
   `"engines.<underscore_name>": "<hyphen-name>"`.
3. Construct it in `web/main.py` `_startup` and assign `ENGINES["<runtime-id>"]`.
4. Allow that id in `get_active_engine_name()`, settings validation, and the engine `<select>` in `web/index.html`.
5. If the engine logs through `logging`, add the logger name to `web/event_log.py` `_UI_LOG_LOGGER_NAMES`. Attach the handler only on the parent logger; child loggers propagate.
6. Cover `resolve_media` and `download_entry` with a test that uses the fake engine in `tests/conftest.py`, or a direct import of the new module.

`download_entry` must set `entry["status"]` to `finished` or `failed`, update `progress`, and broadcast `download_started` / `download_finished` / `download_failed`. One queue id is fetched once per process even when skip-existing is off; do not start a second fetch for the same id inside that call.

## Imports

```python
from engines.base import Engine
from engines.tidal_dl_pro import TdlngEngine, reload_tidal_clients
from engines.tidal_dl import TiddlEngine
from engines.track_manifest import fetch_audio_manifest
```

Inside an engine package, import shared code as `engines.base` and `engines.track_manifest`, not as a relative import. The hyphen folder is not a normal package path.
