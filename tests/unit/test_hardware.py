import json
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.adapters.hardware import (
    NativeHardware,
    NetworkRates,
    SysfsReader,
    normalize_frequency,
    temperature,
)
from app.adapters.mock import MockHardware, MockRos2
from app.adapters.ros2 import Ros2Adapter, graph_result


@pytest.mark.parametrize(
    "raw,expected", [("47000", 47.0), ("-5000", -5.0), ("0", 0.0), ("100500", 100.5)]
)
def test_temperature_conversion(raw, expected):
    assert temperature(raw) == expected


@pytest.mark.parametrize("raw", ["nan", "inf", "bad", "201000", "-51000"])
def test_invalid_temperature(raw):
    with pytest.raises(ValueError):
        temperature(raw)


@pytest.mark.parametrize(
    "raw,unit,expected",
    [
        ("1000000000", "Hz", 1000),
        ("1500000", "kHz", 1500),
        ("750", "MHz", 750),
        ("2133000000", "Hz", 2133),
    ],
)
def test_frequency_units(raw, unit, expected):
    assert normalize_frequency(raw, unit) == expected


@pytest.mark.parametrize(
    "raw,unit",
    [
        ("NaN", "Hz"),
        ("0", "Hz"),
        ("-1", "kHz"),
        ("foo", "MHz"),
        ("1000", "unknown"),
        ("1e99", "Hz"),
    ],
)
def test_invalid_frequency(raw, unit):
    with pytest.raises(ValueError):
        normalize_frequency(raw, unit)


def test_missing_sysfs_and_bpu(tmp_path):
    r = SysfsReader(tmp_path, tmp_path)
    assert r.thermals()["cpu"]["value"] is None
    assert r.thermals()["ddr"]["reason"]
    for v in r.frequency("bpu").values():
        assert v["value"] is None and v["status"] == "unavailable"
    assert r.bpu_devices()["value"] is None
    assert r.bpu_devices()["reason"]


def test_thermal_discovery_by_type_and_cooling(tmp_path):
    base = tmp_path / "class/thermal"
    for n, t, temp in [
        ("thermal_zone9", "thermal-ddr", "42000"),
        ("thermal_zone2", "thermal-cpu", "49000"),
        ("thermal_zone0", "unrelated", "90000"),
    ]:
        p = base / n
        p.mkdir(parents=True)
        (p / "type").write_text(t)
        (p / "temp").write_text(temp)
    c = base / "cooling_device7"
    c.mkdir()
    (c / "type").write_text("cpufreq")
    (c / "cur_state").write_text("0")
    (c / "max_state").write_text("4")
    r = SysfsReader(tmp_path).thermals()
    assert r["cpu"]["value"] == 49 and r["ddr"]["value"] == 42
    assert r["cooling_devices"]["value"][0]["state"]["value"] == 0
    (base / "thermal_zone2/temp").write_text("broken")
    assert SysfsReader(tmp_path).thermals()["cpu"]["status"] == "error"


def test_frequency_files(tmp_path):
    p = tmp_path / "class/devfreq/3a000000.bpu"
    p.mkdir(parents=True)
    for file, text in {
        "cur_freq": "1000000000",
        "min_freq": "500000000",
        "max_freq": "1000000000",
        "governor": "performance",
        "available_frequencies": "500000000 1000000000",
        "available_governors": "performance powersave",
    }.items():
        (p / file).write_text(text)
    f = SysfsReader(tmp_path).frequency("bpu")
    assert f["current"]["value"] == 1000 and f["current"]["unit"] == "MHz"
    assert f["available_frequencies"]["value"] == [500, 1000]
    assert f["available_governors"]["value"] == ["performance", "powersave"]


Counter = namedtuple("Counter", "bytes_recv bytes_sent")


def test_network_throughput_reset_reappear():
    rates = NetworkRates()
    assert rates.update({"eth0": Counter(100, 200)}, 10)["eth0"]["rx"]["value"] is None
    result = rates.update({"eth0": Counter(300, 600)}, 12)
    assert result["eth0"]["rx"]["value"] == 100 and result["eth0"]["tx"]["value"] == 200
    assert rates.update({"eth0": Counter(0, 0)}, 13)["eth0"]["rx"]["value"] is None
    rates.update({}, 14)
    assert rates.update({"eth0": Counter(100, 100)}, 15)["eth0"]["rx"]["value"] is None


def test_network_invalid_interval():
    r = NetworkRates()
    r.update({"x": Counter(2, 3)}, 1)
    assert r.update({"x": Counter(4, 5)}, 1)["x"]["rx"]["value"] is None


def test_cpu_collection_without_fake_initial_zero(monkeypatch, tmp_path):
    Cpu = namedtuple("Cpu", "user nice system idle iowait irq softirq steal guest guest_nice")
    samples = [
        [Cpu(20, 0, 10, 70, 0, 0, 0, 0, 0, 0), Cpu(20, 0, 10, 70, 0, 0, 0, 0, 0, 0)],
        [Cpu(25, 0, 10, 75, 0, 0, 0, 0, 0, 0), Cpu(22, 0, 10, 78, 0, 0, 0, 0, 0, 0)],
    ]
    monkeypatch.setattr("app.adapters.hardware.psutil.cpu_times", lambda **kw: samples.pop(0))
    monkeypatch.setattr("app.adapters.hardware.os.getloadavg", lambda: (1, 2, 3))
    h = NativeHardware(reader=SysfsReader(tmp_path))
    first = h.cpu()
    assert first["overall"]["value"] is None and first["overall"]["status"] == "warming_up"
    second = h.cpu()
    assert [m["value"] for m in second["cores"]] == [50, 20]
    assert second["overall"]["value"] == 35
    assert second["frequencies"][0]["value"] is None


