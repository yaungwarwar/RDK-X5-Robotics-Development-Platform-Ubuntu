# QA infrastructure

For current development validation use the [unified QA guide](UNIFIED_QA_GUIDE.md) and `./scripts/qa-full.sh`. The following v0.1.3 figures and commands are historical and do not represent the latest complete suite.

On 2026-11-25 the Ubuntu 24.04 AMD64 workstation recovered persistent Python 3.10.22 under `.venv-qa-tools/python`, the isolated `.venv-recovered`, Nginx 1.24.0 under `.venv-qa-tools/nginx`, Compose 2.40.3 under `.venv-qa-tools/bin/docker-compose`, and downloaded dependency wheels under `.venv-qa-tools/wheels`. Chromium was reused from `$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`. DNS, HTTPS and local TCP sockets worked. These ignored development directories are not release artifacts.

With the existing pinned requirements, strict `pip check` and imports passed. The complete local suite passed 201 Python tests and 12 desktop/mobile Chromium tests (213 total). Both Nginx configurations, the real proxy, 12 live endpoints, security headers, POST and origin rejection, WebSocket reconnect, and generated Compose CPU profiles passed. One existing Starlette TestClient deprecation warning was reported. The suite was rerun with external process observation: the runner's own Nginx held 127.0.0.1:18088 and exited; both QA listeners disappeared. Before the run both ports were bindable; immediately afterward neither had a listener and both could bind with `SO_REUSEADDR`, although a plain bind encountered a transient address-in-use condition.

## QA-INFRA-001 — addressed in Phase A local runner

The historical v0.1.3 runner could accept an older listener after its own Nginx failed to bind. The working-tree Phase A runner now checks both IPv4/IPv6 loopback ports before startup, detects child failure, correlates Linux `/proc` listener socket inodes with the spawned backend and Nginx process file descriptors, rechecks ownership during and after live and browser checks, and stops only its spawned QA services. Guarded test subprocesses run in their own process group so loss of ownership terminates that group. Regression checks cover occupied ports, unrelated listeners, startup failure and service loss. Port preflight and launch cannot be atomic; listener ownership checks close the identified false-positive path. This Linux-specific development runner fails closed if `/proc` ownership cannot be verified. The original archive is unchanged.

For a future regression, after verifying the ports are free and ownership can be observed, run:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/frontend"
env -u PYTHONPATH -u PYTHONHOME npm run test:e2e -- --python "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-recovered/bin/python" --nginx "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/nginx/usr/sbin/nginx" --compose "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/bin/docker-compose" --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The wheel directory can be used with `pip install --no-index --find-links $RDK_WORKSPACE/.venv-qa-tools/wheels -r ...`. Unpinned transitive requirements may resolve differently when wheels are refreshed. The historic `.venv` points to a missing temporary interpreter; use `.venv-recovered` explicitly. No target hardware acceptance follows from workstation results.
