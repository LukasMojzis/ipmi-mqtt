#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="ipmi-mqtt:smoke"
container="ipmi-mqtt-smoke-minimal"
tmp_dir="$(mktemp -d)"
tmp_config="$tmp_dir/config.yaml"

python3 - "$repo_root/config/config.yaml" "$tmp_config" <<'PY'
import pathlib
import sys

import yaml

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
config = yaml.safe_load(source.read_text())
config.pop("TOPICS", None)
for server in config.get("SERVERS", []) or []:
    if server.get("BRAND") == "DELL":
        server.pop("SDRS", None)
target.write_text(yaml.safe_dump(config, sort_keys=False))
PY

docker build -t "$image" "$repo_root"
docker run --rm --name "$container" \
  -v "$tmp_config:/app/config/config.yaml:ro" \
  --entrypoint python3 \
  "$image" /app/ipmi-mqtt.py -o
