from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.config.settings import Settings
from app.main import create_app


@pytest.fixture
def app():
    return create_app(
        Settings(
            mode="mock",
            interval_seconds=0.2,
            allowed_hosts=["testserver", "localhost", "127.0.0.1"],
        )
    )


@pytest.mark.parametrize(
    "path",
    [
        "health",
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
        "snapshot",
    ],
)
def test_api_endpoints(app, path):
    with TestClient(app) as client:
        response = client.get("/api/v1/" + path)
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "mock" and data["timestamp"]
        if path != "health":
            assert data["data"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"


def test_release_version_consistent_in_health_and_snapshot(app):
    with TestClient(app) as client:
        assert app.version == "0.1.3"
        assert client.get("/api/v1/health").json()["version"] == "0.1.3"
        assert client.get("/api/v1/snapshot").json()["version"] == "0.1.3"
        monitor = app.state.monitor
        assert monitor.task is not None and not monitor.task.done()
    assert monitor.task.done()
    assert monitor.slow_task.done()
    assert monitor.executor._shutdown


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_read_only_api(app, method):
    with TestClient(app) as client:
        assert getattr(client, method)("/api/v1/system").status_code == 405
        assert getattr(client, method)("/api/v1/execute").status_code == 404


def test_host_and_cors_restrictions(app):
    with TestClient(app) as client:
        assert client.get("/api/v1/health", headers={"host": "evil.example"}).status_code == 400
        response = client.get("/api/v1/health", headers={"origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers
        response = client.get("/api/v1/health", headers={"origin": "http://localhost:8088"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:8088"


def test_ws_reconnect_uses_same_collector(app):
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/telemetry", headers={"origin": "http://localhost:8088"}
        ) as ws:
            first = ws.receive_json()
            second = ws.receive_json()
            assert second["sequence"] >= first["sequence"] and first["mode"] == "mock"
        with client.websocket_connect(
            "/ws/v1/telemetry", headers={"origin": "http://localhost:8088"}
        ) as ws:
            assert ws.receive_json()["sequence"] >= first["sequence"]
        assert app.state.monitor.task is not None
        assert len(app.state.monitor.history) <= app.state.settings.history_size


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_ws_rejects_untrusted_origin(app, origin):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/v1/telemetry", headers={"origin": origin} if origin else {}
            ):
                pass


def test_ws_rejects_commands(app):
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/telemetry", headers={"origin": "http://localhost:8088"}
        ) as ws:
            ws.receive_json()
            ws.send_text("$(touch /tmp/rdk-injection)")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_stale_snapshot(app):
    with TestClient(app) as client:
        client.portal.call(app.state.monitor.stop)
        old = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        app.state.monitor.latest["timestamp"] = old
        app.state.monitor.latest["data"]["cpu"]["overall"]["timestamp"] = old
        data = client.get("/api/v1/snapshot").json()
        assert data["stale"] and data["data"]["cpu"]["overall"]["stale"]
        assert client.get("/api/v1/health").json()["status"] == "degraded"


def test_shared_sample_not_recollected_for_browsers(app):
    with TestClient(app) as client:
        client.portal.call(app.state.monitor.stop)
        a = client.get("/api/v1/snapshot").json()
        b = client.get("/api/v1/cpu").json()
        assert a["sequence"] == b["sequence"]
        assert (
            a["data"]["cpu"] == b["data"]
            or a["data"]["cpu"]["overall"]["timestamp"] == b["data"]["overall"]["timestamp"]
        )


def test_native_bpu_and_ros_diagnostics_contract(app):
    with TestClient(app) as client:
        data = client.get("/api/v1/snapshot").json()["data"]
        assert data["bpu"]["utilization"]["unit"] == "%"
        assert data["bpu"]["temperature"]["value"] is None
        assert data["bpu"]["cpu_temperature_proxy"]["value"] is not None
        assert data["bpu"]["temperature_fallback"]["value"] == "cpu_proxy"
        assert data["ros2"]["probe_duration"]["unit"] == "s"
        assert data["ros2"]["last_success"]["value"]
        assert data["ros2"]["consecutive_failures"]["value"] == 0
