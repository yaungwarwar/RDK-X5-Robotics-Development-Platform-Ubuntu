#!/usr/bin/env bash
set -euo pipefail
rdk_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
rdk_compose=$(python3 - "$rdk_root" <<'PY'
import json
import sys
from pathlib import Path
root=Path(sys.argv[1]); marker=root/'.deployment/active.json'
if marker.exists():
    relative=Path(json.loads(marker.read_text())['compose'])
    path=(root/relative).resolve()
    if relative.is_absolute() or root not in path.parents or not path.is_file():
        raise SystemExit('Invalid active deployment marker')
    print(path)
else:
    raise SystemExit('Generate/activate a compatibility configuration first; see DEPLOYMENT.md')
PY
)
exec docker compose -p rdk-control-center -f "$rdk_compose" "$@"
