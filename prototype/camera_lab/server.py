"""Loopback-only synthetic camera laboratory; never starts ROS or a camera."""

import asyncio
import logging
import resource
import time
from collections import deque
from contextlib import suppress
from pathlib import Path

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from native_protocol import MAX_PAYLOAD
from native_supervisor import NativeSupervisor

MAX_FRAME = 256 * 1024
MAX_CLIENTS = 2
FPS = 5
ACK_TIMEOUT = 2.0
VIEWS = {"left", "right", "combined"}
DIST = Path(__file__).resolve().parent / "dist"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")
clients = set()
client_sources = {}
ack_totals = {"acknowledged": 0, "invalid": 0, "timeouts": 0}
native = NativeSupervisor()


@app.get("/lab/status")
async def status():
    sources = sorted(set(client_sources.values()))
    return {
        "source": sources[0] if len(sources) == 1 else "mixed" if sources else "inactive",
        "sources": sources,
        "active_clients": len(clients),
        "max_clients": MAX_CLIENTS,
        "acknowledgements": dict(ack_totals),
    }


@app.get("/")
async def index():
    return FileResponse(DIST / "camera-lab" / "index.html")


def validate_frame(data, encoding, width, height):
    if encoding != "image/svg+xml":
        raise ValueError("unsupported synthetic encoding")
    if not isinstance(data, bytes) or not data.startswith(b"<svg ") or not data.endswith(b"</svg>"):
        raise ValueError("invalid image message")
    if len(data) > MAX_FRAME or not (1 <= width <= 1920 and 1 <= height <= 1080):
        raise ValueError("frame exceeds laboratory bounds")
    return data


def synthetic_frame(view, sequence):
    if view not in VIEWS:
        raise ValueError("unknown view")
    # SVG consists only of trusted constants, chosen view and an integer counter.
    width, height = 640, 360
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="640" height="360" fill="#122332"/>'
        '<path d="M0 260 L140 120 L250 235 L380 75 L640 270 V360 H0Z" fill="#25485a"/>'
        '<path d="M0 300 L180 215 L310 285 L470 175 L640 265 V360 H0Z" fill="#386b70"/>'
        '<circle cx="485" cy="80" r="28" fill="#c19c6e"/>'
        '<path d="M0 300 H640 M160 0 V360 M320 0 V360 M480 0 V360" stroke="#91bdc1" opacity=".22"/>'
        f'<text x="26" y="40" fill="#e5f4f8" font-family="sans-serif" font-size="19">MOCK DATA · {view.upper()}</text>'
        f'<text x="26" y="335" fill="#b9dae1" font-family="monospace" font-size="15">SYNTHETIC FRAME {sequence}</text></svg>'
    )
    return validate_frame(svg.encode(), "image/svg+xml", width, height), width, height


class LatestFrame:
    """One latest slot; replacement drops an obsolete frame instead of queuing."""

    def __init__(self):
        self.sequence = 0
        self.frame = None
        self.event = asyncio.Event()
        self.produced = 0
        self.native_meta = None
        self.error = None
        self.fatal = False
        self.publishers = None
        self.status_pending = False
        self.errors = deque(maxlen=16)
        self.error_overflow = 0

    def report_error(self, message, fatal=False):
        self.error = message
        self.fatal = self.fatal or fatal
        if len(self.errors) == self.errors.maxlen:
            self.error_overflow += 1
        else:
            self.errors.append(message)
        self.event.set()

    def publish(self, data, encoding, width, height):
        data = validate_frame(data, encoding, width, height)
        self.sequence += 1
        self.produced += 1
        self.frame = (self.sequence, data, width, height, time.monotonic())
        self.event.set()

    def publish_native(self, data, meta):
        if len(data) > MAX_PAYLOAD:
            raise ValueError("native image exceeds limit")
        self.sequence += 1
        self.produced += 1
        self.native_meta = meta
        self.frame = (self.sequence, data, meta["width"], meta["height"], time.monotonic())
        self.event.set()


