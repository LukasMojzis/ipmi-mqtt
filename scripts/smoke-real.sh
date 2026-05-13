#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="ipmi-mqtt:smoke"
container="ipmi-mqtt-smoke-real"

docker build -t "$image" "$repo_root"
docker run --rm --name "$container" \
  -v "$repo_root/config/config.yaml:/app/config/config.yaml:ro" \
  --entrypoint python3 \
  "$image" /app/ipmi-mqtt.py -o
