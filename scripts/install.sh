#!/usr/bin/env bash
# Run manually on the target as sunrise. Never invoked by development tests.
set -euo pipefail
rdk_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || { echo "Usage: $0 [--check]" >&2; exit 2; }
[[ $(uname -m) == aarch64 ]] || { echo "Refusing: installation requires ARM64 RDK X5." >&2; exit 1; }
[[ -r /proc/device-tree/model ]] || { echo "Refusing: cannot verify board model." >&2; exit 1; }
rdk_model="$(tr -d '\0' < /proc/device-tree/model)"
[[ "${rdk_model,,}" == *rdk*x5* ]] || { echo "Refusing: model is not RDK X5: $rdk_model" >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 22.04 ]] || { echo "Refusing: Ubuntu 22.04 required." >&2; exit 1; }
[[ $(id -un) == sunrise && $EUID -ne 0 && "$rdk_root" == /home/sunrise/rdk-platform ]] || { echo "Run as sunrise from /home/sunrise/rdk-platform." >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info[:2] == (3,10), "Python 3.10 required"; import venv'
docker compose version >/dev/null
docker info >/dev/null
docker compose -f "$rdk_root/compose.yaml" config -q
python3 "$rdk_root/scripts/cgroup_compat.py" --compose-file "$rdk_root/compose.yaml" --check
if [[ "${1:-}" == --check ]]; then echo "Target preflight passed; no changes made."; exit 0; fi
[[ ! -e "$rdk_root/.venv" ]] || { echo "Existing .venv preserved. See upgrade/rollback instructions." >&2; exit 1; }
[[ ! -e /etc/systemd/system/rdk-control-center.service ]] || { echo "Existing unit preserved. See upgrade/rollback instructions." >&2; exit 1; }
env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 -m venv "$rdk_root/.venv"
env -u PYTHONPATH -u PYTHONHOME "$rdk_root/.venv/bin/python" -m pip install -r "$rdk_root/backend/requirements.txt"
env -u PYTHONPATH -u PYTHONHOME "$rdk_root/.venv/bin/python" -m pip check
cd "$rdk_root"
rdk_bundle=".deployment/install-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p .deployment
python3 scripts/cgroup_compat.py --compose-file compose.yaml --output-dir "$rdk_bundle"
python3 - "$rdk_bundle" <<'PYCODE'
import json
import sys
from pathlib import Path
with Path('.deployment/active.json').open('x') as out:
    json.dump({'compose': sys.argv[1] + '/compose.compat.json'}, out)
PYCODE
./scripts/compose.sh build
# Fixed destination, no replacement of an existing service.
sudo install -m 0644 "$rdk_root/services/rdk-control-center.service" /etc/systemd/system/rdk-control-center.service
sudo systemctl daemon-reload
echo "Installed; nothing started or enabled. Follow docs/DEPLOYMENT.md to start."
