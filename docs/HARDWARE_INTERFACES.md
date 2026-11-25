# Hardware interfaces — 0.1.1

Read-only hardware adapters; unavailable, denied, malformed or implausible measurements stay null with provenance and reasons. The board observations below were provided by the user after physical 0.1.0 deployment. New 0.1.1 dynamic behavior is locally mocked until target acceptance.

| Measurement | Interface | Units / policy |
|---|---|---|
| CPU temperature | Thermal zone discovered by type `thermal-cpu` | Millidegrees / 1000 → °C; existing working reader preserved |
| DDR temperature | Thermal zone type `thermal-ddr` | Millidegrees / 1000 → °C; preserved |
| BPU utilization | `/sys/devices/platform/soc/3a000000.bpu/ratio` | Integer percentage 0–100, real zero retained |
| Dedicated BPU temperature | Discover `/sys/class/hwmon/hwmon*/name` = `pvt`, read `temp2_input` | Millidegrees / 1000 → °C; isolated subprocess, never CPU substitution |
| Optional CPU-temperature proxy | Existing `thermal-cpu` observation | Explicit CPU proxy, with actual thermal-zone source; not an independent BPU sensor |
| BPU / GPU / DDR frequencies | `/sys/class/devfreq/3a000000.bpu/`, `3c000000.gc8000/`, `soc:ddrc-freq/` | Hz / 1,000,000 → MHz, six decimals; no upward 100 MHz rounding |
| Per-core CPU frequency | `cpuN/cpufreq/scaling_cur_freq` under `/sys/devices/system/cpu/` | kHz / 1000 → MHz; procfs core identities |
| Cooling states | `/sys/class/thermal/cooling_device*/{type,cur_state,max_state}` | Nonnegative state, zero is valid |
| BPU devices | `/dev/bpu`, `/dev/bpu_core0` | Character-node metadata/access check; no opening/chmod |
| CPU/RAM/network/uptime | procfs / psutil / uname / os-release | Actual time deltas, bytes, B/s, seconds |
| Storage | statvfs through psutil | Bytes and filesystem percentage |
| Runtime services | Fixed `systemctl show` for Docker/containerd | Read-only status, one-second per-query deadline |

## BPU percentage semantics

The user verified readable mode `-r--r--r--` and idle text `0` at the X5 platform-device ratio path. Vendor documentation identifies ratio as BPU/core utilization; D-Robotics' hardware notes explicitly describe the corresponding BPU ratio interface as 0–100 utilization. This supports interpreting the supplied X5 ratio as an integer percentage, not a fraction or a frequency-derived estimate. The platform path itself is the user's verified X5 interface; other-board documentation is not used to guess alternative paths.

Sources inspected:

