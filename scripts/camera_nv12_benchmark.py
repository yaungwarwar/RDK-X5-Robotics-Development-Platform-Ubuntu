"""Workstation-only synthetic NV12 conversion benchmark; no ROS or hardware access."""

import argparse
import base64
import json
import random
import resource
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype/camera_lab"))
import native_worker as worker  # noqa: E402

W, H = 1088, 1280
VARIANTS = ("baseline", "reduced_rate", "half_resolution", "png_level_1", "png_level_6")


def fixture(detail):
    rng = random.Random(20261125)
    y = bytes([96]) * (W * H) if detail == "low" else rng.randbytes(W * H)
    return SimpleNamespace(
        width=W, height=H, step=W, encoding="nv12", data=y + bytes([128]) * (W * H // 2)
    )


def convert(msg, variant):
    if variant == "half_resolution":
        if len(msg.data) != W * H * 3 // 2:
            raise ValueError("Invalid original synthetic NV12 fixture")
        y = memoryview(msg.data)
        pixels = b"".join(bytes(y[row * W : row * W + W : 2]) for row in range(0, H, 2))
        msg = SimpleNamespace(
            width=W // 2,
            height=H // 2,
            step=W // 2,
            encoding="nv12",
            data=pixels + bytes([128]) * (W * H // 8),
        )
    if variant in ("png_level_1", "png_level_6"):
        original = worker.zlib.compress
        level = int(variant[-1])
        try:
            worker.zlib.compress = lambda data, _: original(data, level)
            return worker.raw_to_png(msg)
        finally:
            worker.zlib.compress = original
    return worker.raw_to_png(msg)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.5))]


def child(variant, detail, iterations, warmup):
    msg = fixture(detail)
    assert len(msg.data) == 2088960
    for _ in range(warmup):
        convert(msg, variant)
    samples = []
    output = b""
    offered = iterations * (2 if variant == "reduced_rate" else 1)
    for offered_index in range(offered):
        if variant == "reduced_rate" and offered_index % 2:
            continue
        start_cpu, start_wall = time.process_time(), time.perf_counter()
        output, _, width, height, _ = convert(msg, variant)
        samples.append(
            {
                "cpu_ms": (time.process_time() - start_cpu) * 1000,
                "wall_ms": (time.perf_counter() - start_wall) * 1000,
                "bytes": len(output),
            }
        )
    return {
        "variant": variant,
        "detail": detail,
        "offered": offered,
        "processed": len(samples),
        "intentionally_throttled": offered - len(samples),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "width": width,
        "height": height,
        "samples": samples,
        "browser_fixture_base64": base64.b64encode(output).decode(),
    }


def pipeline(variant, detail):
    from fastapi.testclient import TestClient
    import server
    from native_supervisor import NativeSupervisor

    previous = server.native
    supervisor = NativeSupervisor(
        [sys.executable, str(ROOT / "tests/fixtures/camera_benchmark_worker.py"), variant, detail]
    )
    server.native = supervisor
    result = {"diagnostic_received": False, "frames_acknowledged": 0, "broker_dropped": 0}
    try:
        with TestClient(server.app, base_url="http://localhost:18100") as client:
            with client.websocket_connect(
                "ws://localhost:18100/lab/preview/left?source=native",
                headers={"origin": "http://localhost:18100"},
            ) as ws:
                assert ws.receive_json()["type"] == "status"
                while result["frames_acknowledged"] < 2:
                    meta = ws.receive_json()
                    if meta["type"] == "error":
                        result["diagnostic_received"] |= meta["message"] == "synthetic diagnostic"
                    elif meta["type"] == "frame":
                        data = ws.receive_bytes()
                        assert data.startswith(b"\x89PNG")
                        result["broker_dropped"] = meta["dropped"]
                        if not result["frames_acknowledged"]:
                            time.sleep(
                                0.25
                            )  # Deliberately slow ACK exercises latest-frame replacement.
                        ws.send_text(f"ack:{meta['sequence']}")
                        result["frames_acknowledged"] += 1
                ws.close()
                deadline = time.monotonic() + 8
                while supervisor.reserved and time.monotonic() < deadline:
                    time.sleep(0.01)
        result["worker_cleaned"] = supervisor.process is None and not supervisor.reserved
        return result
    finally:
        server.native = previous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--child", choices=VARIANTS)
    parser.add_argument("--detail", choices=("low", "high"))
    args = parser.parse_args()
    if args.iterations < 3 or args.warmup < 1:
        parser.error("at least 3 iterations and 1 warmup required")
    if args.child:
        print(json.dumps(child(args.child, args.detail, args.iterations, args.warmup)))
        return
    results = []
    for detail in ("low", "high"):
        for variant in VARIANTS:
            process = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--child",
                    variant,
                    "--detail",
                    detail,
                    "--iterations",
                    str(args.iterations),
                    "--warmup",
                    str(args.warmup),
                ],
                stdout=subprocess.PIPE,
            )
            observed_rss = [0]

            def sample_rss():
                status = Path(f"/proc/{process.pid}/status")
                while process.poll() is None:
                    try:
                        for line in status.read_text().splitlines():
                            if line.startswith("VmRSS:"):
                                observed_rss[0] = max(observed_rss[0], int(line.split()[1]))
                                break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.002)

            sampler = threading.Thread(target=sample_rss)
            sampler.start()
            raw, _ = process.communicate()
            sampler.join()
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, process.args)
            item = json.loads(raw)
            item["child_reported_ru_maxrss_kib"] = item.pop("peak_rss_kib")
            item["sampled_peak_rss_kib"] = observed_rss[0]
            image = item.pop("browser_fixture_base64")
            decoded = subprocess.run(
                [
                    shutil.which("node") or "/usr/bin/node",
                    str(ROOT / "scripts/camera_nv12_decode.mjs"),
                ],
                input=image,
                text=True,
                capture_output=True,
                check=True,
            )
            item["browser_decode"] = json.loads(decoded.stdout)
            item["ipc_broker_exercise"] = pipeline(variant, detail)
            for field in ("cpu_ms", "wall_ms", "bytes"):
                values = [sample[field] for sample in item["samples"]]
                item[field + "_median"] = round(statistics.median(values), 3)
                item[field + "_p95"] = round(percentile(values, 0.95), 3)
            results.append(item)
    print(
        json.dumps(
            {
                "fixture": "synthetic NV12 1088x1280 stride 1088, deterministic seed 20261125",
                "warmup": args.warmup,
                "iterations": args.iterations,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
