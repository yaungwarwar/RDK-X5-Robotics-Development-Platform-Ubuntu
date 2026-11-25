"""Native worker, framing and subprocess tests using no physical ROS or camera."""

import asyncio
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototype/camera_lab"))
import native_protocol as protocol  # noqa: E402
import native_supervisor as supervisor  # noqa: E402
import native_worker as worker  # noqa: E402
import server as lab  # noqa: E402


def raw(encoding="rgb8", width=2, height=1, step=6, data=b"\x01\x02\x03\x04\x05\x06"):
    return NS(encoding=encoding, width=width, height=height, step=step, data=data)


@pytest.mark.parametrize(
    "encoding,step,data",
    [
        ("rgb8", 6, b"\x01\x02\x03\x04\x05\x06"),
        ("bgr8", 6, b"\x03\x02\x01\x06\x05\x04"),
        ("mono8", 2, b"\x01\x02"),
    ],
)
def test_raw_encodings_generate_valid_png(encoding, step, data):
    image, mime, w, h, original = worker.raw_to_png(raw(encoding, step=step, data=data))
    assert mime == "image/png" and image.startswith(b"\x89PNG\r\n\x1a\n")
    assert (w, h, original) == (2, 1, encoding)
    assert worker.compressed_image(NS(format="png", data=image))[:4] == (image, mime, w, h)


@pytest.mark.parametrize(
    "msg",
    [raw("rgba8"), raw(width=1281), raw(step=5), raw(data=b"bad"), raw(step=5000), raw(height=0)],
)
def test_invalid_raw_rejected(msg):
    with pytest.raises(ValueError):
        worker.raw_to_png(msg)


def test_compressed_jpeg_png_validation():
    jpeg = (ROOT / "tests/fixtures/native_camera_fixture.jpg").read_bytes()
    assert worker.compressed_image(NS(format="jpeg", data=jpeg))[1:4] == ("image/jpeg", 2, 1)
    for fmt, data in [
        ("gif", b"xxx"),
        ("jpeg", b"\xff\xd8bad\xff\xd9"),
        ("png", b"\x89PNG\r\n\x1a\n"),
    ]:
        with pytest.raises(ValueError):
            worker.compressed_image(NS(format=fmt, data=data))
    with pytest.raises(ValueError):
        worker.compressed_image(NS(format="jpeg", data=b"x" * (protocol.MAX_PAYLOAD + 1)))


def test_calibration_reports_actual_values_and_rejects_nan():
    m = NS(
        width=640,
        height=360,
        distortion_model="plumb_bob",
        k=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        d=[0.1, 0.2],
    )
    assert worker.calibration(m)["calibrated"] is True
    m.k[0] = float("nan")
    with pytest.raises(ValueError):
        worker.calibration(m)


def test_ipc_version_bounds_and_partial_reads():
    async def scenario():
        reader = asyncio.StreamReader()
        packet = protocol.pack_record({"type": "frame"}, b"abc")
        reader.feed_data(packet)
        reader.feed_eof()
        h, data = await protocol.read_record(reader)
        assert h["version"] == 1 and data == b"abc"
        for packet in [
            struct.pack("!II", protocol.MAX_HEADER + 1, 0),
            struct.pack("!II", 2, protocol.MAX_PAYLOAD + 1),
            protocol.PREFIX.pack(22, 0) + b'{"version":2,"type":1}',
        ]:
            r = asyncio.StreamReader()
            r.feed_data(packet)
            r.feed_eof()
            with pytest.raises((ValueError, asyncio.IncompleteReadError)):
                await protocol.read_record(r)
        with pytest.raises(ValueError):
            protocol.pack_record({"type": "frame"}, b"x" * (protocol.MAX_PAYLOAD + 1))

    asyncio.run(scenario())


def test_real_subprocess_start_frame_stop_and_exclusion():
    async def scenario():
        slot = lab.LatestFrame()
        s = supervisor.NativeSupervisor(
            [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "frame"]
        )
        await s.start("left", "raw", slot)
        pid = s.process.pid
        with pytest.raises(RuntimeError):
            await s.start("left", "raw", lab.LatestFrame())
        await asyncio.wait_for(slot.event.wait(), 3)
        assert slot.frame[1].startswith(b"\x89PNG") and slot.native_meta["calibration"]
        await s.stop()
        assert s.process is None and not s.reserved
        with pytest.raises(ProcessLookupError):
            __import__("os").kill(pid, 0)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["startup_fail", "hang", "crash"])
