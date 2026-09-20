# v2.1.0

Web UI release. Audio is saved as FLAC on both engines, albums keep their track order, and the queue shows live logs and per-song progress.

- Hi-Res is requested only when that track offers it. 16-bit tracks are requested as CD lossless instead of falling back to AAC.
- Successful audio downloads are always `.flac`. FLAC inside an MP4 is remuxed. A lossy stream is transcoded and badged Low.
- Queue items show Hi-Res, CD, or Low. A toast explains when the file is below the requested quality.
- New installs default to Hi-Res when available. Existing quality settings are left alone.
- tiddl album downloads use the album path template, so files land in the album folder with track numbers.
- The search bar accepts TIDAL links (`tidal.com` and `listen.tidal.com`, including `/browse/` and share suffixes).
- The queue panel has an activity log. Copy is shown only while that log has lines.
- Album progress advances once per finished song and shows `done / total` tracks. A single track still follows byte progress.
- The queue panel width can be dragged on desktop and is remembered for the browser tab session.

# v0.4.11

- Fixes regarding empty metadata tags (also fixes #1).
- CLI downloader extended to handle playlists and mixes.
- `Download.track()` now handles logger functions.
- GUI build for macOS and asset upload.

# v0.4.9

- Fixed: Exception on missing file read (config, token) instead of creation.

# v0.4.8

- Fixed: GUI dependencies are treated as extra now (pip).

# v0.4.7

- Fixed: GUI dependencies are treated as extra now (pip).

# v0.4.6

- GUI dependencies are treated as extra now (pip).

# v0.4.5

- Fixed "Mix" download.
- Fixed relative imports.
- Fixed PyPi build.
- Fixed crash on lyrics error.

# v0.4.2

- Added more basic features.

# v0.4.1

- Initial featured running version.
