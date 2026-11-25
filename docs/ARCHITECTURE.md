# Architecture

## Boundaries

The native backend is Python 3.10-compatible FastAPI, Uvicorn, Pydantic and psutil. It owns hardware adapters and the shared collector. The only container contains compiled React/TypeScript assets and Nginx. ROS2, TogetheROS, Hobot libraries, GS130WI capture, BPU runtime and drivers stay on the host. No BlueOS dependency exists.

`create_app(settings, hardware, ros2)` supports dependency injection. `NativeHardware` and `MockHardware` implement the `HardwareAdapter` protocol. `SysfsReader` accepts explicit filesystem roots for tests. `Ros2Adapter` and `MockRos2` provide the same graph result shape. Mock sources say MOCK and the top-level `mode` is always included; native mode never silently falls back to mock.

## Collection and resource bounds

A lifespan-owned `Monitor` runs exactly one hardware sampler and one auxiliary sampler in a shared executor with two workers. Only one Uvicorn worker is supported. HTTP handlers and WebSocket clients read cached snapshots and never initiate collection.

Hardware sampling targets one second, with sample runtime subtracted from the next wait. Slow ROS2 and systemd operations run separately, normally every ten seconds. ROS2 uses a configurable eight-second default subprocess deadline (2–30 seconds); two fixed systemctl queries each have a one-second deadline. A cold backend startup waits for initial auxiliary collection before serving. Scheduler delays and host load can increase intervals; actual timestamps are authoritative.

