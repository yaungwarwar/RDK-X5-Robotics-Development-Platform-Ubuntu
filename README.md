# RDK Control Center — v0.2.0 development

The installed physical release was last observed healthy at v0.1.3; current workstation development is v0.2.0. The camera laboratory is separate from the installed application. Physical testing is suspended pending confirmation of continuous active cooling. See the [current status](docs/IMPLEMENTATION_STATUS.md).

Independent, read-only robotics monitoring for **D-Robotics RDK X5**. No BlueOS dependency. This is a compatibility/reliability maintenance release of the deployed 0.1.2 platform; the native backend, Docker-hosted React/Nginx frontend and existing nine-page design remain intact.

Local paths, target addresses and maintenance transaction details belong in private operator records; do not publish credentials, host-specific configurations or backups.

## Maintenance changes

- Hardware-aware Docker cgroup preflight: omit unsupported CPU quotas; retain required memory/PID isolation and the established rootless/read-only/capability/localhost controls. Generated configurations are separate from administrator files.
- Native BPU utilization from the verified ratio attribute, preserving real zero; utilization gauge and 60-slot history on Overview/BPU.
- Dedicated BPU temperature from hwmon `name=pvt`, `temp2_input`, isolated from the fast sampler with bounded retries. A CPU-temperature proxy is a **separate explicitly labeled measurement**.
- ROS2 default probe deadline eight seconds, specific failure diagnostics, duration/last-success/failure count, retained stale graph and recovery. Combined-image calibration discovery is included; absent JPEG publishers do not invalidate the camera graph.
- Accurate CPU aggregation across zero-jiffy core samples; genuine gaps remain visible, including isolated observations and missed WebSocket sequences.
- Explicit staged upgrade and rollback workflow with stable backup/recovery scripts. No upgrade is executed automatically.

Unavailable measurements remain null with source/reason/timestamp/age/stale metadata. The installed monitoring application has no control endpoints or image subscriptions. The separate, opt-in camera laboratory can subscribe read-only to fixed image topics only after explicit activation.

## Physical evidence and remaining limits

The user reports 0.1.0 successfully deployed on RDK X5 / Ubuntu 22.04.5 / ARM64 / kernel 6.1.83 / Python 3.10.12. Native metrics, ARM64 image build, healthy Nginx, SSH tunnel and WebSocket telemetry worked. User-observed frontend consumption was approximately 2.1 MiB RAM / 0.04% CPU; backend approximately 52 MiB RAM. These are **user-provided 0.1.0 observations**, not new 0.1.2 benchmarks.

The user reports successful physical v0.1.2 deployment, healthy backend and
frontend, isolated ARM64 dependencies and pip check, BPU idle 0% at 996 MHz,
dedicated-temperature errno 110 with labeled CPU proxy, and approximately
36.42 MiB backend / 2.016 MiB frontend memory. The service ROS logging failure
is confirmed; see [ROS2_LOGGING_COMPATIBILITY.md](docs/ROS2_LOGGING_COMPATIBILITY.md).
Dynamic BPU inference-load testing and physical rollback remain pending. Local
automated validation uses mocked hardware and does not substitute for physical validation. v0.1.3 was subsequently deployed and last observed healthy; physical rollback and camera reconnect remain untested. Container inventory remains unavailable; only service state is monitored.

## Local development

Do not run the target installer/upgrade on the workstation. Use an isolated venv; no sudo pip.

```bash
cd /home/uname/rdk/rdk-platform
env -u PYTHONPATH -u PYTHONHOME python3.10 -m venv .venv
env -u PYTHONPATH -u PYTHONHOME .venv/bin/python -m pip install -r backend/requirements.txt -r tests/requirements.txt
./scripts/start.sh --mock
```

Another terminal:

```bash
cd /home/uname/rdk/rdk-platform/frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:8088`. Backend remains `127.0.0.1:8089`. Mock mode has a prominent banner. Foreground processes stop with Ctrl+C. If those ports are already occupied, preserve the existing listener; use the isolated QA harness instead.

## Validation

Run the workstation-only comprehensive checks from the project root:

```bash
./scripts/qa-full.sh
```

The [unified QA guide](docs/UNIFIED_QA_GUIDE.md) documents tool-path overrides, required checks, machine-readable results and artifact protection. The historical reports retain their original test counts; see [implementation status](docs/IMPLEMENTATION_STATUS.md) for the latest result. QA uses synthetic data and does not establish physical acceptance.

## Deployment and operation

The installed target is v0.1.3 as last observed. The development laboratory is not a deployment candidate. For future separately authorized maintenance, review the historical [deployment documentation](docs/DEPLOYMENT.md) and [release reproducibility plan](docs/RELEASE_REPRODUCIBILITY_PLAN.md). Do not overlay the installed source or copy a workstation venv to ARM64.

Production access remains loopback-only by default, with the documented manual SSH tunnel. The maintenance upgrade deliberately rejects a non-loopback Nginx configuration for separate review. Existing LAN configuration files are retained in backups; this workflow does not silently change exposure policy.

- [Changelog](CHANGELOG.md)
- [Hardware interfaces and evidence](docs/HARDWARE_INTERFACES.md)
- [Read-only ROS2 service/shell diagnosis](docs/ROS2_DIAGNOSTICS.md)
- [Architecture/API](docs/ARCHITECTURE.md) and [security](docs/SECURITY.md)
- [Implementation status and physical acceptance checklist](docs/IMPLEMENTATION_STATUS.md)
- [Actual test report](docs/TEST_REPORT.md)
- Mock screenshots: [desktop](docs/screenshots/mock-overview-desktop.png), [mobile](docs/screenshots/mock-overview-mobile.png)

Physical testing and deployment require separate authorization; no work in Phase B.4 contacts the target.
