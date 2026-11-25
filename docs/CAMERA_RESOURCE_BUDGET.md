# Camera laboratory bounds and measurement plan

These are conservative **Phase A synthetic laboratory limits**, not RDK X5 performance claims. The separate process binds 127.0.0.1:18100; the existing service does not import or start it. No physical device is accessed or recording enabled.

| Item | Phase A bound / behavior |
|---|---|
| Active clients | Maximum 2; additional connections are rejected before acceptance |
| Source lifetime | Per accepted client only; canceled and removed on disconnect, stop, switch or timeout |
| Synthetic source | 640 × 360 generated SVG, target 5 frames/s per active viewer |
| Image slot | One latest frame per client; new frames replace old |
| Binary payload | Maximum 256 KiB, dimensions at most 1920 × 1080; only the synthetic SVG encoding is accepted |
| In-flight delivery | One metadata message and one binary image, then an ACK after browser image decode; 2-second ACK and send deadlines |
| Receive frame | Uvicorn WebSocket input limit 1024 bytes; only the expected ACK is acted on |
| Frame stale | Browser marks frame stale after 2 seconds without a new frame; no stale image is relabeled as fresh |
| Storage | No automatic image recording; screenshots are explicit test artifacts |
| Metrics | Synthetic delivered FPS, sent payload bytes/time and skipped sequence count; lab process peak RSS and CPU are measured; actual camera/calibration data are unavailable |

The browser serializes view switching and waits for prior close with a short grace; the server enforces the limit independently. A slow/non-acknowledging browser has its connection closed. Protocol and socket libraries may have their own bounded buffers; process total memory is not established by the image-slot limit. Image age combines server residence time and browser time since receipt; it does not include precise transport time or camera acquisition timestamp. Browser object URLs are revoked on replacement and cleanup. Calibration metadata is intentionally unavailable in this phase. The displayed lab peak RSS comes from `getrusage` for the whole laboratory process and lab CPU is process CPU-time delta over session elapsed time, expressed as percentage of one core. These include any concurrent laboratory clients and are not camera or target measurements.

For Phase B, first measure actual ROS encoding, uncompressed dimensions/stride and frequency, compressed size distribution, end-to-end latency, acquisition clock provenance, publisher QoS, CPU/RSS of all worker/broker/ROS children, memory peaks, dropped frames, network bytes and temperatures. Test the accepted baseline collector and proxy under zero, one, maximum and slow/disconnecting clients. Define quantitative ARM64 acceptance thresholds from those measurements and user-approved operating conditions. Bound raw input and conversion allocations separately; 256 KiB is not a raw-image budget. Account for JPEG encoder CPU, middleware queues, WebSocket/socket buffers, clients and browser memory. No resource isolation guarantees for a real worker are claimed until independently tested.

## Phase B native laboratory bounds

One native worker globally; no more than two total laboratory clients. The chosen image topic plus at most two calibration topics are the only subscriptions. Raw dimensions are capped at 1280×720 and raw size at 2,764,800 bytes; output is at most 2 MiB. ROS QoS is KEEP_LAST depth 1, image callbacks are rate-limited to 5 Hz, the worker writer holds one latest packet, and the broker holds one latest frame. IPC headers are at most 4096 bytes and stderr tail at most 2048 bytes. The worker emits a heartbeat every 5 seconds, startup is bounded at 12 seconds, and missing records are fatal at 15 seconds. Shutdown uses a 3-second TERM deadline followed by a 3-second KILL/reap deadline; an unreaped child prevents replacement. Native image decode is browser-side and ACK-gated. `worker_rss_kib` and `worker_cpu_pct` are measured from `/proc` when accessible; CPU is elapsed CPU-time delta as a percentage of one core. These are monitoring figures, not an enforced OS memory/CPU cap.

These bounds do not cover all ROS/DDS, browser, kernel and compression allocations. No target hardware capacity or resource ceiling has been established. Physical subscriptions, load measurements and any future cgroup/process-limit policy require separately authorized bench acceptance.

## B.1 local NV12 adjustment

A metadata-only physical sample measured 1088×1280 NV12, stride 1088 and 2,088,960 bytes. The user approved local work: NV12 height may now be up to 1280, while width remains 1280, raw input remains capped at 2,764,800 bytes, and output/IPC remains capped at 2 MiB. The worker generates grayscale PNG from Y only; original chroma is not displayed. Other image format height limits remain 720. Calibration may report up to 1280×1280. These are validation limits, not OS-enforced memory isolation or measured target throughput. CPU-rate cgroup enforcement was unavailable on the target; see [isolation review](CAMERA_RESOURCE_ISOLATION.md).