def test_startup_deadline_and_crash_cleanup(mode, monkeypatch):
    monkeypatch.setattr(supervisor, "START_TIMEOUT", 0.35)

    async def scenario():
        slot = lab.LatestFrame()
        s = supervisor.NativeSupervisor(
            [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), mode]
        )
        if mode == "crash":
            await s.start("left", "raw", slot)
            await asyncio.wait_for(slot.event.wait(), 3)
            assert slot.fatal and "disconnected" in slot.error
        else:
            with pytest.raises(Exception):
                await s.start("left", "raw", slot)
        await s.stop()
        assert not s.reserved and s.process is None

    asyncio.run(scenario())


def test_topic_allowlist_and_no_ros_import_in_broker():
    assert worker.TOPICS["combined"][0] == "/image_combine_raw"
    assert "rclpy" not in lab.__dict__

    async def scenario():
        s = supervisor.NativeSupervisor()
        with pytest.raises(ValueError):
            await s.start("left", "compressed", lab.LatestFrame())
        assert not s.reserved

    asyncio.run(scenario())


def test_broker_native_ipc_frame_calibration_and_disconnect(monkeypatch):
    from fastapi.testclient import TestClient

    active = supervisor.NativeSupervisor(
        [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "frame"]
    )
    monkeypatch.setattr(lab, "native", active)
    with TestClient(lab.app) as client:
        with client.websocket_connect(
            "/lab/preview/left?source=native", headers={"origin": "http://testserver"}
        ) as ws:
            assert ws.receive_json()["type"] == "status"
            frame = ws.receive_json()
            assert frame["source"] == "native" and frame["mime"] == "image/png"
            assert frame["calibration"]["/image_left_raw/camera_info"]["calibrated"]
            assert ws.receive_bytes().startswith(b"\x89PNG")
            ws.send_text(f"ack:{frame['sequence']}")
        deadline = time.monotonic() + 5
        while active.reserved and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not active.reserved and active.process is None


def test_native_start_failure_does_not_fallback(monkeypatch):
    from fastapi.testclient import TestClient

    failed = supervisor.NativeSupervisor(
        [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "startup_fail"]
    )
    monkeypatch.setattr(lab, "native", failed)
    with TestClient(lab.app) as client:
        with client.websocket_connect(
            "/lab/preview/left?source=native", headers={"origin": "http://testserver"}
        ) as ws:
            error = ws.receive_json()
            assert error["type"] == "error" and "Native worker unavailable" in error["message"]
        assert not failed.reserved and not lab.clients


def test_actual_system_python_worker_with_mocked_ros_interfaces(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "tests/fixtures/fake_ros"))

    async def scenario():
        slot = lab.LatestFrame()
        s = supervisor.NativeSupervisor()
        await s.start("left", "raw", slot)
        try:
            await asyncio.wait_for(slot.event.wait(), 4)
            assert slot.native_meta["encoding"] == "rgb8"
            assert slot.native_meta["calibration"]["/image_left_raw/camera_info"]["calibrated"]
            assert slot.frame[1].startswith(b"\x89PNG")
        finally:
            await s.stop()
        assert s.process is None and not s.reserved

    asyncio.run(scenario())


def test_hung_worker_heartbeat_timeout_and_forced_cleanup(monkeypatch):
    monkeypatch.setattr(supervisor, "RECORD_TIMEOUT", 0.3)
    monkeypatch.setattr(supervisor, "STOP_TIMEOUT", 0.2)

    async def scenario():
        slot = lab.LatestFrame()
        s = supervisor.NativeSupervisor(
            [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "stubborn"]
        )
        await s.start("left", "raw", slot)
        pid = s.process.pid
        await asyncio.wait_for(slot.event.wait(), 2)
        assert slot.fatal and "disconnected" in slot.error
        await s.stop()
        assert not s.reserved
        with pytest.raises(ProcessLookupError):
            __import__("os").kill(pid, 0)

    asyncio.run(scenario())


def test_disconnect_during_startup_cleans_up_worker(monkeypatch):
    from fastapi.testclient import TestClient

    active = supervisor.NativeSupervisor(
        [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "hang"]
    )
    monkeypatch.setattr(lab, "native", active)
    with TestClient(lab.app) as client:
        with client.websocket_connect(
            "/lab/preview/left?source=native", headers={"origin": "http://testserver"}
        ):
            time.sleep(0.1)
        deadline = time.monotonic() + 5
        while active.reserved and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not active.reserved and active.process is None
