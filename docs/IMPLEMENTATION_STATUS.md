# Current status — v0.2.0 development

The physical target was last observed healthy with v0.1.3; that observation is historical and is not a current health check. The working tree contains separate v0.2.0 camera-laboratory development. The latest B.4.1 validation passed 270 Python and 32 browser cases, 302 unique cases, in each of three consecutive full runs; see [B.4.1 completion](V0.2.0_PHASE_B41_COMPLETION.md). The original independently failed `qa-results/qa-report.json` is preserved; the latest passing reports are under `qa-results/incident-001-validation/`. The earlier B.4 baseline was 267 Python and 32 browser cases. Physical reconnect, rollback, sustained-resource behavior and target CPU-rate isolation are not validated. Physical testing is suspended until continuous active cooling is confirmed and appropriate authorization is obtained.

The inherited application `VERSION` and frontend package version still identify the v0.1.3 release; the v0.2.0 label refers to the development cycle and isolated laboratory, not a generated v0.2.0 release artifact.

## Historical v0.1.3 status (2026-11-25)

The original v0.1.3 workstation QA passed 201 Python and 12 browser tests. The physical ARM64 target was upgraded from 0.1.2 to 0.1.3, and native health, dashboard, loopback bindings, repeated ROS2 discovery and five-minute stability were observed. Camera publishers and a short left preview were observed later; reconnect, right/combined and sustained testing remain pending. Dynamic BPU inference and physical rollback remain untested. See [physical acceptance](V0.1.3_PHYSICAL_ACCEPTANCE.md), [Phase B.1 evidence](V0.2.0_PHASE_B1_COMPLETION.md), and [QA infrastructure](QA_INFRASTRUCTURE.md).

The following material is historical, including earlier pending-work statements and old test counts; it does not describe the current v0.1.3 workstation or assert physical acceptance.

---

# Implementation status — 0.1.1

## User-reported physical v0.1.2 deployment

The user reports successful direct 0.1.0 → 0.1.2 prepare and activation on the
RDK X5, isolated ARM64 Python 3.10.12 dependencies and passing pip check,
healthy native backend and Docker frontend, SSH tunnel and live dashboard.
BPU was detected at idle 0% and 996 MHz; dedicated temperature reported errno
110 and the CPU-temperature proxy was explicitly labeled. Reported backend
memory was 36.42 MiB and frontend memory 2.016 MiB. Physical rollback and
dynamic BPU inference-load validation remain pending. The confirmed service
ROS initialization failure and experiments are documented in
[ROS2_LOGGING_COMPATIBILITY.md](ROS2_LOGGING_COMPATIBILITY.md). The v0.1.3
change and migration have not been physically validated.

## Current 0.1.2 release candidate status

Locally validated release candidate, approved for controlled physical upgrade
testing. The user reports final unrestricted-workstation QA passed 192 Python
and 12 browser tests, including Nginx/proxy checks. Codex's earlier TCP EPERM
remains historical. Physical ARM64 upgrade and hardware acceptance are pending.
The fixed `systemctl show` capture has no explicit byte limit; see
[PHASE_C_COMPLETION.md](PHASE_C_COMPLETION.md) for evidence and limits.

## Preserved physical baseline (reported by the user)

The user successfully deployed 0.1.0 on RDK X5, Ubuntu 22.04.5/ARM64, kernel 6.1.83 and Python 3.10.12 with Docker 29.1.3 / Compose 2.40.3. Native backend, ARM64 frontend build, healthy Nginx, SSH tunnel and WebSocket telemetry worked; CPU/RAM/storage/thermal/devfreq measurements were operational. User-observed resource figures: frontend ~2.1 MiB RAM / 0.04% CPU; backend ~52 MiB RAM. These are not new 0.1.1 measurements performed by the agent.

## Delivered maintenance scope

| Area | Status and evidence |
|---|---|
| RDK-COMPAT-001 | Base Compose quota removed; local Docker driver/version/parent/leaf evidence inspected by a read-only generator; positive memory/PID isolation required; missing CPU quota omitted with a compatibility warning |
| Generated deployment configs | Separate exclusive JSON Compose bundles, original admin files retained, actual Compose validation for both CPU profiles, no silent overwrite |
| Security controls | Native sunrise service and all existing systemd controls unchanged; uid/gid 101 frontend, read-only root/config, cap_drop ALL, no-new-privileges, localhost binding and memory/PID limits retained |
| Native BPU ratio | Exact verified platform path, strict integer 0–100 validation and provenance/freshness; genuine zero preserved; no frequency inference |
| Dedicated BPU temperature | Discover hwmon by pvt name, dedicated temp2 only, single process slot, timeout/backoff/quarantine; local fixture tests |
| CPU-temperature proxy | Separate optional CPU thermal-zone measurement with explicit attribution/fallback state; never inserted into dedicated BPU temperature |
| RDK-COMPAT-002 | Eight-second default configurable probe timeout; separate environment/timeout/exit/JSON/schema/output diagnostics; bounded sanitized stderr; duration, last success and failures; retained stale graph and recovery; no overlapping probes |
| ROS2/camera graph | Combined calibration topics added; absent JPEG publisher is independent; no image subscription or capture startup |
| CPU chart reliability | Aggregate time-delta correction for zero-jiffy cores; resets remain unavailable; missed sequences form gaps and isolated values render visibly; no fabricated interpolation |
| Dashboard | Existing nine-page design retained; Overview/BPU gauge/history, temperature attribution and ROS2 diagnostics added; desktop/mobile browser regressions pass |
| Upgrade/recovery | Explicit prepare/apply/rollback, full source/venv/unit/drop-in/image backups, stable recovery script, staged dependency/config/image validation, hash guards and automatic rollback on health failure; local fixture tests only |
| Documentation/artifacts | Changelog, hardware references, read-only environment comparison, exact manual commands, test report and source archive/checksum |

