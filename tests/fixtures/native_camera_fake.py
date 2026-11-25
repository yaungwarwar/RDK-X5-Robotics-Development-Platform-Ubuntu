"""Test-only IPC child; never uses ROS or hardware."""

import argparse
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototype/camera_lab"))
from native_protocol import pack_record  # noqa: E402
from native_worker import raw_to_png  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("mode")
args = p.parse_args()
if args.mode == "startup_fail":
    sys.exit(7)
if args.mode == "hang":
    time.sleep(30)
    sys.exit(0)
if args.mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

sys.stdout.buffer.write(pack_record({"type": "ready", "view": "left", "topic": "/image_left_raw"}))
sys.stdout.buffer.flush()
if args.mode == "stubborn":
    time.sleep(30)
    sys.exit(0)
if args.mode == "crash":
    time.sleep(0.1)
    sys.exit(3)
if args.mode in ("publisher0", "publisher1"):
    sys.stdout.buffer.write(pack_record({"type": "status", "publishers": int(args.mode[-1])}))
    sys.stdout.buffer.flush()
    time.sleep(30)
if args.mode == "frame":
    frame, mime, w, h, encoding = raw_to_png(
        SimpleNamespace(
            width=2, height=1, step=6, encoding="rgb8", data=b"\xff\x00\x00\x00\xff\x00"
        )
    )
    meta = {
        "type": "frame",
        "view": "left",
        "mime": mime,
        "width": w,
        "height": h,
        "encoding": encoding,
        "sequence": 1,
        "calibration": {
            "/image_left_raw/camera_info": {
                "width": 2,
                "height": 1,
                "model": "plumb_bob",
                "k": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "d": [],
                "intrinsics_present": True,
            }
        },
    }
    sys.stdout.buffer.write(pack_record(meta, frame))
    sys.stdout.buffer.flush()
    time.sleep(30)