- [D-Robotics BPU sysfs documentation](https://d-robotics.github.io/rdk_doc/en/Advanced_development/linux_development/driver_development/driver_bpu_sysfs_dev/): ratio is read-only BPU/core utilization.
- [D-Robotics hardware interface notes](https://github.com/D-Robotics/device-knowledge/blob/main/skills/rdk-hardware/references/hardware-notes.md): BPU ratio range 0–100.
- [D-Robotics BPU monitoring examples](https://d-robotics.github.io/rdk_s_doc/en/Advanced_development/linux_development/hardware_unit_test/bpu_cpu_ddr_stress/): corroborating percentage semantics on the S family, not proof of X5 dynamic accuracy.

The parser accepts only one to three ASCII decimal digits after surrounding whitespace is stripped, with value 0–100. Signed values, decimals, percentages with `%`, NaN, multiple values and out-of-range values are rejected. Missing/denied/error cases never become zero. The actual driver accounting interval and behavior under a real X5 inference workload remain **pending validation**. No dynamic load test is claimed.

## Accurate temperature attribution and isolation

User-verified `pvt` mapping: `temp1_input` DDR, `temp2_input` dedicated BPU, `temp3_input` CPU. Observed values were 59705, a `Connection timed out` error, and 58728 respectively. The application finds the hwmon number through `name`; it never assumes hwmon0.

The application reads only dedicated `temp2_input` in a fixed helper. CPU and DDR retain their working typed thermal-zone readers. If dedicated temperature is missing/fails/times out and `bpu_cpu_proxy_enabled` is true, the application exposes the already sampled **CPU thermal-zone temperature** under `cpu_temperature_proxy`. It does not perform an additional temp3 read. The value has the actual CPU source and a reason explicitly saying it is not an independently measured BPU temperature.

`bpu.temperature` always means the dedicated sensor, including null when it fails. `bpu.cpu_temperature_proxy` is separate. `bpu.temperature_fallback` is `cpu_proxy`, `none`, or `unavailable`; this policy never replaces the dedicated value. Proxy can be disabled without changing vendor configuration.

The helper is one process slot, polled nonblockingly by the sampler. The default deadline is one second (checked on telemetry ticks), successful refresh interval 30 seconds. Failure retry delays are 30, 60, 120, 240, then 300 seconds maximum. Bounds: timeout 0.1–3 seconds, interval 10–300 seconds, maximum backoff 30–1800 seconds and no smaller than the interval. The bounded child output is parsed only after exit.

On timeout the helper is killed and dedicated temperature becomes null. If the kernel leaves the read in an uninterruptible state, the slot stays occupied and **no new helper is spawned until it exits**, even after retry deadlines. No worker threads are abandoned. Shutdown never waits indefinitely on this sensor. An uninterruptible kernel read cannot be forcibly fixed in Python; do not repeatedly restart the service to bypass quarantine. Inspect the unit's remaining child state and wait for kernel recovery under normal board maintenance.

Dedicated sensor measurements use a freshness threshold of 2.5 × their normal refresh interval (75 seconds default), while the CPU proxy retains the CPU observation's acquisition timestamp and five-second freshness. Fast CPU/DDR thermal-zone collection remains unchanged. Missing/error dedicated observations can themselves age stale during a long backoff.

## Vendor utility safety and frequencies

**Do not execute hrut_somstatus from the application or as a diagnostic polling loop.** The user's script inspection found conditional writes to `profiler_frequency` and `profiler_enable`. The application directly reads known sysfs attributes and never enables a profiler, invokes sudo, writes governors/trip points/PWM or changes permissions.

Vendor upward rounding of BPU/GPU frequencies is not reproduced. Native devfreq values are normalized to MHz to one-Hz resolution without inferring utilization. See [X5 frequency interfaces](https://developer.d-robotics.cc/rdk_x_doc/en/Advanced_development/linux_development/driver_development_x5/driver_lowpower), [CPU kHz documentation](https://developer.d-robotics.cc/rdk_x_doc/en/System_configuration/frequency_management) and [Linux devfreq ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-class-devfreq). Ranges reject non-finite/nonpositive frequencies or values above 100,000 MHz; temperatures outside -50–200 °C are invalid data, not thermal control thresholds.

## ROS2 and camera observations

The fixed `/usr/bin/python3` probe is retained; no raw-image subscriptions, parameter changes, camera startup, DDS configuration or environment rewriting. User-observed standalone times were 3.109 seconds without capture and 3.394 seconds with capture; four seconds left little startup margin but is not a proven explanation for the service failure.

The successful user graph had `/mipi_cam`, raw image topics `/image_left_raw`, `/image_right_raw`, `/image_combine_raw`, four calibration topics under left/right raw and combined left/right, plus `/parameter_events` and `/rosout`. Image/calibration topics each had one publisher. `/image_combine_jpeg` was absent. Known camera topics are checked individually; an absent JPEG encoder yields a valid zero publisher count in a successful graph, never global unavailability.

The native adapter now reports specific failures, bounded stderr, actual duration, last successful graph time and consecutive failures. A successful empty graph is explicitly `success_empty` with empty lists and zero known publishers. Failures retain the last successful graph with original timestamps and stale flags; no prior success means null data. See [ROS2_DIAGNOSTICS.md](ROS2_DIAGNOSTICS.md).

## Cgroup evidence

The user reports kernel CFS/RT group scheduling compilation enabled, but root subtree control and system.slice lack effective CPU delegation and system.slice has no cpu.max. Removing only Compose `cpus: 0.50` allowed the frontend to start. A real-time watchdog outside root is **consistent with**, but does not conclusively prove, the documented RT-controller restriction.

[Linux cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) describes controller propagation and RT restrictions. [Docker runtime metrics/cgroup documentation](https://docs.docker.com/engine/containers/runmetrics/) identifies drivers and container hierarchy paths. The generator reads actual controllers, subtree delegation and interfaces along the Docker parent hierarchy and, where available, the running dashboard's leaf. Compilation flags alone never authorize a quota. No subtree, watchdog, kernel or global Docker modification is made.
