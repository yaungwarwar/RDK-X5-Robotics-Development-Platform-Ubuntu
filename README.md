# RDK Control Center 0.1.3 (development)

**Development maintenance release:** v0.1.3 has not been physically deployed. Real proxy/browser and physical acceptance remain pending.

Independent, read-only robotics monitoring for **D-Robotics RDK X5**. No BlueOS dependency. This is a compatibility/reliability maintenance release of the deployed 0.1.2 platform; the native backend, Docker-hosted React/Nginx frontend and existing nine-page design remain intact.

Source: `/home/eve/rdk/rdk-platform`. Target: `/home/sunrise/rdk-platform`.

## Maintenance changes

- Hardware-aware Docker cgroup preflight: omit unsupported CPU quotas; retain required memory/PID isolation and the established rootless/read-only/capability/localhost controls. Generated configurations are separate from administrator files.
- Native BPU utilization from the verified ratio attribute, preserving real zero; utilization gauge and 60-slot history on Overview/BPU.
- Dedicated BPU temperature from hwmon `name=pvt`, `temp2_input`, isolated from the fast sampler with bounded retries. A CPU-temperature proxy is a **separate explicitly labeled measurement**.
- ROS2 default probe deadline eight seconds, specific failure diagnostics, duration/last-success/failure count, retained stale graph and recovery. Combined-image calibration discovery is included; absent JPEG publishers do not invalidate the camera graph.
- Accurate CPU aggregation across zero-jiffy core samples; genuine gaps remain visible, including isolated observations and missed WebSocket sequences.
- Explicit staged upgrade and rollback workflow with stable backup/recovery scripts. No upgrade is executed automatically.

All unavailable measurements remain null with source/reason/timestamp/age/stale metadata. No control endpoints, raw-image subscriptions, vendor utility polling, profiler activation, hardware permission changes or global Docker/cgroup changes exist.

## Physical evidence and remaining limits

The user reports 0.1.0 successfully deployed on RDK X5 / Ubuntu 22.04.5 / ARM64 / kernel 6.1.83 / Python 3.10.12. Native metrics, ARM64 image build, healthy Nginx, SSH tunnel and WebSocket telemetry worked. User-observed frontend consumption was approximately 2.1 MiB RAM / 0.04% CPU; backend approximately 52 MiB RAM. These are **user-provided 0.1.0 observations**, not new 0.1.2 benchmarks.

The user reports successful physical v0.1.2 deployment, healthy backend and
frontend, isolated ARM64 dependencies and pip check, BPU idle 0% at 996 MHz,
dedicated-temperature errno 110 with labeled CPU proxy, and approximately
36.42 MiB backend / 2.016 MiB frontend memory. The service ROS logging failure
is confirmed; see [ROS2_LOGGING_COMPATIBILITY.md](docs/ROS2_LOGGING_COMPATIBILITY.md).
Dynamic BPU inference-load testing and physical rollback remain pending. Local
automated validation uses mocked hardware and does not validate v0.1.3 on the
board. Container inventory remains unavailable; only service state is monitored.

## Local development

Do not run the target installer/upgrade on the workstation. Use an isolated venv; no sudo pip.

```bash
cd /home/eve/rdk/rdk-platform
env -u PYTHONPATH -u PYTHONHOME python3.10 -m venv .venv
env -u PYTHONPATH -u PYTHONHOME .venv/bin/python -m pip install -r backend/requirements.txt -r tests/requirements.txt
./scripts/start.sh --mock
```

Another terminal:

```bash
cd /home/eve/rdk/rdk-platform/frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:8088`. Backend remains `127.0.0.1:8089`. Mock mode has a prominent banner. Foreground processes stop with Ctrl+C. If those ports are already occupied, preserve the existing listener; use the isolated QA harness instead.

## Validation

```bash
cd /home/eve/rdk/rdk-platform
.venv/bin/python -m pytest -q
.venv/bin/ruff check backend scripts tests
.venv/bin/ruff format --check backend scripts tests
.venv/bin/python -m compileall -q backend scripts
for script in scripts/*.sh; do bash -n "$script"; done
cd frontend
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

Complete QA requires Nginx on PATH and a Playwright Chromium installation (`npx playwright install chromium`). It starts only owned local processes on **18088/18089**, temporarily remaps the proxy/origin configuration, tests the production frontend and cleans up. It never starts systemd units or containers. Optional user-space tools:

```bash
npm run test:e2e -- --nginx /absolute/path/to/nginx --compose /absolute/path/to/docker-compose --browser /absolute/path/to/chrome
```

Use `npm run test:e2e -- --backend-only` for Python/lint/compile/shell checks without launching preview services. The `--compose` option validates the base config and both generated CPU-supported/unsupported profiles without Docker daemon access. Otherwise validate Compose separately. Browser-only checks against an existing mock stack use `npm run test:browser` (8088 default or RDK_QA_BASE_URL).

## Deployment and operation

For the running 0.1.2 target, use **[DEPLOYMENT.md](docs/DEPLOYMENT.md)**. Transfer into a new sibling staging directory, prepare while 0.1.2 remains running, inspect the generated configuration/backup, then explicitly apply. Do not overlay source files or copy a workstation venv to ARM64.

Production access remains loopback-only by default, with the documented manual SSH tunnel. The maintenance upgrade deliberately rejects a non-loopback Nginx configuration for separate review. Existing LAN configuration files are retained in backups; this workflow does not silently change exposure policy.

- [Changelog](CHANGELOG.md)
- [Hardware interfaces and evidence](docs/HARDWARE_INTERFACES.md)
- [Read-only ROS2 service/shell diagnosis](docs/ROS2_DIAGNOSTICS.md)
- [Architecture/API](docs/ARCHITECTURE.md) and [security](docs/SECURITY.md)
- [Implementation status and physical acceptance checklist](docs/IMPLEMENTATION_STATUS.md)
- [Actual test report](docs/TEST_REPORT.md)
- Mock screenshots: [desktop](docs/screenshots/mock-overview-desktop.png), [mobile](docs/screenshots/mock-overview-mobile.png)

No SSH connection, physical deployment, public hosting or GitHub push is performed by the development agent.
