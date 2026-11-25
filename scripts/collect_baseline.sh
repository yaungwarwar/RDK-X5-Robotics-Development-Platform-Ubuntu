#!/usr/bin/env bash
set -euo pipefail
[[ $# -le 1 ]] || { echo "Usage: $0 [new-output-file.json]" >&2; exit 2; }
# File is exclusive-created and private. Contains hostname and IP addresses.
python3 - "${1:-rdk-baseline-$(date -u +%Y%m%dT%H%M%SZ).json}" <<'PYCODE'
import json
import os
import sys
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8089/api/v1/snapshot', timeout=5) as response:
    data = json.load(response)
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as out:
    json.dump(data, out, indent=2)
print('Baseline saved:', sys.argv[1])
PYCODE
