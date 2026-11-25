# Phase C: current-tree regression results

**Local acceptance satisfied using user-provided final workstation evidence.**
Codex's restricted environment previously blocked TCP socket creation; the user
subsequently ran the complete QA command on an unrestricted workstation with
exit code 0. Physical ARM64 and upgrade acceptance remain pending.

The user reports Python 3.10.22, Node 24.22.2 and npm 11.19.1: **192 Python
tests passed** in 4.80 seconds (zero failures or skips; one existing Starlette
deprecation warning) and **12 browser tests passed** in 39.1 seconds, for 204
automated tests in that final run. Ruff, both generated Compose profiles,
both Nginx templates, 12 real-proxy REST endpoints, security headers, POST
rejection, WebSocket reconnection and foreign-origin rejection passed.
Uvicorn shut down gracefully. The initial upstream connection refusals occurred
before startup and subsequent readiness checks succeeded. These are user-run
results, not tests executed by Codex.

## Tested identity and interpreter

The mounted `.git` directory has no repository metadata, so a commit ID cannot
be established. [PHASE_C_SOURCE_MANIFEST.sha256](PHASE_C_SOURCE_MANIFEST.sha256)
records SHA-256 for 67 application, configuration, deployment, QA and test
source files. Its own SHA-256 is
`aa92c5ef0736da86de6abd11f274455a962deb63a4a7d1fefdac1eab595032b3`.
Documentation and generated/installed artifacts are outside this source
manifest. CPython 3.10.22 was used; target 3.10.12 and ARM64 are not validated.
From the project root, verify this original manifest with
`sha256sum -c docs/PHASE_C_SOURCE_MANIFEST.sha256`. A separate final release
manifest is distributed with the archive; it does not replace this original.

## Full Python suite and migration

```bash
env -u PYTHONPATH -u PYTHONHOME timeout 180 .venv/bin/python scripts/qa_pytest.py -q -o faulthandler_timeout=30
```

**192 collected, 192 passed, 0 failed, 0 skipped**, 17.87 seconds, one existing
Starlette/httpx TestClient deprecation warning. Counts from earlier phases
overlap and are not added. Coverage includes HTTP/ASGI and WebSocket tests,
normal lifespan and collector shutdown, hardware mocks, dashboard data,
dependency conflict/isolation, private atomic journals and bounded command
logs, prepare failures and interruption, source/target guards, simulated direct
0.1.0 → 0.1.2 activation and 0.1.0 rollback, failed health and rollback,
interrupted swap, admin settings, CPU quota omission and retained failed 0.1.1
artifacts. Docker/systemd upgrade operations are fake fixtures, not live target
operations. TestClient is not a real TCP proxy test.

The QA selector probe was checked with simulated successful socket send and
EPERM: success left the selector unchanged and EPERM installed the fallback.
The fallback runs in the QA process; production startup launches Uvicorn directly
and does not import it. No security policy was altered.

## Production dependency isolation

Fresh `.phase-c-app-venv` was created using Python 3.10.22 with
`include-system-site-packages = false`. The initial install with cleared
`PYTHONPATH`/`PYTHONHOME` failed DNS resolution (`Name or service not known`),
and pip's normal cache was disabled by its ownership check. Existing
`/tmp/rdk-wheels` contained the pinned x86-64 wheels. The following succeeded:

```bash
env -u PYTHONPATH -u PYTHONHOME /tmp/rdk-python310/python/bin/python3.10 -m venv .phase-c-app-venv
env -u PYTHONPATH -u PYTHONHOME .phase-c-app-venv/bin/python -m pip install --no-index --find-links /tmp/rdk-wheels -r backend/requirements.txt
env -u PYTHONPATH -u PYTHONHOME .phase-c-app-venv/bin/python -m pip check
```

`pip check` reported no broken requirements. FastAPI 0.162.5, Uvicorn 0.38.0,
Pydantic 2.12.4 and psutil 7.1.3 imported from the isolated venv; `app.main`
imported as version 0.1.2. Clearing deliberately supplied `PYTHONPATH` and
`PYTHONHOME` removed them and the injected path from the interpreter search
path. This is local AMD64 validation, not target wheel or vendor validation.

## Frontend, static and configuration

`npm run typecheck`, `npm run lint`, and `npm run build` passed; package and
display source use 0.1.2. No remote assets were found in source inspection;
two intentional documentation hyperlinks remain. The subsequent user-run
workstation QA passed the desktop and mobile browser tests.

```bash
.venv/bin/ruff check backend scripts tests
.venv/bin/ruff format --check backend scripts tests
.venv/bin/python -m compileall -q backend scripts tests
for script in scripts/*.sh; do bash -n "$script" || exit 1; done
/tmp/rdk-docker-compose -f compose.yaml config -q
.venv/bin/python tests/integration/validate_compose.py /tmp/rdk-docker-compose
```

All passed, with 32 Python files format-checked. Base Compose and generated
CPU-supported/unavailable profiles validate and preserve memory/PID and
security settings. Systemd verification passed on a temporary unit copy with
only the executable/workspace path changed to the local workspace; the shipped
unit was not installed or modified. Direct verification of the shipped unit
cannot find its target-only `<target-install>/scripts/start.sh` on this workstation.

Both Nginx templates reported `syntax is ok` using temporary QA path and port
substitutions. The default then failed `socket() 127.0.0.1:18088 failed (1:
Operation not permitted)`; the LAN template likewise failed `socket()
0.0.0.0:18088`. Thus neither full `nginx -t` nor network acceptance is claimed.

## Historical restricted-environment proxy and browser blocker

The documented QA runner was invoked with the existing Chromium 1248,
standalone Compose and user-space Nginx paths, and a temporary Python wrapper
that applies the established selector workaround to its pytest invocation. It
re-ran all 192 Python tests and Compose validations successfully, then stopped
at Nginx's denied TCP socket before launching the 12 browser tests. No attempt
was made to modify the security policy. Run the following on an unrestricted
Ubuntu workstation after checking those tool paths:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/frontend"
npm run test:e2e -- --nginx /tmp/rdk-nginx/usr/sbin/nginx --compose /tmp/rdk-docker-compose --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The user subsequently ran that exact command successfully on the unrestricted
workstation; the results are summarized above. The original EPERM remains a
historical limitation of Codex's execution environment.

## Review limits and remaining work

Source review found no production import of the QA selector workaround, no
automatic mock fallback in native mode, no arbitrary command endpoint and no
new default non-loopback listener. This is not an independent security audit.
One pre-existing caveat needs review: the native service-status adapter uses
`subprocess.run(..., capture_output=True, timeout=1)` for a fixed `systemctl
show` command without an explicit byte cap, unlike the bounded ROS and upgrade
capture paths. No claim is made that every subprocess output is byte-bounded.

Physical acceptance remains: native ARM64 dependency installation and imports;
review of actual cgroup v2/systemd report and preserved quota workaround;
prepare, activation, health and rollback; BPU dynamic utilization, isolated
temperature and proxy; ROS2/camera discovery and stale recovery; WebSocket,
resource and security checks on the running board. No physical deployment was
performed. Phase D packaging remains outside this phase.
