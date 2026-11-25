# Current local QA — v0.1.3 (2026-11-25)

The recovered persistent Python 3.10.22 environment passed 201 Python tests and 12 browser tests (213 total), strict pip check and imports. Both real Nginx configurations, live proxy and generated Compose profiles passed. An observed run confirmed the QA runner's own Nginx held port 18088 and terminated, leaving no QA listeners; QA-INFRA-001 remains open in the runner. One existing Starlette deprecation warning was reported. See [QA infrastructure](QA_INFRASTRUCTURE.md) for paths and details. These tests do not establish physical v0.1.3 acceptance; see [physical acceptance](V0.1.3_PHYSICAL_ACCEPTANCE.md).

The following reports are historical. Earlier references to blocked TCP or temporary QA executable paths describe the earlier session and are superseded by the recovered environment.

---

# Actual local test report — 0.1.1

## v0.1.3 local maintenance validation

On Python 3.10.22 the full local Python suite reported **201 passed**, no
failures or skips, one existing Starlette deprecation warning, in 18.13s. The
focused ROS2, deployment and maintenance run passed 107 tests. Ruff lint,
format check (33 files), compile and shell syntax checks, frontend typecheck,
lint and production build, base Compose and both generated CPU profiles passed.
ROS2 tests use mocks and migration tests simulate systemd and Docker; they do
not validate physical v0.1.3. The current sandbox rejects `socket(AF_INET,
SOCK_STREAM)` with EPERM, so real proxy and browser validation has not been
run for v0.1.3. On an unrestricted workstation use:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/frontend"
npm run test:e2e -- --nginx /tmp/rdk-nginx/usr/sbin/nginx --compose /tmp/rdk-docker-compose --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The user reports v0.1.2 physical deployment and isolated ARM64 dependency check
passed; that evidence does not validate v0.1.3. Dynamic BPU load and physical
rollback remain pending. See `ROS2_LOGGING_COMPATIBILITY.md`.

## Current 0.1.2 final workstation QA

The user reports final unrestricted-workstation QA exit 0: **192 Python tests
and 12 browser tests passed (204 total)**, with no Python failures or skips and
one existing Starlette deprecation warning. Both Nginx configs, real proxy,
security headers, mutation/origin rejection and WebSocket reconnection passed.
Codex separately ran 192 Python tests, isolated dependency checks, static,
frontend build and Compose checks; Codex's real TCP checks were blocked by
EPERM. See [PHASE_C_COMPLETION.md](PHASE_C_COMPLETION.md) for the distinct
evidence. The sections below are historical and do not add to these totals.

## v0.1.2 work in progress (2026-11-24)

Before the latest preparation-journal edits, the project QA runner used Python
3.10.22 and reported **155 Python tests passed**, **12 browser tests passed**,
and successful Compose CPU-supported/CPU-unavailable and both Nginx checks.
The browser runner used the existing Chromium 1248 executable with the project's
`--browser` override. Frontend TypeScript, lint and build passed in the prior
work session. After the latest journal changes, the focused deployment and
dependency-isolation groups reported **39 passed**; a fresh full run is required.
The synthetic zope-event 5.1.1 / setuptools 59.6.0 conflict test passes on
Python 3.10.22. The project `.venv` inherits system site packages and is not
evidence that the release application venv is clean; the synthetic test creates
an isolated venv and verifies `pip check` there. No physical v0.1.2 test has
been performed. This paragraph records an earlier work-in-progress state.

Date: 2026-11-24. Local Ubuntu 24.04 / AMD64 development only. No SSH connection, physical deployment, target upgrade, watchdog/vendor modification, public hosting or GitHub push occurred.

## Regression baseline before application changes

- Existing v0.1.0 Python suite: **79 passed**, one existing non-failing Starlette/httpx transport deprecation warning.
- Existing desktop/mobile browser suite: **six passed** in 31.1 seconds.
- Initial QA encountered an already occupied workstation port 8088; it was preserved. The QA harness alone was moved to owned 18088/18089 listeners, with temporary proxy/origin remapping. Production ports and security defaults remain unchanged.
- Existing tests were retained. Necessary assertions changed only for the eight-second ROS2 deadline/bounded runner injection and the verified eight-known-topic fixture (JPEG absent, combined calibration topics present). No test was removed or skipped.

## Final validation

