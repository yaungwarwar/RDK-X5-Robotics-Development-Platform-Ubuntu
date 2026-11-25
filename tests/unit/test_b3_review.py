"""Regression fixtures for independent review findings; no hardware access."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.mock import MockHardware
from app.config.settings import Settings
from app.main import create_app


class FailedRos:
    def collect(self):
        raise RuntimeError("synthetic initial ROS failure")


def test_initial_auxiliary_failure_has_unavailable_sections():
    class HardwareWithoutServices(MockHardware):
        def collect(self):
            data = super().collect()
            del data["services"]
            return data

    app = create_app(
        Settings(mode="mock", allowed_hosts=["testserver"]), HardwareWithoutServices(), FailedRos()
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for name in ("ros2", "cameras", "services"):
            response = client.get("/api/v1/" + name)
            assert response.status_code == 200
            assert response.json()["data"] is not None
        assert client.get("/api/v1/ros2").json()["data"]["available"]["value"] is None
        assert client.get("/api/v1/services").json()["data"]["docker"]["value"] is None


def test_production_default_excludes_test_host():
    assert "testserver" not in Settings().allowed_hosts


def test_laboratory_rejects_test_only_websocket_host():
    import sys
    from pathlib import Path
    from starlette.websockets import WebSocketDisconnect

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototype/camera_lab"))
    import server

    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://testserver/lab/preview/left", headers={"origin": "http://testserver"}
            ):
                pass


def test_async_stop_does_not_block_event_loop_while_thread_finishes():
    from app.collectors.monitor import Monitor

    async def scenario():
        monitor = Monitor(MockHardware(), FailedRos(), Settings(mode="mock"))
        started = threading.Event()
        release = threading.Event()
        monitor.executor.submit(lambda: (started.set(), release.wait(2)))
        assert started.wait(1)
        stop = asyncio.create_task(monitor.stop())
        await asyncio.sleep(0.05)
        assert not stop.done()
        release.set()
        await asyncio.wait_for(stop, 1)

    asyncio.run(scenario())


def test_intrinsics_do_not_claim_validated_calibration():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototype/camera_lab"))
    from native_worker import calibration

    data = calibration(SimpleNamespace(width=1, height=1, distortion_model="x", k=[1] * 9, d=[]))
    assert data["intrinsics_present"] is True
    assert "calibrated" not in data


@pytest.mark.parametrize("count", [0, 1])
def test_worker_publisher_heartbeat_is_observable(count):
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "prototype/camera_lab"))
    from native_supervisor import NativeSupervisor
    from server import LatestFrame

    async def scenario():
        slot = LatestFrame()
        supervisor = NativeSupervisor(
            [
                sys.executable,
                str(root / "tests/fixtures/native_camera_fake.py"),
                f"publisher{count}",
            ]
        )
        try:
            await supervisor.start("left", "raw", slot)
            await asyncio.wait_for(slot.event.wait(), 1)
            assert slot.publishers == count
        finally:
            await supervisor.stop()

    asyncio.run(scenario())
