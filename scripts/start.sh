#!/usr/bin/env bash
set -euo pipefail
rdk_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:---backend}" in
  --mock) export RDK_CONFIG="$rdk_root/config/mock.yaml" ;;
  --backend) export RDK_CONFIG="${RDK_CONFIG:-$rdk_root/config/rdkx5.yaml}" ;;
  *) echo "Usage: $0 [--backend|--mock]" >&2; exit 2 ;;
esac
if [[ "${1:---backend}" != --mock ]]; then
  # Source only fixed vendor locations. Some ROS2 setup scripts expect unset vars.
  set +u
  if [[ -f /opt/tros/humble/setup.bash ]]; then
    source /opt/tros/humble/setup.bash
  elif [[ -f /opt/ros/humble/setup.bash ]]; then
    source /opt/ros/humble/setup.bash
  fi
  set -u
fi
# Keep ROS module paths for the fixed system-Python probe, not the backend.
export RDK_ROS_PYTHONPATH="${PYTHONPATH-}"
unset PYTHONPATH PYTHONHOME
[[ -x "$rdk_root/.venv/bin/python" ]] || { echo "Create the isolated .venv first; see README." >&2; exit 1; }
cd "$rdk_root/backend"
exec "$rdk_root/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8089 --workers 1 --no-proxy-headers