CPU usage comes from successive psutil/procfs CPU-time deltas, excluding guest time from totals and treating idle+iowait as idle. The initial usage sample is null / `warming_up`; no artificial initial zero. Overall usage uses the sum of valid elapsed busy/total CPU time; a zero-jiffy individual core no longer erases a valid overall sample. Invalid/reset deltas still make the aggregate unavailable. Core IDs come from `/proc/stat`; identity changes reset the delta baseline. A missing/inconsistent identity map makes frequencies unavailable rather than assigning them to the wrong core. Per-core sysfs frequency reads use kHz and normalize to MHz. Memory used is total minus available (reclaimable caches are accounted for by Linux's available value). Load averages use one/five/fifteen-minute values.

Network rates are byte counter deltas divided by monotonic elapsed seconds. First samples, newly appearing interfaces, resets, and nonpositive intervals have null rates with explanations. RX/TX totals in the UI exclude loopback. The UI reports binary byte units; API rates are B/s. Storage defaults to `/`; configured local paths use statvfs through psutil, without recursive mount scanning.

Server history is a bounded deque, default 60, configurable 1–600. Only latest snapshots are transmitted; no historical replay or disk telemetry database. Frontend history is bounded at 60 and deduplicates sequence/timestamp pairs. Chart gaps preserve unavailable samples. Chart axes span the currently collected samples, up to 60, and show the actual count. A browser restart clears its history.

Each WebSocket connection sends at the configured interval and uses a three-second send timeout, with no per-client unbounded queue. Client messages close the read-only channel with code 1008. Browser reconnect uses bounded exponential backoff (1–10 seconds), an idle-channel watchdog, and immediate fresh-snapshot updates. WebSocket clients must send an explicitly accepted Origin, including non-browser clients.

## Freshness and failure

Each measurement has its own UTC acquisition timestamp. Responses compute `age_seconds` and `stale` without changing that timestamp. Fast metrics become stale after five seconds by default. ROS2, cameras and services use the larger of that threshold or 2.5 × the auxiliary interval (25 seconds by default). Thus a ten-second graph cache is not mislabeled stale midway through its normal cycle.

A collection exception retains the last successful fast snapshot and records a `collector_error`; timestamps continue aging. Before any successful sample the API returns 503. A stale snapshot or fast collector error makes `/health` degraded. Unavailable sensors or disabled ROS2 do not themselves indicate an unhealthy collector. Auxiliary failures retain old data with aging timestamps or report unavailable through their adapter. The dashboard separately detects silence even when no new messages arrive.

## REST and WebSocket contract

GET routes:

| Route | Result |
|---|---|
| `/api/v1/health` | Collector status, version, mode, timestamp, age, stale flag, error |
| `/api/v1/system` | Hostname, OS, kernel, architecture, uptime |
| `/api/v1/cpu` | Overall/per-core usage, per-core MHz, load average |
| `/api/v1/memory` | Total/available/used bytes, used percentage |
| `/api/v1/storage` | Configured volume usage |
| `/api/v1/thermal` | CPU/DDR temperatures and cooling-device states |
| `/api/v1/bpu` | Device metadata, frequency interface, unavailable vendor metrics |
| `/api/v1/network` | Interface addresses/state/RX/TX rates |
| `/api/v1/ros2` | Environment/graph availability, nodes, topics/types/publisher counts |
| `/api/v1/cameras` | Known camera publishers and `/mipi_cam` presence |
| `/api/v1/services` | Docker/containerd systemd status; unavailable inventory |
| `/api/v1/snapshot` | All sections plus GPU and DDR frequency interfaces |

`/ws/v1/telemetry` sends the same JSON schema as `/api/v1/snapshot`. No arguments select paths, commands, services or hardware devices. Query strings do not execute operations. No mutations or file endpoints exist. OpenAPI/UI endpoints are disabled in production.

Section responses retain the snapshot envelope but replace `data` with that section. An example native unavailable measurement:

```json
{
  "value": null,
  "unit": "°C",
  "status": "unavailable",
  "reason": "Matching thermal zone not found",
  "source": "sysfs thermal type=thermal-ddr",
  "timestamp": "2026-11-24T07:30:00+00:00",
  "age_seconds": 0.3,
  "stale": false
}
```

Status is `ok`, `unavailable`, `error` or `warming_up`. `null` is never converted to zero. Observed zero usage, zero publishers in a successfully discovered graph, and cooling state zero are legitimate readings. Unavailable publisher counts are null when discovery itself is unavailable.

## Configuration

Files under `config/*.yaml` deliberately contain **JSON syntax, a subset of YAML 1.2**. Use JSON syntax when editing; arbitrary YAML syntax is not accepted. This keeps the runtime parser small and forbids YAML tags or constructors.

`RDK_CONFIG` selects a file at process startup, not through the API. `default.yaml` is native with ROS2 disabled; `rdkx5.yaml` enables optional native ROS2; `mock.yaml` is explicit simulation. Settings reject unknown fields, wrong types, wildcard hosts/origins, command-like paths, path traversal and invalid interval/history bounds. Origins must be exact HTTP(S) origins without paths or credentials. Backend host/port and subprocess arguments are fixed outside the API. Frequency units and device paths are fixed verified interfaces, not user-supplied commands.

## Container

Host networking allows Nginx to reach the host backend's loopback address. It intentionally avoids a bridge-network assumption that container localhost is host localhost. No port publishing is needed with `network_mode: host`. Nginx listens on 127.0.0.1:8088 by default. The container runs uid/gid 101, all capabilities dropped, no-new-privileges, read-only root, and a bounded temporary filesystem. It has no device mounts or Docker socket. Only the Nginx configuration file is mounted read-only. Base limits: 96 MiB and 64 PIDs. CPU quota 0.5 is added only by a compatible generated profile; upgrades preserve an existing no-quota workaround. systemd bounds backend memory to 256 MiB and tasks to 96; validate these limits on the target with ROS2 enabled.

## 0.1.1 maintenance additions

BPU utilization is read from the verified platform ratio attribute, not frequency. Dedicated BPU temperature uses a single nonblocking-polled fixed subprocess slot, with a 30-second refresh and bounded failure backoff. Its default freshness limit is 75 seconds; CPU/DDR thermal readers and optional CPU proxy retain their existing five-second fast freshness. See HARDWARE_INTERFACES.md for exact attribution and the uninterruptible-kernel-read limitation.

ROS2 data is retained after failures with original acquisition times and forced stale flags; freshen preserves those flags even before the normal age deadline. Separate attempt diagnostics distinguish a failed discovery from a valid empty graph. The fixed subprocess architecture remains; a persistent ROS2 worker is future work.

Frontend history still holds at most 60 slots. Sequence/time gaps add one explicit null separator, duplicate sequence/timestamp pairs add no points, and isolated valid values render as points rather than disappearing in an SVG move-only path. Nulls are never interpolated or changed to zero.

Deployment tools are manual, local target operations outside the backend/API. They inspect the local Docker/cgroup hierarchy, generate exclusive standalone configs, and stage/back up/activate/roll back this application only. The base Compose has no unconditional CPU quota; generated profiles conditionally add it. Neither runtime API nor frontend gains command/service-control endpoints.
# 0.1.2 release candidate notes

The backend uses an isolated application venv; the fixed `/usr/bin/python3`
ROS2 probe receives the preserved native ROS environment. BPU adapters use
read-only sysfs. The 0.1.0 → 0.1.2 transaction retains the administrator's
quota workaround and uses a separate backup recovery script. The v0.1.1
detector was physically observed on the X5 with cgroup v2/systemd, CPU quota
unavailable and memory/PID controllers available. The 0.1.2 upgrade and native
ARM64 paths remain physically unvalidated.

