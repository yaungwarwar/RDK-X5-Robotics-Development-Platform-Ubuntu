# Phase B: versioning and direct migration

## Changes

The active development version is 0.1.2 in `VERSION`, backend application,
health and telemetry metadata, frontend package/lock and displayed version,
Compose and upgrade image tag. Backend API and telemetry use one Python
constant; frontend display reads the package version. Current security text and
deployment instructions describe 0.1.2. Historical release notes, physical
0.1.0 observations, the failed 0.1.1 staging paths and earlier test reports
retain their original version numbers. Test fixtures explicitly distinguish the
0.1.0 source, 0.1.2 target and unsupported versions.

Only **0.1.0 → 0.1.2** is supported; rollback restores **0.1.0**. Other
installed versions, including 0.1.1 and 0.1.2, and incorrect staged versions
are rejected. The preparation and activation journals identify source/target,
expected health versions, old image ID/tag, new tag, staged source hashes and
compatibility config hash. Activation checks metadata agreement and hashes
before stopping the service. Standalone recovery copies remain in the backup.
Simulations cover activation, health failure, rollback, interrupted swap,
administrator settings, omitted CPU quota with memory/PID limits, and unrelated
failed 0.1.1 artifacts. No physical target was contacted.

## Validation (Python 3.10.22)

```bash
.venv/bin/python -m pytest -q tests/unit/test_deployment.py tests/unit/test_dependency_isolation.py tests/unit/test_config_and_freshness.py tests/integration/test_api.py::test_release_version_consistent_in_health_and_snapshot
.venv/bin/ruff check backend scripts tests
.venv/bin/ruff format --check backend scripts tests
.venv/bin/python -m compileall -q backend scripts tests
```

The selected tests passed: **91 passed, 0 failed**, with one existing
Starlette TestClient deprecation warning. Ruff lint and formatting (30 files),
compile checks and shell syntax checks passed. Frontend typecheck, lint and
production build passed. Standalone Compose validated the base configuration
and CPU-supported and CPU-unavailable profiles. The direct API version test
calls the health handler and verifies the telemetry snapshot; it does not
exercise an HTTP transport.

An additional attempt to run the complete API integration test group did not
finish: Starlette TestClient hung entering its AnyIO blocking portal. A separate
targeted TestClient attempt showed the same stall, and both were stopped; no
pass or application failure was inferred at that time. No
browser suite was run in this phase.

## Follow-up: Phase B.1

The HTTP integration blocker was traced to a denied local socket wakeup in the
test execution environment. With the test-only polling runner, the complete HTTP
integration group passed, including real TestClient HTTP/ASGI and WebSocket
transport and the normal application lifespan. See [PHASE_B1_COMPLETION.md](PHASE_B1_COMPLETION.md)
for the reproduction, exact commands, and subsequent results.

## Acceptance and remaining work

The scoped implementation and focused validation, including the HTTP API
integration group with the documented QA runner, are complete. The new code has not
been tested on physical ARM64 hardware. Phase C must run the complete release
regression and physical acceptance checks;
Phase D must produce and verify the source-only release archive and checksum.
Version 0.1.2 remains a development release, not release-ready.
