# Changelog

## 0.1.3 — development

- Disable external ROS library logs for the fixed graph probe, preserving the
  hardened service filesystem and Python exception diagnostics.
- Retain bounded stderr tail and upgrade from the active generated v0.1.2
  deployment to v0.1.3, with rollback to v0.1.2.
- Local regression and physical acceptance are recorded separately.

## 0.1.2 — release candidate

- Isolate application dependencies from vendor packages and retain the native ROS2 subprocess environment.
- Add private upgrade diagnostics, preparation state tracking, fresh retry, and direct 0.1.0 → 0.1.2 migration with rollback to 0.1.0.
- User-reported final workstation QA: 192 Python and 12 browser tests passed; physical target acceptance remains pending.

## 0.1.1 — 2026-11-24

Hardware compatibility and reliability maintenance release. Existing native/container boundaries, nine-page dark dashboard and read-only controls are preserved.

- **RDK-COMPAT-001:** remove the unconditional Compose CPU quota. An explicit read-only preflight resolves the local Docker cgroup version/driver and parent hierarchy, verifies effective controllers and interfaces, preserves memory/PID limits, and generates a separate, validated compatibility configuration. Missing required isolation fails closed. Upgrade preserves the operational administrator quota workaround.
- Read native X5 BPU `ratio` as an integer 0–100 percentage, preserving zero. Add an Overview/BPU utilization gauge and bounded history. Dynamic physical inference-load validation remains pending.
- Discover hwmon by `name=pvt` and read dedicated `temp2_input` in a single isolated child. Timeout, bounded retries/backoff and quarantine prevent slow/uninterruptible reads from blocking hardware sampling or accumulating children. Expose an optional, separately named CPU-temperature proxy from the existing `thermal-cpu` measurement; never substitute it into BPU temperature.
- **RDK-COMPAT-002:** default ROS2 timeout becomes eight seconds (validated 2–30). Distinguish environment, timeout, process-exit, JSON, schema and output-limit errors. Record duration, last success, consecutive failures and sanitized bounded stderr. Preserve the last successful graph with original timestamps and explicit stale status during failures. No overlapping probes.
- Discover combined-image calibration topics; a missing JPEG publisher is independent of other camera availability.
- Correct aggregate CPU usage when an individual core has zero elapsed jiffies; preserve actual reset/warmup/missing samples. Render isolated valid chart points and insert visible gaps for missed telemetry sequences without interpolation.
- Add explicit prepare/apply/rollback upgrade transactions, source/venv/unit/drop-in/image backups, staged validation/build, local health checks and a recovery script retained outside the active installation.
- Retain devfreq precision to one Hz in MHz representation, without the vendor utility's 100 MHz upward rounding. Never run hrut_somstatus or touch its profiler controls.
- Preserve the 79-test Python baseline and six browser baseline tests; update only assertions required by eight-second probes, bounded subprocess injection and the verified graph fixture. Add maintenance regression coverage and updated documentation/screenshots.

## 0.1.0

Initial read-only native monitoring backend, mock fixtures, responsive nine-page frontend, Nginx/Compose configuration, systemd template and local tests. The user subsequently reported successful physical X5 deployment and provided the compatibility evidence addressed above.
