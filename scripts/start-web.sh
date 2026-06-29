#!/bin/bash
set -e

# Run from the repo root so docker compose finds docker-compose.yml regardless
# of where this script is invoked from (it now lives in scripts/).
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed.${NC}"
    exit 1
fi

DCMD="docker compose"
if ! $DCMD version &> /dev/null; then
    DCMD="docker-compose"
fi

echo -e "${BLUE}Starting Tidal DL Pro Web UI...${NC}"
mkdir -p downloads config

$DCMD up -d --build

echo -e "${BLUE}Waiting for service...${NC}"
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/api/status &>/dev/null; then
        break
    fi
    sleep 1
done

if curl -sf http://localhost:8000/api/status &>/dev/null; then
    echo -e "${GREEN}Ready at http://localhost:8000${NC}"
    (xdg-open http://localhost:8000 2>/dev/null || open http://localhost:8000 2>/dev/null || true)
else
    echo -e "${RED}Service failed to start. Run: $DCMD logs tidal-dl-pro-web${NC}"
    exit 1
fi
