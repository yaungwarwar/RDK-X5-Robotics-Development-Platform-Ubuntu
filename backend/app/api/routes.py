from app.version import VERSION
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
import asyncio

router = APIRouter()
SECTIONS = [
    "system",
    "cpu",
    "memory",
    "storage",
    "thermal",
    "bpu",
    "network",
    "ros2",
    "cameras",
    "services",
]


@router.get("/api/v1/health")
def health(request: Request):
    monitor = request.app.state.monitor
    snapshot = monitor.snapshot()
    if snapshot is None:
        raise HTTPException(503, "No successful telemetry sample")
    return {
        "status": "degraded" if snapshot["stale"] or monitor.error else "ok",
        "version": VERSION,
        "mode": snapshot["mode"],
        "timestamp": snapshot["timestamp"],
        "stale": snapshot["stale"],
        "age_seconds": snapshot["age_seconds"],
        "collector_error": monitor.error,
    }


@router.get("/api/v1/snapshot")
def snapshot(request: Request):
    result = request.app.state.monitor.snapshot()
    if result is None:
        raise HTTPException(503, "No successful telemetry sample")
    return result


def endpoint(section):
    def get_section(request: Request):
        result = snapshot(request)
        return {k: v for k, v in result.items() if k != "data"} | {"data": result["data"][section]}

    get_section.__name__ = "get_" + section
    return get_section


for section in SECTIONS:
    router.add_api_route("/api/v1/" + section, endpoint(section), methods=["GET"])


@router.websocket("/ws/v1/telemetry")
async def telemetry(websocket: WebSocket):
    settings = websocket.app.state.settings
    if websocket.headers.get("origin") not in settings.allowed_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            result = websocket.app.state.monitor.snapshot()
            if result is not None:
                await asyncio.wait_for(websocket.send_json(result), timeout=3)
            # Detect disconnects promptly; client messages never invoke commands.
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=settings.interval_seconds
                )
                if message["type"] == "websocket.disconnect":
                    break
                await websocket.close(code=1008, reason="Telemetry channel is server-push only")
                break
            except asyncio.TimeoutError:
                continue
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        return