async def wait_for_frame_or_disconnect(slot, ws, timeout):
    frame = asyncio.create_task(slot.event.wait())
    incoming = asyncio.create_task(ws.receive())
    try:
        done, _ = await asyncio.wait(
            (frame, incoming), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if incoming in done:
            raise WebSocketDisconnect()
        if frame not in done:
            raise asyncio.TimeoutError()
    finally:
        # A disconnect can race the ASGI server's cancellation of this session.
        # Finish reaping both helper tasks without replacing the disconnect with
        # a cancellation raised by the surrounding AnyIO cancel scope.
        with anyio.CancelScope(shield=True):
            for pending in (frame, incoming):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(frame, incoming, return_exceptions=True)


async def produce(slot, view):
    while True:
        frame, width, height = synthetic_frame(view, slot.sequence + 1)
        slot.publish(frame, "image/svg+xml", width, height)
        await asyncio.sleep(1 / FPS)


@app.websocket("/lab/preview/{view}")
async def preview(ws: WebSocket, view: str, source: str = "synthetic", image_format: str = "raw"):
    origin = ws.headers.get("origin", "")
    host = ws.headers.get("host", "")
    if (
        view not in VIEWS
        or source not in ("synthetic", "native")
        or image_format not in ("raw", "compressed")
        or (source == "native" and image_format == "compressed" and view != "combined")
        or origin != f"http://{host}"
        or host not in ("127.0.0.1:18100", "localhost:18100")
    ):
        await ws.close(code=1008)
        return
    if len(clients) >= MAX_CLIENTS:
        await ws.close(code=1013)
        return
    clients.add(ws)
    client_sources[ws] = source
    try:
        await ws.accept()
    except BaseException:
        clients.discard(ws)
        client_sources.pop(ws, None)
        raise
    slot = LatestFrame()
    task = None
    if source == "native":
        started_native = False
        try:
            starting = asyncio.create_task(native.start(view, image_format, slot, owner=ws))
            disconnected = asyncio.create_task(ws.receive())
            try:
                done, _ = await asyncio.wait(
                    (starting, disconnected), return_when=asyncio.FIRST_COMPLETED
                )
                if disconnected in done:
                    starting.cancel()
                    await asyncio.gather(starting, return_exceptions=True)
                    raise WebSocketDisconnect()
                await starting
                started_native = True
            finally:
                with anyio.CancelScope(shield=True):
                    if not starting.done():
                        starting.cancel()
                    await asyncio.gather(starting, return_exceptions=True)
                    if not started_native and native.owner is ws:
                        await native.stop()
                    if not disconnected.done():
                        disconnected.cancel()
                    await asyncio.gather(disconnected, return_exceptions=True)
            await ws.send_json(
                {
                    "type": "status",
                    "state": "waiting",
                    "message": "Native worker ready; waiting for publisher",
                }
            )
        except BaseException as exc:
            clients.discard(ws)
            client_sources.pop(ws, None)
            if started_native:
                with anyio.CancelScope(shield=True):
                    await native.stop()
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, WebSocketDisconnect):
                return
            with suppress(RuntimeError, WebSocketDisconnect):
                await ws.send_json(
                    {"type": "error", "message": "Native worker unavailable: " + str(exc)[:300]}
                )
                await ws.close()
            return
    else:
        task = asyncio.create_task(produce(slot, view))
    last = 0
    sent_bytes = 0
    sent_count = 0
    acknowledged = 0
    started = time.monotonic()
    cpu_started = time.process_time()
    try:
        while True:
            try:
                await wait_for_frame_or_disconnect(
                    slot, ws, 15 if source == "native" else ACK_TIMEOUT
                )
            except asyncio.TimeoutError:
                if source == "synthetic":
                    raise
                await ws.send_json(
                    {"type": "status", "state": "waiting", "message": "No native frames received"}
                )
                continue
            slot.event.clear()
            if slot.status_pending:
                slot.status_pending = False
                await asyncio.wait_for(
                    ws.send_json(
                        {
                            "type": "status",
                            "state": "waiting",
                            "publishers": slot.publishers,
                            "message": "No publisher detected"
                            if slot.publishers == 0
                            else (
                                "Publisher present; frames received"
                                if slot.frame and time.monotonic() - slot.frame[4] <= 2
                                else "Publisher present; waiting for usable frames"
                            ),
                        }
                    ),
                    2,
                )
                if slot.errors or slot.error_overflow or (slot.frame and slot.frame[0] > last):
                    slot.event.set()
                continue
            if slot.errors or slot.error_overflow:
                if slot.errors:
                    message = slot.errors.popleft()
                else:
                    message = f"{slot.error_overflow} additional diagnostic events omitted"
                    slot.error_overflow = 0
                await asyncio.wait_for(ws.send_json({"type": "error", "message": message}), 2)
                if slot.errors or slot.error_overflow or (slot.frame and slot.frame[0] > last):
                    slot.event.set()
                if slot.fatal and not slot.errors and not slot.error_overflow:
                    break
                continue
            if not slot.frame or slot.frame[0] <= last:
                continue
            seq, data, width, height, created = slot.frame
            dropped = max(0, seq - sent_count - 1)
            elapsed = max(time.monotonic() - started, 0.001)
            await asyncio.wait_for(
                ws.send_json(
                    {
                        "type": "frame",
                        "sequence": seq,
                        "view": view,
                        "source": source,
                        "encoding": slot.native_meta.get("encoding")
                        if source == "native"
                        else "image/svg+xml",
                        "mime": slot.native_meta.get("mime")
                        if source == "native"
                        else "image/svg+xml",
                        "width": width,
                        "height": height,
                        "fps": round(sent_count / elapsed, 2) if sent_count else None,
                        "bandwidth_bps": round(sent_bytes / elapsed) if sent_count else None,
                        "dropped": dropped,
                        "acknowledged_frames": acknowledged,
                        "frame_age_ms": round((time.monotonic() - created) * 1000),
                        "calibration": slot.native_meta.get("calibration")
                        if source == "native"
                        else None,
                        "display_mode": slot.native_meta.get("display_mode")
                        if source == "native"
                        else "synthetic",
                        "source_stamp": slot.native_meta.get("source_stamp")
                        if source == "native"
                        else None,
                        "worker_dropped": slot.native_meta.get("worker_dropped")
                        if source == "native"
                        else None,
                        "invalid_frames": slot.native_meta.get("invalid_frames")
                        if source == "native"
                        else None,
                        "throttled_frames": slot.native_meta.get("throttled_frames")
                        if source == "native"
                        else None,
                        "diagnostic_overflow": slot.native_meta.get("diagnostic_overflow")
                        if source == "native"
                        else None,
                        "lab_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        "lab_cpu_pct": round((time.process_time() - cpu_started) / elapsed * 100, 2)
                        if sent_count
                        else None,
                        "max_frame_bytes": MAX_PAYLOAD if source == "native" else MAX_FRAME,
                        **(native.metrics() if source == "native" else {}),
                    }
                ),
                2,
            )
            await asyncio.wait_for(ws.send_bytes(data), 2)
            sent_count += 1
            sent_bytes += len(data)
            last = seq
            try:
                message = await asyncio.wait_for(ws.receive_text(), ACK_TIMEOUT)
            except asyncio.TimeoutError:
                ack_totals["timeouts"] += 1
                raise
            if message != f"ack:{seq}":
                ack_totals["invalid"] += 1
                await ws.send_json({"type": "error", "message": "Invalid frame acknowledgement"})
                break
            acknowledged += 1
            ack_totals["acknowledged"] += 1
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        pass
    finally:
        try:
            if source == "native":
                with anyio.CancelScope(shield=True):
                    await native.stop()
            elif task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logging.getLogger(__name__).exception("Synthetic producer failed")
        finally:
            clients.discard(ws)
            client_sources.pop(ws, None)
        if ws.client_state == WebSocketState.CONNECTED:
            with suppress(RuntimeError):
                await ws.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=18100, log_level="warning", ws_max_size=1024)