Container inventory, authentication/TLS, hardware control, profiler activation and persistent ROS2 worker remain outside this maintenance release. A persistent read-only ROS2 worker is documented as a future startup-cost optimization, not implemented.

## Remaining physical acceptance — not yet performed for 0.1.1

1. Run the read-only compatibility check on the actual Docker hierarchy. Confirm detected cgroup version/driver and running dashboard parent/leaf match the target; cpu.max/delegation is absent as reported. Confirm the warning omits CPU quotas while memory/PID controls remain effective. Do not modify cgroups, watchdog or kernel/Docker settings.
2. Prepare the staged release with the actual old Compose files and selected RDK_CONFIG. Verify complete private source/venv/unit/drop-in/image backups, native ARM64 dependencies/build and generated loopback configuration before stopping anything. Review preserved manual quota workaround and unchanged service protections.
3. Apply the explicit transaction and check native 0.1.1 health, healthy dashboard, SSH tunnel and WebSocket updates. Exercise explicit rollback to 0.1.0 in an appropriate maintenance window; local simulated rollback is not physical rollback validation.
4. Confirm all previously working CPU/RAM/storage/CPU-DDR thermal/devfreq/network/service readings remain correct. Verify BPU/GPU frequencies have no vendor 100 MHz upward rounding. Observe the CPU chart under normal load and genuine missing/reset cases without inventing history.
5. Compare the ratio's idle raw zero to API/UI zero. Under a user-approved existing inference workload, record changing ratio values, timestamps, units and utilization history, then idle recovery. **Dynamic inference-load validation remains pending.** Do not start a workload automatically or claim board load testing from mocks.
6. Verify actual hwmon name discovery with arbitrary hwmon numbering. Observe dedicated temp2 success or its reported timeout/null; verify retry/backoff and fast sampler continuity. Confirm CPU proxy is separately labeled and has the actual CPU thermal-zone source, never a dedicated BPU value. Do not run hrut_somstatus or enable profiling.
7. If a sensor read remains uninterruptible, inspect the one retained child and absence of new helper accumulation. Confirm application/service shutdown behavior without repeated restarts to bypass quarantine. Python cannot force an uninterruptible kernel read to complete.
8. Inspect the specific ROS2 diagnostic under the service. Compare the allowlisted service/shell environment and namespace evidence using ROS2_DIAGNOSTICS.md. Determine whether timeout, environment, process exit, JSON contamination or schema rejection explains the prior generic failure. No root cause has been conclusively established.
9. With the existing camera graph already active, confirm `/mipi_cam`, image/calibration topics/types and one publisher for the user-verified topics. Confirm JPEG absence remains only a zero publisher row. Do not start camera capture or subscribe to raw images for monitoring acceptance.
10. Verify ROS2 last-success timestamps, failure counts, retained stale graph and recovery during a controlled application-only test. Record actual durations against the configurable deadline; do not change ROS_DOMAIN_ID, DDS settings, shared-memory permissions or vendor scripts.
11. Re-measure 0.1.1 backend/frontend RAM/CPU, sustained one-second sampling, multiple-browser behavior and the configured limits under normal robotics workload. The successful 0.1.0 resource observations are a comparison baseline, not a promise of identical 0.1.1 consumption.
12. Verify backend 8089 and dashboard 8088 stay loopback-only; accepted hosts/origins, mutation rejection and security headers still work. Confirm SSH 22, RPCBind 111, VNC 5900, Hobot 8000, Python 11511 and unrelated robotics processes/configurations remain intact.

No physical 0.1.1 deployment, dynamic BPU test, native service-environment reproduction or target upgrade/rollback was performed by this agent.
# v0.1.2 continuation — incomplete

The physical staged environment reported zope-event 5.1.1 requiring
setuptools >=75.8.2 while finding setuptools 59.6.0. System Python's check was
clean, and isolated mode in the system-site-enabled venv still failed. The
distribution locations and exact shadowing mechanism are not yet known. The
application isolation changes and synthetic regression have not been validated
on the RDK X5.

Local Python 3.10.22 and the existing Chromium QA setup completed a run with
155 Python and 12 browser tests passing before the latest journal changes. The
updated deployment/isolation tests subsequently passed (39 tests). See
TEST_REPORT.md. Phase A transaction changes and Phase B direct migration work
are recorded in their completion documents. This paragraph is historical; the
user later reported successful final workstation QA. The historical physical
cgroup report remains valid; the new upgrade path has not been physically tested.

