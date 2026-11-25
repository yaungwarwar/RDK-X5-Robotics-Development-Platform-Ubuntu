# Upgrade preparation failure: confirmed dependency conflict

The physical target's staged venv reported `zope-event 5.1.1` requires
`setuptools>=75.8.2`, but saw `setuptools 59.6.0`. System Python's `pip check`
reported no broken requirements. The staged venv had `include-system-site-packages
= true`, and the same conflict occurred under Python isolated mode, so
`PYTHONPATH` alone cannot account for the failure. Exact installation locations
and the package-shadowing mechanism remain unverified. Native system Python
successfully imported `rclpy` from `/opt/ros/humble/local/lib/python3.10/dist-packages/rclpy/__init__.py`.
The archive was confirmed source-only on the target;
the retry rejection is consistent with the first attempt creating `.venv`.
It does not establish an archive packaging defect.

The failed v0.1.1 preparation created a venv with system site packages and
checked all visible distributions, while the ROS2 probe uses `/usr/bin/python3`.
Vendor ROS setup can populate `PYTHONPATH`. An isolated venv alone does
not prevent packages on `PYTHONPATH` from being visible. Locally, a synthetic
distribution on `PYTHONPATH` with an unsatisfied dependency made `pip check`
fail inside an otherwise isolated venv. This demonstrates an additional
contamination mechanism, not the complete cause of the target failure. The new
isolation implementation has not been validated on the target. The 0.1.2
implementation preserves the ROS path for the system-Python probe while
isolating the backend and installation commands.

## Read-only target diagnostics

Run in the same shell used for preparation. Output may contain local paths;
review it before sharing. These commands do not install or remove packages.

```bash
VENV="${RDK_FAILED_STAGE:?set preserved staging path}/.venv/bin/python"
echo '=== platform ==='
uname -m
/usr/bin/python3 --version
"$VENV" --version
echo '=== venv configuration ==='
cat "${RDK_FAILED_STAGE:?set preserved staging path}/.venv/pyvenv.cfg"
echo '=== staged dependency check ==='
"$VENV" -m pip check
echo '=== system dependency check ==='
/usr/bin/python3 -m pip check
echo '=== paths and installed runtime distributions ==='
"$VENV" -B - <<'PY'
import sys, importlib.metadata as m, importlib.util
print('executable:', sys.executable)
print('prefix:', sys.prefix, 'base_prefix:', sys.base_prefix)
print('search paths:', *sys.path, sep='\n  ')
for name in ('fastapi', 'uvicorn', 'pydantic', 'psutil', 'starlette', 'anyio', 'rclpy'):
    try:
        d = m.distribution(name)
        print(name, d.version, d.locate_file(''))
    except m.PackageNotFoundError:
        print(name, 'distribution metadata not found')
    spec = importlib.util.find_spec(name)
    print('  module:', spec.origin if spec else 'not found')
PY
echo '=== application imports ==='
(cd "${RDK_FAILED_STAGE:?set preserved staging path}/backend" && "$VENV" -B -c 'import fastapi, uvicorn, pydantic, psutil, app.main; print("application imports OK")')
echo '=== native ROS2 import in current shell ==='
/usr/bin/python3 -B -c 'import rclpy; print("rclpy:", rclpy.__file__)'
```

Compare each staged conflict with the system check: a matching system conflict
is already visible to system Python; a conflict only in the venv can result
from changed application versions or different paths. Package locations and
versions help distinguish these cases, but matching messages alone do not prove
causation. If system pip is unavailable, its check will report that fact rather
than proving the system environment clean. ROS imports depend on the shell's
native ROS setup; do not change vendor installation to obtain this evidence.
