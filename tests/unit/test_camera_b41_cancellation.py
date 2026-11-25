"""Deterministic synthetic cancellation and real local WebSocket regressions."""

import asyncio
import os
import socket
import sys
from pathlib import Path

import anyio
import pytest
import uvicorn
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototype/camera_lab"))
import native_supervisor as supervisor  # noqa: E402
import server as lab  # noqa: E402


def test_disconnect_helper_cleanup_survives_anyio_scope_cancellation(monkeypatch):
    async def scenario():
        entered, release, scope_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_gather = asyncio.gather
        result = []
        scopes = []

        async def held_gather(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original_gather(*args, **kwargs)

        class Disconnected:
            async def receive(self):
                return {"type": "websocket.disconnect"}

        async def session():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                scope_ready.set()
                try:
                    await lab.wait_for_frame_or_disconnect(lab.LatestFrame(), Disconnected(), 2)
                except WebSocketDisconnect:
                    result.append("disconnect")

        monkeypatch.setattr(lab.asyncio, "gather", held_gather)
        task = asyncio.create_task(session())
        await asyncio.wait_for(scope_ready.wait(), 1)
        await asyncio.wait_for(entered.wait(), 1)
        scopes[0].cancel()
        await asyncio.sleep(0)  # Yield to deliver the scheduled cancellation, not a delay.
        release.set()
        await asyncio.wait_for(task, 1)
        assert result == ["disconnect"]

    asyncio.run(scenario())


def test_cancelled_stop_keeps_one_cleanup_until_worker_reaped(monkeypatch):
    async def scenario():
        active = supervisor.NativeSupervisor(
            [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "frame"]
        )
        await active.start("left", "raw", lab.LatestFrame())
        pid = active.process.pid
        entered, release = asyncio.Event(), asyncio.Event()
        original = active._stop_impl

        async def held_stop():
            entered.set()
            await release.wait()
            await original()

        monkeypatch.setattr(active, "_stop_impl", held_stop)
        first = asyncio.create_task(active.stop())
        await asyncio.wait_for(entered.wait(), 1)
        shared = active.cleanup_task
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(active.stop())
        await asyncio.sleep(0)
        assert active.cleanup_task is shared and active.reserved and active.process.pid == pid
        release.set()
        await asyncio.wait_for(second, 3)
        assert shared.done() and active.process is None and not active.reserved
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    asyncio.run(scenario())


def test_real_local_websocket_disconnect_reaps_synthetic_worker(monkeypatch):
    async def scenario():
        active = supervisor.NativeSupervisor(
            [sys.executable, str(ROOT / "tests/fixtures/native_camera_fake.py"), "frame"]
        )
        monkeypatch.setattr(lab, "native", active)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        instance = uvicorn.Server(uvicorn.Config(lab.app, log_level="error", lifespan="on"))
        serving = asyncio.create_task(instance.serve(sockets=[sock]))
        pid = None
        try:

            async def ready():
                while not instance.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("Local ASGI server exited before startup")
                    await asyncio.sleep(0)

            await asyncio.wait_for(ready(), 5)
            async with connect(
                "ws://localhost:18100/lab/preview/left?source=native",
                host="127.0.0.1",
                port=port,
                origin="http://localhost:18100",
            ) as ws:
                import json

                assert json.loads(await ws.recv())["type"] == "status"
                frame = json.loads(await ws.recv())
                assert frame["source"] == "native" and (await ws.recv()).startswith(b"\x89PNG")
                pid = active.process.pid
                await ws.send(f"ack:{frame['sequence']}")
            await asyncio.wait_for(active.stopped_event.wait(), 5)
            assert not active.reserved and active.process is None and active.cleanup_task.done()
            assert active.reader_task is None and active.stderr_task is None
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            instance.should_exit = True
            await asyncio.wait_for(serving, 5)
            sock.close()
        assert not lab.clients and not lab.client_sources
        assert active.cleanup_task.done() and not active.reserved

    asyncio.run(scenario())
