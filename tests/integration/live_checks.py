"""Run against the owned local QA services, including the production Nginx proxy."""

import asyncio
import json
import os
import urllib.error
import urllib.request
import websockets


def main():
    root = "http://127.0.0.1:" + os.environ.get("RDK_QA_DASHBOARD_PORT", "8088")
    for path in [
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
    ]:
        with urllib.request.urlopen(root + "/api/v1/" + path, timeout=5) as r:
            assert json.load(r)["mode"] == "mock"
    with urllib.request.urlopen(root, timeout=5) as r:
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
        assert r.headers["X-Frame-Options"] == "DENY"
    try:
        urllib.request.urlopen(
            urllib.request.Request(root + "/api/v1/system", method="POST"), timeout=3
        )
        raise AssertionError("POST allowed")
    except urllib.error.HTTPError as error:
        assert error.code == 405

    async def sockets():
        url = root.replace("http:", "ws:") + "/ws/v1/telemetry"
        for _ in range(2):
            async with websockets.connect(url, origin=root) as ws:
                assert json.loads(await asyncio.wait_for(ws.recv(), 3))["mode"] == "mock"
        try:
            async with websockets.connect(url, origin="https://evil.example"):
                raise AssertionError("Untrusted WebSocket accepted")
        except websockets.exceptions.InvalidStatus as error:
            assert error.response.status_code == 403

    asyncio.run(sockets())
    print(
        "LIVE CHECKS: 12 endpoints, security headers, POST rejection, WebSocket reconnect/origin rejection passed"
    )


if __name__ == "__main__":
    main()
