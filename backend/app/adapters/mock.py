import json
import math
from pathlib import Path
from app.models.telemetry import metric
from app.adapters.ros2 import graph_result


class MockHardware:
    mode = "mock"

    def __init__(self):
        self.tick = 0
        fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/mock_host.json"
        self.fixture = json.loads(fixture.read_text())

    def collect(self):
        self.tick += 1
        f = self.fixture

        def m(value, unit="text"):
            return metric(value, unit, "MOCK fixture / deterministic simulation")

        wave = math.sin(self.tick / 8)

        def freq(n):
            return {
                "current": m(n, "MHz"),
                "min": m(n / 2, "MHz"),
                "max": m(n, "MHz"),
                "governor": m("performance"),
                "available_frequencies": m([n / 2, n], "MHz"),
                "available_governors": m(["performance", "powersave"]),
            }

        cores = [m(round(22 + 12 * math.sin(self.tick / 8 + i / 2), 1), "%") for i in range(8)]
        total = f["memory_bytes"]
        ram = 37 + 2 * wave
        result = {
            "system": {k: m(v) for k, v in f["system"].items()},
            "cpu": {
                "overall": m(sum(c["value"] for c in cores) / 8, "%"),
                "core_ids": m(list(range(8)), "CPU IDs"),
                "cores": cores,
                "frequencies": [m(1500, "MHz") for _ in cores],
                "load_average": m([1.24, 1.09, 0.96], "1/5/15 min"),
            },
            "memory": {
                "total": m(total, "B"),
                "used": m(int(total * ram / 100), "B"),
                "available": m(int(total * (1 - ram / 100)), "B"),
                "percent": m(ram, "%"),
            },
            "storage": {
                "volumes": [
                    {
                        "path": "/",
                        "total": m(64_000_000_000, "B"),
                        "used": m(17_000_000_000, "B"),
                        "free": m(47_000_000_000, "B"),
                        "percent": m(26.56, "%"),
                    }
                ]
            },
            "thermal": {
                "cpu": m(47 + 2 * wave, "°C"),
                "ddr": m(43 + wave, "°C"),
                "cooling_devices": m(
                    [
                        {
                            "name": "cooling_device0",
                            "type": m("cpufreq"),
                            "state": m(0, "state"),
                            "max_state": m(3, "state"),
                        }
                    ],
                    "devices",
                ),
            },
            "bpu": {
                "devices": m(
                    [
                        {"path": "/dev/bpu", "readable": True},
                        {"path": "/dev/bpu_core0", "readable": True},
                    ],
                    "devices",
                ),
                "frequency": freq(1000),
                "utilization": m(round(18 + 12 * wave, 1), "%"),
                "temperature": metric(
                    None,
                    "°C",
                    "MOCK hwmon name=pvt / temp2_input",
                    "Simulated dedicated BPU sensor timeout",
                ),
                "cpu_temperature_proxy": m(47 + 2 * wave, "°C"),
                "temperature_fallback": m("cpu_proxy", "state"),
            },
            "frequencies": {"gpu": freq(750), "ddr": freq(2133)},
            "network": {
                "interfaces": [
                    {
                        "name": "eth0",
                        "up": m(True, "boolean"),
                        "addresses": m(["192.168.127.10"], "IP addresses"),
                        "rx": m(32000 + 8000 * wave, "B/s"),
                        "tx": m(9000 + 2000 * wave, "B/s"),
                    },
                    {
                        "name": "wlan0",
                        "up": m(True, "boolean"),
                        "addresses": m(["192.168.1.59"], "IP addresses"),
                        "rx": m(1500, "B/s"),
                        "tx": m(800, "B/s"),
                    },
                ]
            },
            "services": {
                name: m({"active": "active", "sub": "running"}, "state")
                for name in ["docker", "containerd"]
            },
        }
        result["system"]["uptime"] = m(89412 + self.tick, "s")
        result["services"]["inventory"] = metric(
            None,
            "containers",
            "MOCK / not collected",
            "Container inventory is outside this release; no Docker socket access",
        )
        return result


class MockRos2:
    def collect(self):
        path = Path(__file__).resolve().parents[3] / "tests/fixtures/ros2_graph.json"
        result = graph_result(json.loads(path.read_text()), source="MOCK ROS2 graph fixture")
        result["ros2"]["probe_duration"] = metric(3.4, "s", "MOCK ROS2 duration fixture")
        return result
