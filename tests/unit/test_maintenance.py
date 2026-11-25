import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.adapters.hardware import SysfsReader, bpu_ratio, NativeHardware
from app.adapters.bpu_temperature import BpuTemperature, temperature_report
from app.adapters.bpu_temperature_probe import discover, read_sensor
from app.adapters.ros2 import Ros2Adapter, graph_result
from app.adapters.bounded_command import BoundedCommand, CommandBusy
from app.config.settings import Settings
from app.models.telemetry import freshen, metric


@pytest.mark.parametrize("raw,expected", [("0", 0), ("1", 1), ("99", 99), ("100", 100)])
def test_bpu_ratio_preserves_percentage(raw, expected):
    assert bpu_ratio(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "101", "1.0", "1%", "nan", "0 1", "+2", "1000", ""])
def test_invalid_bpu_ratio(raw):
    with pytest.raises(ValueError):
        bpu_ratio(raw)


def test_missing_denied_and_invalid_ratio(tmp_path, monkeypatch):
    reader = SysfsReader(tmp_path)
    assert reader.bpu_utilization()["value"] is None
    path = tmp_path / "devices/platform/soc/3a000000.bpu/ratio"
    path.parent.mkdir(parents=True)
    path.write_text("0\n")
    assert reader.bpu_utilization()["value"] == 0
    assert reader.bpu_utilization()["source"] == str(path)
    path.write_text("102")
    assert reader.bpu_utilization()["status"] == "error"
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=PermissionError))
    assert reader.bpu_utilization()["value"] is None
    assert "denied" in reader.bpu_utilization()["reason"]


def test_hwmon_discovery_by_name_and_missing_dedicated(tmp_path):
    for name, device in [("hwmon0", "unrelated"), ("hwmon7", "pvt")]:
        p = tmp_path / name
        p.mkdir()
        (p / "name").write_text(device)
    assert discover(tmp_path) == tmp_path / "hwmon7"
    result = read_sensor(tmp_path / "hwmon7/temp2_input")
    assert result["raw"] is None and "missing" in result["error"]


class SensorProcess:
    def __init__(self, payload=None, running=False, unkillable=False):
        rd, wr = os.pipe()
        self.stdout = os.fdopen(rd, "rb", buffering=0)
        if payload is not None:
            os.write(wr, json.dumps(payload).encode())
        os.close(wr)
        self.returncode = None if running else 0
        self.unkillable = unkillable
        self.kills = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.kills += 1
        if not self.unkillable:
            self.returncode = -9


def settings():
    return Settings(bpu_temperature_timeout_seconds=0.1)


def test_dedicated_sensor_success_and_failure(tmp_path):
    process = SensorProcess(
        {
            "dedicated": {
                "raw": "59705",
                "source": "/sys/class/hwmon/hwmon7/temp2_input",
                "error": None,
            }
        }
    )
    runner = Mock(return_value=process)
    adapter = BpuTemperature(settings(), popen=runner, clock=lambda: 0)
    assert adapter.poll()["value"] is None
    result = adapter.poll()
    assert result["value"] == 59.705 and result["unit"] == "°C"
    assert runner.call_count == 1
    assert adapter.poll()["timestamp"] == result["timestamp"]
    adapter.close()


def test_dedicated_missing_does_not_use_cpu_as_bpu():
    process = SensorProcess(
        {
            "dedicated": {
                "raw": None,
                "source": "/sys/class/hwmon/hwmon7/temp2_input",
                "error": "Sensor interface missing",
            }
        }
    )
    adapter = BpuTemperature(settings(), popen=Mock(return_value=process), clock=lambda: 0)
    adapter.poll()
    result = adapter.poll()
    assert result["value"] is None and "missing" in result["reason"]
    report = temperature_report(result, metric(58.728, "°C", "thermal-cpu"), True)
    assert report["temperature"]["value"] is None
    assert report["cpu_temperature_proxy"]["value"] == 58.728
    assert "not an independently measured BPU" in report["cpu_temperature_proxy"]["reason"]
    assert report["temperature_fallback"]["value"] == "cpu_proxy"
    assert (
        temperature_report(result, metric(58, "°C", "CPU"), False)["cpu_temperature_proxy"]["value"]
        is None
    )


