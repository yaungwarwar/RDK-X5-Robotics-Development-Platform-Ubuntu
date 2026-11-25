# Phase B.1: HTTP integration test blocker

## Finding

The smallest failing case needs neither pytest nor the application: an AnyIO
blocking portal starts, but `portal.call(lambda: 42)` hangs. Its portal thread
is blocked in `selectors.select`; the caller waits in AnyIO's
`run_sync_from_thread` for the callback. Python thread creation/join and a
same-thread asyncio loop both pass. A local socketpair can be created, but
`socket.send()` on it raises `PermissionError: [Errno 1] Operation not
permitted`; an asyncio `call_soon_threadsafe` callback then fails to wake the
selector. The same socket send fails with `/usr/bin/python3` 3.12.3. TCP socket
creation also returns EPERM here. `/proc/self/status` reports seccomp mode 2
and one filter, but we did not inspect the filter or establish which policy
produces the denial. This is a confirmed restriction of this execution
environment, not evidence of an application or dependency defect.

With the unmodified selector, bounded independent TestClient diagnostics for
minimal Starlette, minimal FastAPI, RDK mock without its lifespan, and RDK mock
with its normal lifespan all stalled at the portal, exiting via a 3-second
faulthandler deadline. With periodic selector polling, all four completed; the
normal RDK mock returned HTTP 200 and shut down. This isolates the failure
before application startup, so it does not establish a monitor executor defect.

## Environment

The interpreter is `.venv/bin/python`, CPython 3.10.22, based on
`/tmp/rdk-python310/python`. Its `pyvenv.cfg` says
`include-system-site-packages = true`: the effective path contains both
`.venv/lib/python3.10/site-packages` and the base interpreter's site-packages.
The latter contains pip and setuptools. This development QA venv is distinct
from the isolated application venv created on the target. `PYTHONPATH` and
`PYTHONHOME` were unset in the validation commands; pytest's configuration
adds the project `backend` and `scripts` paths. The inspected packages below
resolve from the project venv:

| Package | Version |
| --- | --- |
| FastAPI | 0.162.5 |
| Starlette | 1.7.0 |
| AnyIO | 4.16.0 |
| httpx | 0.28.1 |
| httpcore | 1.0.9 |
| pytest | 9.0.1 |
| Uvicorn | 0.38.0 |

`pytest-asyncio` and `httpx2` are absent; pytest's trace showed the AnyIO plugin
and built-in plugins. `pip check` passed. No dependencies were changed, and no
system packages were modified. Starlette emits its existing warning recommending
httpx2; the current dependency set was retained.

## Change and validation

`scripts/qa_pytest.py` probes the socketpair send and, only if it returns EPERM,
caps selector sleep at 50 ms in the test runner process. It does not change
security policy, enable network access, alter production code, replace the HTTP
transport, or change the application's executor/lifespan. On systems where the
send works it leaves the selector unchanged. A subprocess regression checks the
cross-thread portal using this runner setup. The release-version test now uses
TestClient HTTP requests and explicitly checks that the collector tasks finish
and the executor shuts down after lifespan exit. Existing HTTP and WebSocket
assertions remain intact.

```bash
env -u PYTHONPATH -u PYTHONHOME timeout 60 .venv/bin/python scripts/qa_pytest.py -q -o faulthandler_timeout=15 tests/integration/test_api.py
env -u PYTHONPATH -u PYTHONHOME timeout 75 .venv/bin/python scripts/qa_pytest.py -q -o faulthandler_timeout=15 tests/unit/test_deployment.py tests/unit/test_dependency_isolation.py tests/unit/test_config_and_freshness.py tests/unit/test_maintenance.py tests/unit/test_qa_runner.py tests/integration/test_api.py
.venv/bin/ruff check scripts/qa_pytest.py tests/integration/test_api.py tests/unit/test_qa_runner.py
.venv/bin/ruff format --check scripts/qa_pytest.py tests/integration/test_api.py tests/unit/test_qa_runner.py
.venv/bin/python -m compileall -q scripts/qa_pytest.py tests/integration/test_api.py tests/unit/test_qa_runner.py
```

The complete HTTP API group passed **26 tests**; the combined migration,
isolation, configuration, maintenance, portal regression and HTTP run passed
**155 tests**, with one existing deprecation warning and no failures. Ruff,
format and compile checks passed. HTTP coverage includes endpoint and snapshot
data, mode, health, security headers and host/origin restrictions, mutation
rejection, WebSocket reconnect/rejection, stale data, shared sampling, BPU and
ROS diagnostics, version metadata and startup/shutdown.

For a bounded reproduction without the workaround, run:

```bash
env -u PYTHONPATH -u PYTHONHOME timeout 8 .venv/bin/python -X faulthandler -c 'import faulthandler,anyio.from_thread; faulthandler.dump_traceback_later(4,exit=True); p=anyio.from_thread.start_blocking_portal(); portal=p.__enter__(); print(portal.call(lambda: 42),flush=True); p.__exit__(None,None,None)'
```

The denial is environment-specific; a host that permits socketpair send should
complete normally without the polling workaround. The test runner does not
validate real TCP networking in this sandbox. No complete browser suite, physical
target operation, or release packaging was performed. Phase B focused acceptance
is satisfied; full release regression, physical acceptance and packaging remain
outstanding.