def test_memory_collection(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1000, available=400),
    )
    data = NativeHardware().memory()
    assert data["used"]["value"] == 600 and data["percent"]["value"] == 60
    assert data["total"]["unit"] == "B"


def test_storage_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.disk_usage", Mock(side_effect=PermissionError)
    )
    assert NativeHardware().storage()["volumes"][0]["percent"]["value"] is None


def test_missing_vendor_utilities_never_invoked(monkeypatch, tmp_path):
    runner = Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr("app.adapters.hardware.subprocess.run", runner)
    h = NativeHardware(reader=SysfsReader(tmp_path, tmp_path))
    data = h.collect()
    assert data["bpu"]["utilization"]["value"] is None
    assert data["bpu"]["temperature"]["value"] is None
    runner.assert_not_called()
    services = h.services()
    assert services["docker"]["value"] is None
    for call in runner.call_args_list:
        assert call.args[0][0] == "/usr/bin/systemctl"
        assert call.kwargs["timeout"] == 1
        assert "shell" not in call.kwargs


def test_missing_ros2_environment(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda _: False)
    monkeypatch.setattr(
        "app.adapters.ros2.subprocess.run", Mock(side_effect=AssertionError("must not execute"))
    )
    result = Ros2Adapter(enabled=True).collect()
    assert result["ros2"]["available"]["value"] is None
    assert "not installed" in result["ros2"]["available"]["reason"]


def test_disabled_ros2():
    assert "disabled" in Ros2Adapter().collect()["ros2"]["available"]["reason"]


def test_ros2_mock_graph_and_known_camera_topics():
    result = MockRos2().collect()
    assert result["ros2"]["available"]["value"] is True
    assert "/mipi_cam" in result["ros2"]["nodes"]["value"]
    assert len(result["cameras"]["topics"]) == 8
    assert all(
        t["publishers"]["value"] == (0 if t["name"] == "/image_combine_jpeg" else 1)
        for t in result["cameras"]["topics"]
    )
    assert "MOCK" in result["ros2"]["topics"]["source"]


def test_empty_valid_ros2_graph_reports_zero_publishers():
    r = graph_result({"nodes": [], "topics": []})
    assert r["ros2"]["available"]["value"] is True
    assert r["cameras"]["node_present"]["value"] is False
    assert r["cameras"]["topics"][0]["publishers"]["value"] == 0


def test_ros2_probe_fixed_command_and_timeout(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    monkeypatch.setenv("ROS_DISTRO", "humble")
    runner = Mock(
        return_value=SimpleNamespace(
            stdout=json.dumps({"nodes": ["/mipi_cam"], "topics": []}), stderr="", returncode=0
        )
    )
    monkeypatch.setattr("app.adapters.ros2.subprocess.run", runner)
    assert (
        Ros2Adapter(True, runner=SimpleNamespace(run=runner)).collect()["cameras"]["node_present"][
            "value"
        ]
        is True
    )
    args = runner.call_args
    assert args.args[0][0] == "/usr/bin/python3"
    assert args.args[0][1].endswith("ros2_probe.py")
    assert args.kwargs["timeout"] == 8 and "shell" not in args.kwargs


def test_ros2_invalid_probe_output(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    monkeypatch.setenv("ROS_DISTRO", "humble")
    runner = Mock(
        return_value=SimpleNamespace(
            stdout='{"nodes":[";touch /tmp/injected"],"topics":[]}', stderr="", returncode=0
        )
    )
    assert (
        Ros2Adapter(True, runner=SimpleNamespace(run=runner)).collect()["ros2"]["available"][
            "value"
        ]
        is None
    )


def test_mock_identity():
    mock = MockHardware()
    data = mock.collect()
    assert mock.mode == "mock" and data["system"]["architecture"]["value"] == "aarch64"
    assert all("MOCK" in m["source"] for m in data["cpu"]["cores"])


def test_permission_denied_network_interfaces(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.net_io_counters", lambda **kw: {"eth0": Counter(20, 30)}
    )
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.net_if_stats", Mock(side_effect=PermissionError)
    )
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.net_if_addrs", Mock(side_effect=PermissionError)
    )
    result = NativeHardware().network()["interfaces"][0]
    assert result["up"]["value"] is None and result["up"]["reason"]
    assert result["addresses"]["value"] is None and result["addresses"]["reason"]
    assert result["rx"]["value"] is None


def test_cpu_identity_with_offline_core(monkeypatch, tmp_path):
    Cpu = namedtuple("Cpu", "user idle")
    monkeypatch.setattr(
        "app.adapters.hardware.psutil.cpu_times", lambda **kw: [Cpu(20, 80), Cpu(30, 70)]
    )
    (tmp_path / "stat").write_text("cpu 50 150\ncpu0 20 80\ncpu3 30 70\n")
    for core, frequency in [(0, "1500000"), (3, "1200000")]:
        path = tmp_path / f"devices/system/cpu/cpu{core}/cpufreq"
        path.mkdir(parents=True)
        (path / "scaling_cur_freq").write_text(frequency)
    result = NativeHardware(reader=SysfsReader(tmp_path), proc_root=tmp_path).cpu()
    assert result["core_ids"]["value"] == [0, 3]
    assert [m["value"] for m in result["frequencies"]] == [1500, 1200]
