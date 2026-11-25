#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo "Usage: $0" >&2; exit 2; }
rdk_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Explicit manual target action; affects only this application's unit/project.
sudo systemctl stop rdk-control-center.service
"$rdk_root/scripts/compose.sh" down
