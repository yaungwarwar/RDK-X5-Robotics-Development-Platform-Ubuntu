"""Synthetic laboratory tests; no ROS packages or physical camera required."""

import asyncio
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototype" / "camera_lab"))
import server as lab  # noqa: E402


def test_frame_validation_and_single_latest_slot():
    slot = lab.LatestFrame()
    frame, w, h = lab.synthetic_frame("left", 1)
    slot.publish(frame, "image/svg+xml", w, h)
    slot.publish(frame, "image/svg+xml", w, h)
    assert slot.sequence == 2 and slot.produced == 2 and slot.frame[0] == 2
    with pytest.raises(ValueError, match="unsupported"):
        lab.validate_frame(frame, "rgb8", w, h)
    with pytest.raises(ValueError, match="invalid"):
        lab.validate_frame(b"bad", "image/svg+xml", w, h)
    with pytest.raises(ValueError, match="bounds"):
        lab.validate_frame(b"<svg " + b"x" * lab.MAX_FRAME + b"</svg>", "image/svg+xml", w, h)
    with pytest.raises(ValueError):
        lab.synthetic_frame("unexpected", 1)


@pytest.mark.parametrize("view", ["left", "right", "combined"])
def test_start_stop_and_switch(view):
    with TestClient(lab.app) as c:
        with c.websocket_connect(
            "/lab/preview/" + view, headers={"origin": "http://testserver"}
        ) as ws:
            m = ws.receive_json()
            assert m["source"] == "synthetic" and m["view"] == view
            assert m["lab_peak_rss_kib"] > 0
            assert b"MOCK DATA" in ws.receive_bytes()
            ws.send_text(f"ack:{m['sequence']}")
        assert not lab.clients


def test_bad_origin_and_client_limit():
    with TestClient(lab.app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/lab/preview/left", headers={"origin": "http://evil.test"}):
                pass
        with c.websocket_connect("/lab/preview/left", headers={"origin": "http://testserver"}):
            with c.websocket_connect("/lab/preview/right", headers={"origin": "http://testserver"}):
                with pytest.raises(WebSocketDisconnect):
                    with c.websocket_connect(
                        "/lab/preview/combined", headers={"origin": "http://testserver"}
                    ):
                        pass
    assert not lab.clients


def test_slow_client_drops_old_frames_and_disconnect_reconnect():
    with TestClient(lab.app) as c:
        with c.websocket_connect(
            "/lab/preview/left", headers={"origin": "http://testserver"}
        ) as ws:
            first = ws.receive_json()
            ws.receive_bytes()
            time.sleep(0.65)
            ws.send_text(f"ack:{first['sequence']}")
            second = ws.receive_json()
            ws.receive_bytes()
            assert second["sequence"] > first["sequence"] + 1
            assert second["dropped"] >= 2
        assert not lab.clients
        with c.websocket_connect(
            "/lab/preview/right", headers={"origin": "http://testserver"}
        ) as ws:
            assert ws.receive_json()["view"] == "right"
            ws.receive_bytes()
    assert not lab.clients


def test_publisher_disappearance_and_cancel_cleanup():
    async def scenario():
        slot = lab.LatestFrame()
        task = asyncio.create_task(lab.produce(slot, "left"))
        await asyncio.wait_for(slot.event.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        before = slot.sequence
        await asyncio.sleep(0.25)
        assert slot.sequence == before

    asyncio.run(scenario())


def test_existing_mock_telemetry_continues_while_preview_is_active():
    from app.config.settings import Settings
    from app.main import create_app

    telemetry = create_app(Settings(mode="mock", interval_seconds=0.2))
    with TestClient(telemetry) as existing, TestClient(lab.app) as camera:
        first = existing.get("/api/v1/snapshot").json()["sequence"]
        with camera.websocket_connect(
            "/lab/preview/left", headers={"origin": "http://testserver"}
        ) as ws:
            m = ws.receive_json()
            ws.receive_bytes()
            time.sleep(0.5)
            ws.send_text(f"ack:{m['sequence']}")
            assert existing.get("/api/v1/snapshot").json()["sequence"] > first
            assert existing.get("/api/v1/health").json()["status"] == "ok"


def test_unresponsive_client_is_closed_and_releases_source():
    with TestClient(lab.app) as client:
        with client.websocket_connect(
            "/lab/preview/left", headers={"origin": "http://testserver"}
        ) as ws:
            ws.receive_json()
            ws.receive_bytes()
            time.sleep(lab.ACK_TIMEOUT + 0.2)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        assert not lab.clients


def test_failed_handshake_releases_client_slot():
    class BrokenSocket:
        headers = {"origin": "http://testserver", "host": "testserver"}

        async def accept(self):
            raise RuntimeError("handshake failed")

    socket = BrokenSocket()
    with pytest.raises(RuntimeError, match="handshake failed"):
        asyncio.run(lab.preview(socket, "left"))
    assert not lab.clients


def test_publisher_failure_disconnects_and_cleans_up(monkeypatch):
    async def failed_producer(slot, view):
        raise RuntimeError("synthetic publisher disappeared")

    monkeypatch.setattr(lab, "produce", failed_producer)
    with TestClient(lab.app) as client:
        with client.websocket_connect(
            "/lab/preview/left", headers={"origin": "http://testserver"}
        ) as ws:
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        assert not lab.clients
