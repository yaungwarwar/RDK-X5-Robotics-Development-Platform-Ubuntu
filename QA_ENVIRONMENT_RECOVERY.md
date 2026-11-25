# QA environment recovery after reboot

Status on 2026-11-25: **recovery is incomplete**. The Codex environment could not resolve GitHub or Ubuntu package hosts, so the missing interpreter, Nginx and Compose could not be downloaded. No Python or browser regression was run during this recovery. The instructions below are a proposed recovery procedure for an internet-connected workstation; their download and installation steps have not yet been validated here.

## Diagnosis and preserved evidence

`.venv/bin/python` -> `python3.10` -> `/tmp/rdk-python310/python/bin/python3.10`; the final target is missing. `.venv/pyvenv.cfg` records Python 3.10.22 and `include-system-site-packages = true`. The runner therefore reports `spawnSync ... ENOENT`. The `.phase-c-app-venv` interpreter points to the same missing location. Both environments remain untouched for diagnosis. The former `/tmp/rdk-nginx/usr/sbin/nginx`, `/tmp/rdk-docker-compose` and `/tmp/rdk-wheels` are also missing. The system has Python 3.12.3 and Docker CLI, but no Nginx or Docker Compose; 3.12 with the original pins has not been validated. Node 24.22.2 and npm 11.19.1 are available. Chromium is present at `$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome` (version 156.0.8078.4); the QA command explicitly selects it, since this project's Playwright expects a different cached revision by default.

The 0.1.3 archive matches SHA-256 `07cf0439383e6fc207ca47517ffeb62f56603be4fb136e08f42e15c31e6cd37b`; all 91 entries of the 0.1.3 release manifest matched the working tree when checked from `$HOME/rdk`. No release source was altered and no manifest was regenerated. This workspace has no accessible Git metadata, so Git status cannot be used to detect extra unmanifested files.

## Restore on the workstation

The preferred `$HOME/rdk/tools` is outside this session's writable roots. The following uses `.venv-qa-tools`, already covered by the existing `.venv*/` ignore rule, and `.venv-recovered`, also ignored. Keep both out of release packaging. The original `.venv` stays in place; explicitly pass the recovered Python to the runner. These commands assume Ubuntu 24.04 amd64, network access, the existing `$HOME/.local/bin/uv`, and the same package index used for the pinned requirements. Do not run them against the target device.

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}"
mkdir -p .venv-qa-tools/python .venv-qa-tools/cache .venv-qa-tools/downloads .venv-qa-tools/bin
export UV_CACHE_DIR="$PWD/.venv-qa-tools/cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.venv-qa-tools/python"
"$HOME/.local/bin/uv" python install --no-bin 3.10.22
PY310=$("$HOME/.local/bin/uv" python find --managed-python 3.10.22)
"$PY310" --version
env -u PYTHONPATH -u PYTHONHOME "$PY310" -m venv .venv-recovered
env -u PYTHONPATH -u PYTHONHOME .venv-recovered/bin/python -m pip install -r backend/requirements.txt -r tests/requirements.txt
env -u PYTHONPATH -u PYTHONHOME .venv-recovered/bin/python -m pip check
env -u PYTHONPATH -u PYTHONHOME .venv-recovered/bin/python -c 'import fastapi, uvicorn, psutil, pydantic, pytest, httpx, websockets, ruff; print("Python QA imports OK")'
(cd backend && env -u PYTHONPATH -u PYTHONHOME ../.venv-recovered/bin/python -c 'import app.main; print("application import OK")')
```

Download and extract the Ubuntu packages without installing them system-wide. Use the version supplied by the workstation's configured Ubuntu repositories. These steps do not start a service or contact the Docker daemon. Check `ldd` for missing shared libraries and fix them in user-owned storage if necessary.

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/downloads"
apt-get download nginx docker-compose-v2
mkdir -p ../nginx ../compose
for pkg in nginx_*.deb; do dpkg-deb -x "$pkg" ../nginx; done
for pkg in docker-compose-v2_*.deb; do dpkg-deb -x "$pkg" ../compose; done
COMPOSE=$(find "$PWD/../compose" -type f -name docker-compose -print -quit)
test -n "$COMPOSE"
ln -sfn "$(realpath "$COMPOSE")" ../bin/docker-compose
../nginx/usr/sbin/nginx -v
ldd ../nginx/usr/sbin/nginx
../bin/docker-compose version
```

After a successful installation, validate and run the full Python regression under the restricted environment with the existing QA selector helper:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}"
env -u PYTHONPATH -u PYTHONHOME timeout 180 .venv-recovered/bin/python scripts/qa_pytest.py -q -o faulthandler_timeout=30
```

For full workstation browser/proxy QA, first check that ports 18088 and 18089 are free without stopping any existing process. From an unrestricted workstation, run this exact command after the recovery steps succeed:

```bash
cd "${RDK_WORKSPACE:?set the absolute checkout path}/frontend"
env -u PYTHONPATH -u PYTHONHOME npm run test:e2e -- --python "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-recovered/bin/python" --nginx "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/nginx/usr/sbin/nginx" --compose "${RDK_WORKSPACE:?set the absolute checkout path}/.venv-qa-tools/bin/docker-compose" --browser "$HOME/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
```

The runner repeats the Python tests, validates Compose profiles and Nginx configurations, then runs browser and live proxy checks. It owns and stops only its spawned QA processes. It does not build the frontend; run `npm run build` first if `frontend/dist` is absent or stale. A restricted Codex session may prohibit TCP socket creation; use the workstation for this acceptance run, without changing security policy. Record the actual outputs and exit status before claiming acceptance.

After future reboots these project-local paths should persist. If they are missing, repeat the installation; if the browser cache has been cleaned, install the Chromium revision required by the project's Playwright and update the explicit browser path. Check release integrity from the parent directory with `sha256sum -c rdk-platform/release/rdk-control-center-0.1.3-source-manifest.sha256` and verify the archive separately against the hash above.
