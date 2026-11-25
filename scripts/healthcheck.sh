#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo "Usage: $0" >&2; exit 2; }
python3 - <<'PYCODE'
import json
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8089/api/v1/health', timeout=4) as response:
    health = json.load(response)
print(json.dumps(health, indent=2))
with urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=4) as response:
    assert response.status == 200
if health['status'] != 'ok':
    raise SystemExit('Collector degraded')
PYCODE
