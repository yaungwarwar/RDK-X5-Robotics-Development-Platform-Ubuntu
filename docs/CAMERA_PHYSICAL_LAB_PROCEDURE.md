# RDK X5 stationary camera laboratory — approval required

This is a **future procedure**, not an execution record. Separately obtain the user's approval for physical camera subscriptions and testing, confirm a stationary safe bench, and verify the camera publisher is already running. Do not start or restart a camera, the installed v0.1.3 service, Docker, or any robotics process. Do not change DDS settings, `ROS_DOMAIN_ID`, vendor files or systemd protections. Do not run on a robot or vehicle in motion. Do not publish or record frames. No approval or physical testing occurred in Phase B.

The standalone lab must live outside `/home/sunrise/rdk-platform` and all existing backup/staging transactions. After separate authorization, copy a reviewed development snapshot of `prototype/camera_lab` (including built `dist`) and `backend/requirements.txt` to a **fresh** user-owned bench directory, preserving all existing files. Prepare a separate isolated Python 3.10 venv in that new directory and install the pinned requirements there; do not modify system Python or the active application's venv. Ensure system `/usr/bin/python3` can import native `rclpy` and `sensor_msgs` only after sourcing the board's existing ROS environment. Do not copy `tests/fixtures/fake_ros` or use mocked ROS on the board.

Before streaming, with a separately authorized read-only inspection in the board's **existing** ROS environment, capture `ros2 node list`, `ros2 topic list -t`, and `ros2 topic info -v` for the relevant existing names. Inspect publisher types and offered QoS. Names from prior observations are `/image_left_raw`, `/image_right_raw`, `/image_combine_raw`, `/image_combine_jpeg`, `/image_left_raw/camera_info`, `/image_right_raw/camera_info`, `/image_combine_raw/left/camera_info` and `/image_combine_raw/right/camera_info`; their presence is not assumed. Do not subscribe to image data during initial graph inspection. If the camera is absent, report it pending; do not launch it.

After explicit approval for subscription, run only the standalone lab from the new bench directory. Source the board's normal `/opt/tros/humble/setup.bash` in that shell, then run the lab with its new venv Python and access 127.0.0.1:18100 only via a private SSH tunnel. Confirm this port is free before starting and stop only the process started for this test. The native child must be `/usr/bin/python3`; the lab selection is Native ROS2, raw by default; combined compressed is a separate explicit option. Never change the existing service's environment or Nginx configuration. Existing dashboard listeners stay loopback-only.

Start only one selected view at a time, inspect actual frame width, height, encoding, FPS, age, drops, worker RSS/CPU and calibration metadata, and stop it promptly. Compare actual `CameraInfo` and QoS against the publisher and check whether the supported encodings and 1280×720 / 2 MiB limits match. If not, stop and report; do not weaken limits without review. Where separately approved, test slow client/disconnect/reconnect and compare telemetry health/collector freshness, process counts, CPU, memory, bandwidth and temperature against baseline. Do not subscribe to all views simultaneously. Preserve no automatic image data. Stop the standalone lab and verify its worker has exited, the original application and camera processes remain unchanged, and the original v0.1.3 health remains good. Document actual findings and any unresolved QoS, decode, timestamp, thermal or resource issue; no physical acceptance can be inferred from mocked tests.

## Example commands — do not execute without the separate approval above

On the workstation, build the standalone page and create a reviewed laboratory-only bundle in persistent project-local storage. The bundle is a development artifact, not a release and not a deployment:

```bash
cd /home/eve/rdk/rdk-platform
frontend/node_modules/.bin/vite build --config frontend/camera-lab/vite.config.ts
mkdir -p .venv-qa-tools/bench-bundle
tar --exclude='__pycache__' --exclude='*.pyc' -czf .venv-qa-tools/bench-bundle/camera-phase-b-lab.tar.gz prototype/camera_lab backend/requirements.txt
sha256sum .venv-qa-tools/bench-bundle/camera-phase-b-lab.tar.gz
```

After the user separately approves target preparation and the safe stationary window, create a fresh bench directory and transfer the bundle using existing SSH authentication; substitute a fresh suffix if it already exists. For example, on the workstation:

```bash
ssh sunrise@192.168.1.59 'test ! -e /home/sunrise/rdk-camera-lab-phase-b && mkdir -m 700 /home/sunrise/rdk-camera-lab-phase-b'
rsync -av --ignore-existing .venv-qa-tools/bench-bundle/camera-phase-b-lab.tar.gz sunrise@192.168.1.59:/home/sunrise/rdk-camera-lab-phase-b/
ssh sunrise@192.168.1.59
```

On the target, compare the received bundle's hash with the workstation output before extraction; do not continue on mismatch. The following writes only to the fresh bench directory and makes a separate venv; network/package availability and dependency architecture must be checked. After sourcing the already installed ROS setup, preserve its Python path for the native child while removing it from the broker's isolated interpreter:

```bash
cd /home/sunrise/rdk-camera-lab-phase-b
sha256sum camera-phase-b-lab.tar.gz
# Manually compare the printed hash with the workstation result before continuing.
tar -xzf camera-phase-b-lab.tar.gz
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip check
source /opt/tros/humble/setup.bash
ss -ltn '( sport = :18100 )'
env -u PYTHONPATH RDK_LAB_ROS_PYTHONPATH="${PYTHONPATH:-}" .venv/bin/python prototype/camera_lab/server.py
```

Do not start this command until the target listener check and user approval are complete. On the workstation, first ensure local port 18100 is free, then tunnel privately:

```bash
ssh -N -L 127.0.0.1:18100:127.0.0.1:18100 sunrise@192.168.1.59
```

Open `http://127.0.0.1:18100/`. Start in Synthetic mode if desired; Native Start creates a real image subscription and requires explicit physical subscription approval. Stop the preview, terminate the lab and tunnel that you started, and verify worker cleanup. Preserve the bench directory and report evidence rather than removing unrelated files.

For the separately approved graph inspection, after sourcing the existing target ROS environment, the following queries do not subscribe to image streams:

```bash
ros2 node list
ros2 topic list -t
for topic in /image_left_raw /image_right_raw /image_combine_raw /image_combine_jpeg /image_left_raw/camera_info /image_right_raw/camera_info /image_combine_raw/left/camera_info /image_combine_raw/right/camera_info; do
  printf '\n--- %s ---\n' "$topic"
  ros2 topic info -v "$topic" || true
done
```

The reported endpoint type and offered reliability/durability must be compared against the worker's fixed message type and best-effort depth-one QoS. Record an absent topic as absent; do not create a publisher. Width, encoding and calibration require receiving messages and therefore remain behind the separate physical subscription approval. The lab displays those values once received; compare them with the publisher and inspect staleness and timestamp provenance.
