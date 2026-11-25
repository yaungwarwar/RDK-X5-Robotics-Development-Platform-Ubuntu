"""Synthetic benchmark IPC producer; no ROS imports or camera access."""

import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts"))
sys.path.insert(0, str(root / "prototype/camera_lab"))
from camera_nv12_benchmark import convert, fixture  # noqa: E402
from native_protocol import pack_record  # noqa: E402

variant, detail = sys.argv[1:3]
message = fixture(detail)
output = sys.stdout.buffer
output.write(pack_record({"type": "ready", "view": "left", "topic": "/synthetic"}))
output.flush()
output.write(pack_record({"type": "error", "message": "synthetic diagnostic"}))
output.flush()
for sequence in range(1, 9):
    frame, mime, width, height, encoding = convert(message, variant)
    output.write(
        pack_record(
            {
                "type": "frame",
                "view": "left",
                "sequence": sequence,
                "mime": mime,
                "width": width,
                "height": height,
                "encoding": encoding,
            },
            frame,
        )
    )
    output.flush()
    time.sleep(0.04)
time.sleep(30)