def test_temperature_timeout_and_quarantine_prevent_worker_accumulation():
    clock = [0.0]
    process = SensorProcess(running=True, unkillable=True)
    runner = Mock(return_value=process)
    adapter = BpuTemperature(settings(), popen=runner, clock=lambda: clock[0])
    adapter.poll()
    clock[0] = 2
    assert "timed out" in adapter.poll()["reason"]
    for _ in range(30):
        clock[0] += 100
        adapter.poll()
    assert runner.call_count == 1 and process.kills == 1
    adapter.close()
    assert process.kills == 1
    process.returncode = -9
    replacement = SensorProcess(running=True)
    runner.return_value = replacement
    adapter.poll()
    # Slot can be reused only after the previous child has exited and backoff elapsed.
    assert runner.call_count == 2
    replacement.returncode = -9
    adapter.close()


def test_temperature_backoff_after_error():
    clock = [0.0]
    processes = [
        SensorProcess(
            {
                "dedicated": {
                    "raw": None,
                    "source": "hwmon name=pvt / temp2_input",
                    "error": "Sensor read failed (errno 110)",
                }
            }
        )
        for _ in range(2)
    ]
    runner = Mock(side_effect=processes)
    adapter = BpuTemperature(settings(), popen=runner, clock=lambda: clock[0])
    adapter.poll()
    adapter.poll()
    for second in range(1, 30):
        clock[0] = second
        adapter.poll()
    assert runner.call_count == 1
    clock[0] = 30
    adapter.poll()
    adapter.poll()
    assert runner.call_count == 2 and adapter.next_attempt == 90