| Check | Actual local result |
|---|---|
| Python unit/API/integration regression suite | **149 passed**, 0 failed, 0 skipped in 0.95 seconds; actual CPython 3.10.22 |
| Original browser scenarios | Preserved and passed at desktop/mobile viewports |
| Expanded browser suite | **12 passed** in 39.1 seconds: adds BPU zero/proxy/dedicated absence/ROS2 retained failures honest CPU gaps/isolated valid points and an existing-tab transition back to the old API after rollback at both viewports |
| Real proxy integration | All 12 REST routes, security headers, mutation rejection, WebSocket reconnection and foreign-origin rejection pass through local Nginx |
| Frontend TypeScript | Passed |
| Frontend ESLint | Passed |
| Production build | Passed Vite 6.4.6; JS 232.90 kB / 71.19 kB gzip, CSS 16.32 kB / 4.22 kB gzip |
| Python Ruff / formatting | Passed; 28 Python files formatted/checked |
| Python compile/import | Actual Python 3.10 suite and compileall passed |
| Dependency consistency | Isolated venv pip check passed; dependency versions preserved from 0.1.0 |
| npm audit | Zero reported vulnerabilities on this run |
| Compose base and generated profiles | v2.40.3 validated both CPU-supported/quota and CPU-unavailable/no-quota standalone configs; memory/PID and execution controls retained |
| Nginx configurations | Default and optional LAN templates pass nginx -t with temporary test-path/QA-port substitutions; no workstation Nginx service installed |
| Shell syntax | All seven scripts pass bash -n |
| systemd template | Read-only systemd-analyze verify passes on a temporary copy with local executable/workspace paths; actual shipped unit unchanged from 0.1.0 |
| Installer architecture guard | Local AMD64 --check refuses before installation changes |
| Read-only environment helper | Executed locally for its own process; output is allowlisted and profile values hashed |
| Docker build/container execution / ARM64 / native DDS / physical sensors | Not executed locally for 0.1.1; target acceptance pending |

The test interpreter was isolated Python **3.10.22**, not the target's exact 3.10.12 patch release. Node v24.22.2/npm 11.19.1, extracted user-space Nginx 1.24.0, standalone Compose 2.40.3 and local Chromium with Playwright 1.58.2 were used. Browser viewports: desktop 1440×1100 and mobile 390×844. No dependency upgrades or system-package changes were made for this maintenance release.

One existing non-failing warning remains: Starlette deprecates its httpx TestClient transport. Browser tooling may report the inherited NO_COLOR/FORCE_COLOR warning. Nginx readiness polling can briefly see upstream refusal while Uvicorn starts; subsequent integration requests pass. These warnings are distinct from application test failures.

## Added regression evidence

- Effective cgroup CPU availability despite kernel capability, supported parent/leaf hierarchy, v1/v2 drivers, required memory/PID failure/permission handling, local Docker context restrictions and generated configuration immutability/security.
- BPU ratio zero and valid percentages, malformed/missing/denied/out-of-range data; precise devfreq normalization without 100 MHz rounding.
- hwmon name discovery, missing dedicated sensor, independent proxy, bounded timeout, unreaped-child quarantine and retry/backoff. An uninterruptible read is simulated; no real kernel hang is claimed.
- ROS2 timeout, nonzero exit, malformed JSON, invalid schema (including JSON null), successful empty graph, simulated 3.394-second success within the eight-second deadline, retained original graph timestamps/stale flags, transient recovery, no overlap and bounded/sanitized stderr.
- Actual local child-process timeout, stdout size rejection, stderr capture limit and subsequent slot recovery, without ROS2/hardware.
- CPU zero-jiffy core handling versus real counter resets, preserved chart gaps and isolated-point rendering.
- Upgrade staging/backups without service interruption, apply/explicit rollback, automatic rollback after simulated health failure, interrupted directory-move recovery and changed-admin/staged-source refusal and recursive-backup destination rejection. Docker/systemd/target operations in these tests are fake runners over temporary filesystem fixtures; no live service is altered.

## Reproduce

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/frontend"
npm run typecheck
npm run lint
npm run build
npm run test:e2e -- --nginx /tmp/rdk-nginx/usr/sbin/nginx --compose /tmp/rdk-docker-compose --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The QA runner uses the project `.venv/bin/python`, starts/stops only its owned local Uvicorn/Nginx processes on 18088/18089, runs Python checks and generated Compose validations, then tests the production static build. Ordinary systems can use Nginx/Chromium on their normal local paths; README documents overrides. Do not run the installer/upgrade on the workstation.

## Screenshots and physical evidence boundaries

Mock screenshots under `screenshots/` include Overview desktop/mobile and BPU/ROS2 maintenance diagnostics desktop/mobile. They prominently display MOCK DATA. The BPU screenshot intentionally simulates ratio zero and an unavailable dedicated sensor with a CPU proxy; ROS2 screenshots intentionally simulate a retained graph after timeout. They are not physical observations.

The user's prior successful **physical 0.1.0** deployment, resource measurements, idle ratio zero, pvt mapping/read error and standalone ROS2 graph/timings are accepted as supplied evidence and documented separately. They are not relabeled as physical 0.1.1 tests. [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) lists every remaining physical acceptance item, including dynamic BPU load, actual environment root cause, container execution and real upgrade/rollback.
