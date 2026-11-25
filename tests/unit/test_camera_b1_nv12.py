"""Synthetic NV12 fixtures matching measured metadata; no physical images retained."""

import asyncio
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototype/camera_lab"))
import native_worker as worker  # noqa: E402
import native_supervisor as supervisor  # noqa: E402
import server as lab  # noqa: E402


def nv12(width, height, step, payload):
    return SimpleNamespace(width=width, height=height, step=step, encoding="nv12", data=payload)


def png_scanlines(png):
    position = 8
    chunks = []
    while position < len(png):
        length = struct.unpack("!I", png[position : position + 4])[0]
        tag = png[position + 4 : position + 8]
        if tag == b"IDAT":
            chunks.append(png[position + 8 : position + 8 + length])
        position += length + 12
    return zlib.decompress(b"".join(chunks))


def test_nv12_uses_luminance_plane_with_padded_stride():
    msg = nv12(
        4, 2, 6, bytes([10, 20, 30, 40, 99, 99, 50, 60, 70, 80, 99, 99, 128, 128, 128, 128, 99, 99])
    )
    png, mime, width, height, source = worker.raw_to_png(msg)
    assert (mime, width, height, source) == ("image/png", 4, 2, "nv12")
    assert png[25] == 0  # PNG grayscale, not a claim to reproduce chroma.
    assert png_scanlines(png) == b"\x00\x0a\x14\x1e\x28\x00\x32\x3c\x46\x50"


def test_observed_camera_dimensions_and_bytes_fit_without_raising_raw_cap():
    assert worker.MAX_RAW == 1280 * 720 * 3
    width, height, stride = 1088, 1280, 1088
    payload = bytes([128]) * (stride * height * 3 // 2)
    assert len(payload) == 2_088_960
    png, _, w, h, encoding = worker.raw_to_png(nv12(width, height, stride, payload))
    assert (w, h, encoding) == (1088, 1280, "nv12")
    assert len(png) <= 2 * 1024 * 1024


@pytest.mark.parametrize(
    "width,height,stride,payload",
    [
        (3, 2, 4, bytes(12)),
        (4, 3, 4, bytes(18)),
        (4, 2, 3, bytes(9)),
        (4, 2, 4, bytes(11)),
        (1280, 1280, 2048, bytes()),
        (1280, 1282, 1280, bytes()),
    ],
)
def test_nv12_rejects_invalid_layouts(width, height, stride, payload):
    with pytest.raises(ValueError):
        worker.raw_to_png(nv12(width, height, stride, payload))


def test_existing_rgb_height_limit_remains_unchanged():
    msg = SimpleNamespace(width=2, height=722, step=6, encoding="rgb8", data=bytes(4332))
    with pytest.raises(ValueError, match="dimensions"):
        worker.raw_to_png(msg)


def test_system_python_worker_nv12_fixture_through_real_ipc(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("PYTHONPATH", str(root / "tests/fixtures/fake_ros"))
    monkeypatch.setenv("FAKE_ROS_NV12", "1")

    async def scenario():
        slot = lab.LatestFrame()
        process = supervisor.NativeSupervisor()
        await process.start("left", "raw", slot)
        try:
            await asyncio.wait_for(slot.event.wait(), 5)
            assert (slot.native_meta["width"], slot.native_meta["height"]) == (1088, 1280)
            assert slot.native_meta["encoding"] == "nv12"
            assert slot.native_meta["display_mode"] == "grayscale luminance (NV12)"
            assert slot.frame[1].startswith(b"\x89PNG")
        finally:
            await process.stop()
        assert process.process is None

    asyncio.run(scenario())


def test_native_reconnect_waits_for_old_worker_reap(monkeypatch):
    monkeypatch.setattr(supervisor, "STOP_TIMEOUT", 0.2)
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(root / "tests/fixtures/native_camera_fake.py"), "stubborn"]

    async def scenario():
        process = supervisor.NativeSupervisor(command)
        await process.start("left", "raw", lab.LatestFrame())
        old_pid = process.process.pid
        stopping = asyncio.create_task(process.stop())
        await asyncio.sleep(0.05)
        assert process.stopping
        await process.start("left", "raw", lab.LatestFrame())
        await stopping
        assert process.process.pid != old_pid
        with pytest.raises(ProcessLookupError):
            __import__("os").kill(old_pid, 0)
        await process.stop()

    asyncio.run(scenario())
