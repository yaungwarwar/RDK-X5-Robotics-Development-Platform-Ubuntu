# ROS2 service versus interactive-shell diagnosis

The user verified that sourcing `/opt/tros/humble/setup.bash` and running the fixed system-Python probe works interactively in approximately 3.1–3.4 seconds. This does **not** establish that the service has the same environment, namespaces, discovery timing or permissions. The old generic failure message hid whether the deadline, exit code, JSON or graph schema was responsible. No root cause is asserted without the new diagnostics.

## New diagnostic fields

`GET /api/v1/ros2` and the ROS2 page report:

- `probe_duration` in seconds; null when no subprocess ran.
- `last_success` UTC timestamp; null until discovery succeeds.
- `consecutive_failures` (disabled discovery is not counted as a failure).
- `diagnostic`: `success`, `success_empty`, `disabled`, `environment_missing`, `environment_unsourced`, `timeout`, `exit_error`, `invalid_json`, `invalid_graph`, `output_limit`, `spawn_error`, or `probe_unreaped`.
- `detail`: specific human-readable reason, including timeout seconds or exit status.
- `stderr_excerpt`: at most 512 printable characters, with ANSI/control characters removed and common secret assignments redacted. Capture itself is bounded at 4096 stderr bytes; stdout is limited to 2 MB.

The configurable `ros2_probe_timeout_seconds` defaults to 8.0 and accepts 2–30 seconds. Old config files inherit the new default without being rewritten. Probes never overlap; the auxiliary collector waits for completion and the adapter has a non-overlap lock. A killed child that remains unreaped occupies its single slot; no replacement accumulation is allowed.

A transient failure sets current discovery availability to unavailable while preserving prior graph/node/publisher data with **original timestamps and explicit stale flags**. Last success remains unchanged and the failure count increases. Success replaces the graph and resets failures. An empty successful graph has actual empty lists and known-publisher zeroes, not a discovery error. A 25-second age threshold (default) also detects stopped auxiliary sampling.

## Read-only target procedure

Execute manually in the target's existing terminal; the development agent did not execute these commands on the board. Do not start capture just for this check. Never run hrut_somstatus as part of it.

1. Inspect the service and the specific adapter error:

```bash
cd "${RDK_INSTALL:?set the installed application directory}"
systemctl status rdk-control-center.service --no-pager
systemctl show rdk-control-center.service --property=User,Group,WorkingDirectory,MainPID,PrivateTmp,ProtectSystem,ProtectHome,DropInPaths
systemctl cat rdk-control-center.service
journalctl -u rdk-control-center.service -n 80 --no-pager
curl -fsS http://127.0.0.1:8089/api/v1/ros2
```

2. Compare only allowlisted discovery-related environment and namespace metadata. The helper does not dump the complete environment or read profile contents. Profile-variable values are represented by presence/hash because they can contain inline XML. Store reports privately:

```bash
umask 077
source /opt/tros/humble/setup.bash
/usr/bin/python3 scripts/ros2_environment.py > /tmp/rdk-ros2-interactive.json
rdk_service_pid=$(systemctl show rdk-control-center.service --property=MainPID --value)
/usr/bin/python3 scripts/ros2_environment.py --pid "$rdk_service_pid" > /tmp/rdk-ros2-service.json
diff -u /tmp/rdk-ros2-interactive.json /tmp/rdk-ros2-service.json || true
```

Expected differences include PID, executable (venv backend versus system Python helper), working directory and mount namespace/temporary-directory metadata under PrivateTmp. These differences are evidence to inspect, not reasons to disable protections. Compare ROS_DISTRO, ROS_VERSION, ROS_DOMAIN_ID, RMW_IMPLEMENTATION, ROS_LOCALHOST_ONLY, AMENT/COLCON prefixes, PYTHONPATH, LD_LIBRARY_PATH, discovery-server/profile presence and hashes. The probe itself uses `/usr/bin/python3`; the backend venv must not replace native rclpy.

If `/proc/PID/environ` or namespace metadata is denied, record that limitation. Do not chmod procfs/shared memory, change security controls or introduce passwordless sudo. Do not post the reports publicly without reviewing paths/domain/discovery-server addresses.

3. Repeat the already verified interactive probe, with a bounded manual deadline, without changing the graph or camera configuration:

```bash
cd "${RDK_INSTALL:?set the installed application directory}"
source /opt/tros/humble/setup.bash
time timeout 8s /usr/bin/python3 backend/app/adapters/ros2_probe.py > /tmp/rdk-ros2-probe.json
```

Read its exit code immediately (`echo $?`), inspect JSON and compare with the API's diagnostic/duration/last-success fields. Standalone execution emits normal DDS discovery traffic and creates only the monitor node. Do not change ROS_DOMAIN_ID, DDS profiles, shared-memory permissions or vendor setup files to force agreement. The environment helper is a read-only comparison of the actual running service; it does not reproduce every systemd constraint in an interactive child.

4. If a timeout is identified, inspect host load and cold-start timing. If a nonzero exit is identified, use its sanitized stderr and local journal. Invalid JSON may indicate stdout contamination; graph-schema failures are distinct from missing publishers. Preserve the specific evidence before choosing a fix. The new eight-second default supplies margin, not proof of the old failure's cause.

`start.sh` continues sourcing the fixed TogetheROS setup (or ROS Humble fallback) before exec. PrivateTmp, ProtectSystem, ProtectHome and other unit controls are **unchanged**. A persistent ROS2 worker could reduce repeated import/DDS startup in a future release, but would require its own resource, restart and isolation review and is not implemented here.
# Confirmed v0.1.2 service initialization failure

The user isolated ROS library file logging under the read-only service home as
the cause. See [ROS2_LOGGING_COMPATIBILITY.md](ROS2_LOGGING_COMPATIBILITY.md)
for the exception, controlled experiments and v0.1.3 fix. The new release still
requires physical service graph and camera discovery acceptance.

