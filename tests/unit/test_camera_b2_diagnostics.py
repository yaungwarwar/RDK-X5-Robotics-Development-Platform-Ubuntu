"""Local-only diagnostic and ordering regressions using synthetic fixtures."""

import asyncio
import io
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototype/camera_lab"))
import native_protocol as protocol  # noqa: E402
import native_worker as worker  # noqa: E402
import server as lab  # noqa: E402


class FakeNative:
    owner = None

    async def start(self, view, image_format, slot, owner=None):
        self.owner = owner
        slot.report_error("synthetic invalid message")
        slot.publish_native(b"\x89PNG\r\n\x1a\nexample", {"width": 1, "height": 1})

    async def stop(self):
        self.owner = None

    def metrics(self):
        return {}


def test_pending_error_and_frame_are_both_delivered_without_new_event(monkeypatch):
    monkeypatch.setattr(lab, "native", FakeNative())
    with TestClient(lab.app, base_url="http://localhost:18100") as client:
        assert client.get("/lab/status").json()["source"] == "inactive"
        with client.websocket_connect(
            "ws://localhost:18100/lab/preview/left?source=native",
            headers={"origin": "http://localhost:18100"},
        ) as ws:
            assert ws.receive_json()["type"] == "status"
            assert client.get("/lab/status").json()["source"] == "native"
            assert ws.receive_json()["message"] == "synthetic invalid message"
            frame = ws.receive_json()
            assert frame["type"] == "frame" and ws.receive_bytes().startswith(b"\x89PNG")
            with client.websocket_connect(
                "ws://localhost:18100/lab/preview/right",
                headers={"origin": "http://localhost:18100"},
            ) as synthetic:
                synthetic.receive_json()
                synthetic.receive_bytes()
                assert client.get("/lab/status").json()["source"] == "mixed"
            ws.send_text(f"ack:{frame['sequence']}")
        assert client.get("/lab/status").json()["source"] == "inactive"


def test_synthetic_status_and_acknowledgement_counters():
    with TestClient(lab.app, base_url="http://localhost:18100") as client:
        before = client.get("/lab/status").json()["acknowledgements"]
        with client.websocket_connect(
            "ws://localhost:18100/lab/preview/left", headers={"origin": "http://localhost:18100"}
        ) as ws:
            first = ws.receive_json()
            ws.receive_bytes()
            assert client.get("/lab/status").json()["source"] == "synthetic"
            ws.send_text(f"ack:{first['sequence']}")
            second = ws.receive_json()
            ws.receive_bytes()
            assert second["acknowledged_frames"] == 1
            ws.send_text("wrong")
            assert ws.receive_json()["message"] == "Invalid frame acknowledgement"
        after = client.get("/lab/status").json()["acknowledgements"]
        assert after["acknowledged"] == before["acknowledged"] + 1
        assert after["invalid"] == before["invalid"] + 1


def test_broker_error_queue_is_bounded_and_reports_overflow():
    slot = lab.LatestFrame()
    for number in range(20):
        slot.report_error(str(number))
    assert len(slot.errors) == 16 and slot.error_overflow == 4
    assert slot.errors[0] == "0" and slot.event.is_set()


def test_broker_delivers_overflow_notice_before_pending_frame(monkeypatch):
    class FloodNative(FakeNative):
        async def start(self, view, image_format, slot, owner=None):
            self.owner = owner
            for number in range(20):
                slot.report_error(str(number))
            slot.publish_native(b"\x89PNG\r\n\x1a\nexample", {"width": 1, "height": 1})

    monkeypatch.setattr(lab, "native", FloodNative())
    with TestClient(lab.app, base_url="http://localhost:18100") as client:
        with client.websocket_connect(
            "ws://localhost:18100/lab/preview/left?source=native",
            headers={"origin": "http://localhost:18100"},
        ) as ws:
            assert ws.receive_json()["type"] == "status"
            assert [ws.receive_json()["message"] for _ in range(16)] == [str(n) for n in range(16)]
            assert ws.receive_json()["message"] == "4 additional diagnostic events omitted"
            assert ws.receive_json()["type"] == "frame"
            ws.receive_bytes()


def test_worker_throttling_is_counted_separately_from_invalid_messages():
    counters = worker.PreviewCounters()
    assert counters.admit(10.0)
    assert not counters.admit(10.1)
    counters.invalid += 1
    assert counters.admit(10.3)
    assert counters.throttled == 1 and counters.invalid == 1


def test_worker_diagnostics_survive_frame_replacement_and_report_overflow():
    class BlockedStream(io.BytesIO):
        entered = threading.Event()
        release = threading.Event()

        def write(self, data):
            self.entered.set()
            assert self.release.wait(3)
            return super().write(data)

    stream = BlockedStream()
    writer = worker.Writer(stream)
    try:
        writer.offer({"type": "frame"}, b"a")
        assert stream.entered.wait(2)
        for i in range(20):
            writer.offer({"type": "error", "message": str(i)})
        writer.offer({"type": "frame"}, b"b")
        writer.offer({"type": "frame"}, b"c")
        assert writer.diagnostic_overflow == 4 and writer.dropped >= 1
        stream.release.set()

        async def records():
            for _ in range(100):
                if writer.diagnostics.empty() and writer.frames.empty():
                    break
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)
            reader = asyncio.StreamReader()
            reader.feed_data(stream.getvalue())
            reader.feed_eof()
            result = []
            while True:
                try:
                    result.append(await protocol.read_record(reader))
                except asyncio.IncompleteReadError:
                    return result

        result = asyncio.run(records())
        errors = [h for h, _ in result if h["type"] == "error"]
        assert len(errors) == 16 and errors[0]["message"] == "0"
        assert all(h["diagnostic_overflow"] == 4 for h in errors)
        assert any(payload == b"c" for _, payload in result)
    finally:
        stream.release.set()
        writer.closed.set()
        writer.thread.join(2)
