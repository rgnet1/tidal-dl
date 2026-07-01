# ---- Production image (Tidal DL Pro web UI) ----
# tiddl v3.x requires Python >=3.13; upstream tidal-dl-ng supports 3.12–3.13 per pyproject.
FROM python:3.13-slim

ENV PUID=1000 \
    PGID=1000 \
    XDG_CONFIG_HOME=/config \
    TIDDL_PATH=/config/tiddl \
    DOWNLOAD_PATH=/downloads \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl gosu tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r -g 1000 app && useradd -r -u 1000 -g app -d /home/app -s /bin/bash app \
    && mkdir -p /home/app && chown -R app:app /home/app

WORKDIR /app

# NOTE: quotes around uvicorn[standard] are REQUIRED; without them the shell
# treats [standard] as a glob pattern and pip installs plain uvicorn, leaving
# the WebSocket implementation (websockets/wsproto/httptools/uvloop) missing.
RUN pip install \
    "fastapi==0.139.*" \
    "starlette>=1.3.1" \
    "uvicorn[standard]==0.34.*" \
    "websockets>=12" \
    "wsproto>=1.2" \
    "tiddl>=3.4.0,<4" \
    "tomli-w>=1.0.0"

COPY pyproject.toml poetry.lock README.md LICENSE /app/
COPY tidal_dl_ng/ /app/tidal_dl_ng/
RUN pip install .

COPY web/ /app/web/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Normalize line endings in case the script was saved with CRLF on Windows,
# otherwise bash rejects it with "bad interpreter".
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

# Declare the persistent paths. Bind-mounting any path here from docker-compose
# (e.g. ./config:/config) keeps settings.json and token.json on the host so
# credentials survive rebuilds.
RUN mkdir -p /config /config/unified /config/tiddl /downloads \
    && chown -R app:app /config /downloads
VOLUME ["/config", "/downloads"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/status || exit 1

ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "websockets"]
