# Synthetic workstation NV12 resource benchmark

The benchmark uses generated inputs only: NV12, 1088×1280, stride 1088, 2,088,960 bytes, a constant luminance plane for low detail and seeded pseudo-random luminance for high detail, with constant synthetic chroma. No physical camera image or target was accessed. It evaluates the existing grayscale-luminance conversion with its normal validation and 2 MiB IPC cap. Production defaults remain unchanged. Raw per-iteration data and all ten browser/pipeline results are in [CAMERA_NV12_BENCHMARK_RESULTS.json](CAMERA_NV12_BENCHMARK_RESULTS.json).

Each variant runs in a fresh child process, with three warm-ups and 12 measured conversions. CPU is process CPU-time delta; wall is monotonic elapsed conversion time. The reported p95 uses the nearest index to `0.95 × (n − 1)` (the eleventh sorted value for 12 samples); this is illustrative, not a stable tail estimate. Peak RSS is the largest `/proc/<pid>/status` VmRSS sampled every 2 ms, including interpreter and fixture memory; it may miss shorter peaks. The child's `ru_maxrss` is retained in the raw results but may inherit a parent high-water mark and should not be compared as a clean independent peak. Chromium separately decodes one actual generated PNG from memory for each variant; no image file is written.

The independent alternatives are: every other offered frame (a simulated halving of preview frequency, not real-time scheduling), nearest-neighbor halving of luminance dimensions including its resampling cost, and PNG compression levels 1 and 6 instead of the current level 3. Downsampling occurs in the benchmark only and creates a valid bounded NV12 fixture before the unchanged converter. No default, publisher, hardware codec or camera process was changed.

| Detail | Variant | Wall median / p95 ms | CPU median / p95 ms | PNG bytes | Sampled peak RSS KiB |
|---|---|---:|---:|---:|---:|
| Low | Baseline | 1.719 / 1.740 | 1.719 / 1.740 | 8,644 | 17,024 |
| Low | Reduced frequency | 1.745 / 1.977 | 1.744 / 1.972 | 8,644 | 17,068 |
| Low | Half resolution | 2.758 / 2.768 | 2.758 / 2.767 | 3,403 | 17,184 |
| Low | PNG level 1 | 1.717 / 1.956 | 1.717 / 1.955 | 8,082 | 17,084 |
| Low | PNG level 6 | 6.532 / 6.551 | 6.532 / 6.551 | 5,203 | 17,100 |
| High | Baseline | 22.592 / 22.711 | 22.577 / 22.710 | 1,394,408 | 22,516 |
| High | Reduced frequency | 22.508 / 22.749 | 22.508 / 22.735 | 1,394,408 | 22,588 |
| High | Half resolution | 7.420 / 7.711 | 7.420 / 7.709 | 348,973 | 18,696 |
| High | PNG level 1 | 22.649 / 23.052 | 22.645 / 23.046 | 1,394,408 | 22,572 |
| High | PNG level 6 | 23.698 / 23.909 | 23.697 / 23.893 | 1,394,413 | 22,508 |

All ten generated PNGs decoded in local Chromium at their expected dimensions. A separate per-variant synthetic process used the real native supervisor, framed IPC and broker with a deliberately delayed first ACK: two frames were acknowledged in each case, all ten diagnostic messages arrived, and all ten workers were reaped. The broker reported 4 slot replacements in the low-detail cases and 2–4 in high-detail cases. These ACKs were sent by a TestClient, not by Chromium; browser decoding and IPC/ACK were separate tests. They do not establish continuous delivery or real browser network throughput. The reduced-frequency conversion experiment processed 12 of 24 offered synthetic inputs; the IPC stress exercise itself sends its common burst and does not measure a frequency limit. Losses upstream of the broker and actual target DDS costs remain unknown.

High-detail data took roughly 13 times the baseline conversion CPU and produced roughly 161 times the payload of the low-detail fixture. Half resolution reduced high-detail payload and conversion CPU in this sample, but its Python downsampling cost exceeded baseline for low detail. Level 6 used more CPU with no payload benefit for pseudo-random data. A lower rate should reduce total conversion work for a fixed offered rate, but these samples do not measure a running timed service. Do not change defaults on this evidence; use later separately authorized, thermally safe target measurements to establish limits.

Reproduce on the workstation (requires persistent recovered Python, frontend Playwright and Chromium):

```sh
env -u PYTHONPATH -u PYTHONHOME RDK_TEST_BROWSER=${RDK_QA_CHROMIUM} \
  .venv-recovered/bin/python scripts/camera_nv12_benchmark.py > docs/CAMERA_NV12_BENCHMARK_RESULTS.json
```

Application slots and IPC length limits bound some user-space buffering, not process memory. RSS is measured process residency, not a memory limit. A cgroup memory limit bounds its included tasks, not remote browser or all kernel/DDS allocations. `RLIMIT_CPU` limits cumulative CPU time per process, not rate; a cgroup CPU quota constrains rate but was not verified available for the physical laboratory. None of these workstation measurements establish target isolation or safe sustained operation.
