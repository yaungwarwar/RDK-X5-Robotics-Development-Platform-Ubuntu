# Camera prototype test report — synthetic workstation only

On Ubuntu 24.04 AMD64 with persistent Python 3.10.22, recovered venv and existing Chromium, Phase A exercised a standalone synthetic process. The physical RDK was not accessed for this phase. No vendor packages or ROS image subscriptions were used; all generated pictures are visibly MOCK DATA.

The complete regression reported **213 Python tests passed** (including the existing 201 baseline and focused laboratory/QA additions), **12 existing dashboard browser tests passed**, and **6 laboratory browser tests passed**, for 231 test cases. The Python total includes a wrapper test invoking three Node QA-guard scenarios; those are not added a second time. Strict `pip check`, existing frontend build/lint, lab TypeScript check, both Nginx syntax checks, real proxy HTTP/WebSocket/security checks and both Compose compatibility profiles passed. The existing Starlette TestClient deprecation and browser color-environment warnings remain non-failing.

Python and browser checks exercise activation, stop, all view choices, synthetic producer cancellation, stale-source indication, invalid/unsupported/oversized synthetic messages, latest-slot replacement under a slow client, ACK timeout, max clients, unauthorized origin, disconnect/reconnect and cleanup. A simultaneous mock telemetry test confirms sequence advancement while synthetic preview runs. The QA guard tests reject occupied ports and a failed child in the presence of another listener, interrupt guarded tests on loss of owned listener, and leave unrelated listeners untouched. These are synthetic/local tests, not proof of real ROS serialization, physical encodings, DDS/QoS, target performance or real camera acceptance.

Desktop and mobile screenshots: [desktop](screenshots/camera-lab-desktop.png), [mobile](screenshots/camera-lab-mobile.png). FPS and bandwidth are local synthetic delivery metrics; availability and calibration show unavailable; process metrics describe the lab itself. Real camera publisher disappearance has not been exercised; the browser test injects a synthetic frame and stops sending frames.

Reproduce from the workspace (no physical device):

```bash
frontend/node_modules/.bin/tsc --noEmit -p frontend/camera-lab/tsconfig.json
frontend/node_modules/.bin/vite build --config frontend/camera-lab/vite.config.ts
RDK_TEST_BROWSER=/home/eve/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome frontend/node_modules/.bin/playwright test --config frontend/camera-lab/playwright.config.ts
cd frontend
env -u PYTHONPATH -u PYTHONHOME npm run test:e2e -- --python /home/eve/rdk/rdk-platform/.venv-recovered/bin/python --nginx /home/eve/rdk/rdk-platform/.venv-qa-tools/nginx/usr/sbin/nginx --compose /home/eve/rdk/rdk-platform/.venv-qa-tools/bin/docker-compose --browser /home/eve/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
```

For interactive preview, build the lab as above, then run `.venv-recovered/bin/python prototype/camera_lab/server.py` from the workspace and open `http://127.0.0.1:18100/`. Stop the process after use. It is a laboratory service, not a production endpoint. The existing release archive and original manifest were not regenerated.
