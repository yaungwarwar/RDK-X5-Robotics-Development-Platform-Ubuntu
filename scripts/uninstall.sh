#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo "Usage: $0" >&2; exit 2; }
rdk_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
rdk_unit=/etc/systemd/system/rdk-control-center.service
# Refuse to remove an administrator-modified unit.
if [[ -e "$rdk_unit" ]]; then
  cmp -s "$rdk_root/services/rdk-control-center.service" "$rdk_unit" || { echo "Unit differs; preserve it and uninstall manually." >&2; exit 1; }
  sudo systemctl disable --now rdk-control-center.service
  sudo rm -- "$rdk_unit"
  sudo systemctl daemon-reload
fi
"$rdk_root/scripts/compose.sh" down
echo "Application stopped and unit removed. Source, .venv, config and image retained for rollback."