@pytest.fixture
def ros_env(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    monkeypatch.setenv("ROS_DISTRO", "humble")


def probe(result=None, error=None):
    runner = SimpleNamespace(run=Mock(side_effect=error, return_value=result))
    return Ros2Adapter(True, interval=0, runner=runner), runner


@pytest.mark.parametrize(
    "out,code",
    [
        ("not json", "invalid_json"),
        ("null", "invalid_graph"),
        ('{"nodes":["bad node"],"topics":[]}', "invalid_graph"),
        ('{"nodes":[],"topics":[{"name":"/x","types":[],"publishers":-1}]}', "invalid_graph"),
    ],
)
def test_ros_json_and_schema_diagnostics(ros_env, out, code):
    adapter, _ = probe(SimpleNamespace(stdout=out, stderr="", returncode=0))
    result = adapter.collect()["ros2"]
    assert result["available"]["value"] is None
    assert result["diagnostic"]["value"] == code and result["consecutive_failures"]["value"] == 1


def test_ros_timeout_diagnostic(ros_env):
    adapter, _ = probe(
        error=subprocess.TimeoutExpired(["probe"], 8, stderr=b"\x1b[31mtimeout\nsecret=abc")
    )
    result = adapter.collect()["ros2"]
    assert result["diagnostic"]["value"] == "timeout" and "8 seconds" in result["detail"]["value"]
    assert "abc" not in result["stderr_excerpt"]["value"]


def test_ros_nonzero_exit_and_sanitized_stderr(ros_env, caplog):
    adapter, _ = probe(
        SimpleNamespace(returncode=7, stdout="", stderr="\x1b[31mfailed\n" + "x" * 1000)
    )
    result = adapter.collect()["ros2"]
    assert result["diagnostic"]["value"] == "exit_error" and "status 7" in result["detail"]["value"]
    assert len(result["stderr_excerpt"]["value"]) <= 512
    assert "\x1b" not in caplog.text


def test_ros_slow_success_empty_and_default_deadline(ros_env, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.adapters.ros2.time.monotonic", lambda: clock[0])

    def slow(*args, **kwargs):
        assert kwargs["timeout"] == 8
        clock[0] += 3.394
        return SimpleNamespace(returncode=0, stdout='{"nodes":[],"topics":[]}', stderr="")

    adapter = Ros2Adapter(True, runner=SimpleNamespace(run=slow))
    result = adapter.collect()
    assert result["ros2"]["diagnostic"]["value"] == "success_empty"
    assert result["ros2"]["probe_duration"]["value"] == 3.394
    assert result["ros2"]["available"]["value"] is True
    assert result["cameras"]["topics"][0]["publishers"]["value"] == 0


def test_ros_graph_retained_stale_and_recovers(ros_env):
    adapter, runner = probe(
        SimpleNamespace(returncode=0, stdout='{"nodes":["/mipi_cam"],"topics":[]}', stderr="")
    )
    success = adapter.collect()
    timestamp = success["ros2"]["nodes"]["timestamp"]
    last = success["ros2"]["last_success"]["value"]
    runner.run.side_effect = subprocess.TimeoutExpired(["probe"], 8)
    failed = adapter.collect()
    assert failed["ros2"]["nodes"]["value"] == ["/mipi_cam"]
    assert failed["ros2"]["nodes"]["timestamp"] == timestamp
    assert failed["ros2"]["last_success"]["value"] == last
    assert failed["ros2"]["available"]["value"] is None
    assert freshen(failed, 25)["ros2"]["nodes"]["stale"]
    assert failed["cameras"]["node_present"]["stale"]
    runner.run.side_effect = None
    recovered = adapter.collect()
    assert recovered["ros2"]["available"]["value"] is True
    assert recovered["ros2"]["consecutive_failures"]["value"] == 0
    assert not recovered["ros2"]["nodes"]["stale"]


def test_ros_no_overlapping_probe(ros_env):
    adapter, runner = probe(
        SimpleNamespace(returncode=0, stdout='{"nodes":[],"topics":[]}', stderr="")
    )
    adapter.lock.acquire()
    try:
        adapter.collect()
        runner.run.assert_not_called()
    finally:
        adapter.lock.release()


def test_bounded_command_quarantined_child():
    runner = BoundedCommand()
    runner.process = SimpleNamespace(poll=lambda: None)
    with pytest.raises(CommandBusy):
        runner.run(["/usr/bin/python3", "fixed-probe.py"], 8)


@pytest.mark.parametrize("value", [0.0, 1.9, 30.1, float("inf")])
def test_ros_timeout_config_bounds(value):
    with pytest.raises(ValueError):
        Settings(ros2_probe_timeout_seconds=value)


def test_graph_jpeg_absence_does_not_hide_camera():
    result = graph_result(
        {
            "nodes": ["/mipi_cam"],
            "topics": [
                {"name": "/image_left_raw", "types": ["sensor_msgs/msg/Image"], "publishers": 1}
            ],
        }
    )
    assert result["cameras"]["node_present"]["value"] is True
    assert (
        next(t for t in result["cameras"]["topics"] if t["name"] == "/image_left_raw")[
            "publishers"
        ]["value"]
        == 1
    )
    assert (
        next(t for t in result["cameras"]["topics"] if t["name"] == "/image_combine_jpeg")[
            "publishers"
        ]["value"]
        == 0
    )


def test_cpu_zero_jiffy_core_does_not_erase_valid_overall(monkeypatch, tmp_path):
    from collections import namedtuple

    Cpu = namedtuple("Cpu", "user idle")
    samples = [[Cpu(10, 90), Cpu(20, 80)], [Cpu(10, 90), Cpu(25, 85)]]
    monkeypatch.setattr("app.adapters.hardware.psutil.cpu_times", lambda **kw: samples.pop(0))
    (tmp_path / "stat").write_text("cpu0 10 90\ncpu1 20 80\n")
    adapter = NativeHardware(proc_root=tmp_path)
    adapter.cpu()
    data = adapter.cpu()
    assert data["cores"][0]["value"] is None
    assert data["cores"][1]["value"] == 50 and data["overall"]["value"] == 50


def test_frequency_retains_hz_resolution_without_100mhz_roundup():
    from app.adapters.hardware import normalize_frequency

    assert normalize_frequency("750123456", "Hz") == 750.123456


def test_cpu_reset_remains_unavailable(monkeypatch, tmp_path):
    from collections import namedtuple

    Cpu = namedtuple("Cpu", "user idle")
    samples = [[Cpu(10, 90), Cpu(20, 80)], [Cpu(1, 9), Cpu(25, 85)]]
    monkeypatch.setattr("app.adapters.hardware.psutil.cpu_times", lambda **kw: samples.pop(0))
    (tmp_path / "stat").write_text("cpu0 10 90\ncpu1 20 80\n")
    adapter = NativeHardware(proc_root=tmp_path)
    adapter.cpu()
    assert adapter.cpu()["overall"]["value"] is None


def test_bounded_command_real_timeout_capture_limit_and_recovery():
    import sys
    from app.adapters.bounded_command import OutputLimit

    runner = BoundedCommand()
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run([sys.executable, "-c", "import time; time.sleep(5)"], 0.1)
    assert runner.process is None
    with pytest.raises(OutputLimit):
        runner.run([sys.executable, "-c", 'print("x"*10000)'], 2, max_stdout=128)
    result = runner.run(
        [sys.executable, "-c", 'import sys; print("{}"); sys.stderr.write("x"*10000)'],
        2,
        max_stderr=64,
    )
    assert result.returncode == 0 and result.stdout.strip() == "{}" and len(result.stderr) == 64
