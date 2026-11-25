# Phase B camera worker local test report

Local validation uses synthetic image fixtures and mocked ROS interfaces; no physical board or real ROS graph was contacted. `tests/fixtures/fake_ros` is test-only. Tests launch the actual native worker with `/usr/bin/python3` against those mock modules, plus separate actual subprocesses that exercise the broker's framed IPC and supervisor. They verify fixed ROS topics and logging-init option, supported RGB/BGR/mono PNG conversion, compressed JPEG/PNG framing, invalid encodings, lengths, dimensions and calibration, IPC version/size/partial data, native worker startup, single-worker exclusion, crash, startup timeout, heartbeat timeout, disconnect during startup, TERM/KILL cleanup, native frame and calibration delivery, and no synthetic fallback after failure. These mocks do not establish device compatibility.

The recovered workstation environment completed 235 Python tests, 12 existing dashboard browser tests and 10 laboratory browser tests (257 total). See [Phase B completion](V0.2.0_PHASE_B_COMPLETION.md) for final exact results and [Phase A test report](CAMERA_PROTOTYPE_TEST_REPORT.md) for the historical baseline. The full runner exercises real Nginx, Compose profiles and QA listener ownership. Native browser tests inject mock image/calibration messages; they are not a live camera stream. One existing Starlette TestClient deprecation warning and browser color warnings are non-failing.

Reproduce on the development workstation:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}"
.venv-recovered/bin/python -m pip check
.venv-recovered/bin/python -m ruff check backend scripts tests prototype/camera_lab
.venv-recovered/bin/python -m ruff format --check backend scripts tests prototype/camera_lab
.venv-recovered/bin/python -m compileall -q backend scripts tests prototype/camera_lab
frontend/node_modules/.bin/tsc --noEmit -p frontend/camera-lab/tsconfig.json
frontend/node_modules/.bin/vite build --config frontend/camera-lab/vite.config.ts
RDK_TEST_BROWSER="$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome" frontend/node_modules/.bin/playwright test --config frontend/camera-lab/playwright.config.ts
cd frontend
env -u PYTHONPATH -u PYTHONHOME npm run test:e2e -- --python "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-recovered/bin/python" --nginx "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/nginx/usr/sbin/nginx" --compose "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/bin/docker-compose" --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The native child is exercised separately under `/usr/bin/python3` by the mock-ROS test; the remaining suite uses `.venv-recovered`. No actual GS130WI encoding, QoS, calibration or physical performance limits have been validated. PNG validation checks chunk CRC and structure; JPEG validation checks bounded marker structure and dimensions but relies on browser decoding for full image decode. Physical rollback remains untested.
