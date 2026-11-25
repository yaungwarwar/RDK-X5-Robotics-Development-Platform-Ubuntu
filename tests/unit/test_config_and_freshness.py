from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from app.config.settings import Settings, load_settings
from app.models.telemetry import freshen, metric
from app.collectors.monitor import Monitor
from app.adapters.mock import MockHardware, MockRos2


@pytest.mark.parametrize(
    "config",
    [
        {"mode": "rdk;touch /tmp/x"},
        {"interval_seconds": 0.0},
        {"interval_seconds": "1"},
        {"history_size": 100000},
        {"allowed_hosts": ["*"]},
        {"allowed_hosts": ["localhost; id"]},
        {"allowed_origins": ["http://*.example.com"]},
        {"allowed_origins": ["http://localhost:8088/path"]},
        {"allowed_origins": ["http://user:pass@localhost"]},
        {"allowed_origins": ["http://localhost:99999"]},
        {"storage_paths": ["/;touch /tmp/injected"]},
        {"storage_paths": ["../../etc"]},
        {"storage_paths": ["/tmp/../etc"]},
        {"command": "id"},
        {"interval_seconds": 4.0, "stale_after_seconds": 5.0},
    ],
)
def test_invalid_config_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        Settings(**config)


def test_freshness_preserves_value_and_sample_time():
    reading = metric(47, "°C", "test")
    reading["timestamp"] = (datetime.now(timezone.utc) - timedelta(seconds=9)).isoformat()
    updated = freshen(reading, 5)
    assert updated["stale"] and updated["age_seconds"] >= 9
    assert updated["timestamp"] == reading["timestamp"] and updated["value"] == 47
    assert not reading["stale"]


def test_central_history_bounded_and_collector_failure_retains_sample():
    h = MockHardware()
    m = Monitor(h, MockRos2(), Settings(mode="mock", history_size=3))
    m.sample_auxiliary()
    for _ in range(8):
        m.sample()
    assert len(m.history) == 3 and m.sequence == 8
    original = m.latest["timestamp"]

    def fail():
        raise OSError("unreadable procfs")

    h.collect = fail
    m.sample()
    assert m.latest["timestamp"] == original and m.snapshot()["collector_error"]
    m.executor.shutdown()


def test_config_files_load():
    for name in ["mock", "default", "rdkx5"]:
        s = load_settings(f"config/{name}.yaml")
        assert s.interval_seconds == 1.0
