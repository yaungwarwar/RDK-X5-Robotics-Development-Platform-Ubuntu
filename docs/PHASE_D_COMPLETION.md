# Phase D: release candidate packaging

**Locally validated release candidate, approved for controlled physical upgrade testing.**
This is not physical validation or production certification.

## Source identity

The original Phase C manifest is `docs/PHASE_C_SOURCE_MANIFEST.sha256`, not at
the project root. Its unchanged SHA-256 is
`aa92c5ef0736da86de6abd11f274455a962deb63a4a7d1fefdac1eab595032b3`;
`sha256sum -c docs/PHASE_C_SOURCE_MANIFEST.sha256` verified all 67 listed
files. No production source difference from that manifest was found. The
mounted `.git` contains no repository metadata, so no commit ID is asserted.
Documentation was updated after Phase C and is covered by the separate final
release manifest, not the historical one.

## Workstation validation evidence

The user reports running the documented full QA command on the unrestricted
Ubuntu development workstation, exit 0: Python 3.10.22, Node 24.22.2 and npm
11.19.1; **192 Python tests passed** in 4.80 seconds, 0 failures, 0 skips, one
existing Starlette deprecation warning; **12 browser tests passed** in 39.1
seconds. The 204 total is from that single final run, not added to earlier
overlapping results. Ruff, both generated Compose profiles, both Nginx configs,
12 REST endpoints through the real proxy, security headers, POST rejection,
WebSocket reconnect and foreign-origin rejection passed. Uvicorn shut down
gracefully. Initial upstream refusals preceded readiness. This is user-provided
evidence, not a Codex-executed workstation run. Codex independently ran the
192 Python tests, isolated AMD64 dependency installation, `pip check`, frontend
build, static checks and Compose profiles; its sandbox denied TCP socket creation.

## Release artifacts and verification

- Archive: `release/rdk-control-center-0.1.2.tar.gz`, **141506 bytes**;
  SHA-256 `d23c1248a44f18ba8878a0443a1b923b95b1401fff86af67ef7a8b49731cd1cd`.
- Checksum: `release/rdk-control-center-0.1.2.tar.gz.sha256`.
- Separate 88-file release source manifest:
  `release/rdk-control-center-0.1.2-source-manifest.sha256`, SHA-256
  `f7559518989e995d994659f9e094db8d8537bedcf764dc5dc38600f996d3ae04`.
- Release notes: `release/RELEASE_NOTES.md`.

Checksum verification passed. Archive inspection found a single `rdk-platform/`
root, 108 entries including 88 files, and no absolute/parent traversal paths,
symlinks, environments, node_modules, caches, generated deployments, release
directory or other excluded artifacts. A fresh temporary extraction matched all
88 manifest hashes. VERSION, backend and frontend versions, Compose image tag,
upgrade source/target constants and rollback health version, plus required
installer, recovery, frontend, service and deployment files were checked.
The source manifest includes the final documentation as packaged. This Phase D
completion report and release notes were written after packaging and are outside
the archive; they are not part of that manifest.

README, changelog, deployment, architecture, security, isolation, recovery,
implementation status and test reports now distinguish user-run final QA from
Codex's results and earlier physical observations. The 0.1.1 preparation
conflict is confirmed as zope-event 5.1.1 requiring setuptools >=75.8.2 while
the staged venv saw 59.6.0; exact package locations remain unknown. The v0.1.1
cgroup detector was physically observed reporting v2/systemd, unavailable
CPU quota and available memory/PID controllers; it does not prove 0.1.2 upgrade
success.

## Physical acceptance and limits

- Validate ARM64 dependency installation, `pip check`, and backend/ROS imports.
- Inspect cgroup compatibility, preserved administrator config and quota
  workaround, private backup, logs and PREPARED state before activation.
- In a controlled maintenance window, validate 0.1.2 activation and health,
  SSH tunnel/WebSocket, then explicit rollback to 0.1.0 as appropriate.
- Validate dynamic BPU utilization, dedicated temperature behavior and the
  separately labeled CPU proxy; validate native ROS2/camera discovery and stale
  recovery. Do not change vendor software or watchdog/cgroup settings.
- The fixed systemctl status subprocess has a one-second timeout without an
  explicit captured-output byte cap. Credential redaction is best-effort.
  Authentication and TLS are not implemented; default access is loopback-only
  via an SSH tunnel. The Starlette test warning remains.

No physical v0.1.2 deployment, remote installation or hardware acceptance was
performed by Codex. See `docs/DEPLOYMENT.md` for exact manual commands.
