import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.adapters import ros2_probe
from app.adapters.bounded_command import BoundedCommand
from app.adapters.ros2 import sanitize_stderr


def test_probe_disables_external_logging_and_discovers_graph(monkeypatch, capsys):
    node = Mock()
    node.get_node_names_and_namespaces.return_value = [("camera", "/")]
    node.get_topic_names_and_types.return_value = [("/image", ["sensor_msgs/msg/Image"])]
    node.count_publishers.return_value = 1
    ros = SimpleNamespace(
        init=Mock(), create_node=Mock(return_value=node), spin_once=Mock(), shutdown=Mock()
    )
    monkeypatch.setitem(sys.modules, "rclpy", ros)
    clock = iter([0, 2])
    monkeypatch.setattr(ros2_probe.time, "monotonic", lambda: next(clock))
    ros2_probe.main()
    ros.init.assert_called_once_with(args=["--ros-args", "--disable-external-lib-logs"])
    node.destroy_node.assert_called_once()
    ros.shutdown.assert_called_once()
    result = json.loads(capsys.readouterr().out)
    assert result["nodes"] == ["/camera"] and result["topics"][0]["publishers"] == 1


def test_probe_propagates_discovery_error_and_cleans_up(monkeypatch):
    node = Mock()
    node.get_node_names_and_namespaces.side_effect = RuntimeError("discovery failed")
    ros = SimpleNamespace(
        init=Mock(), create_node=Mock(return_value=node), spin_once=Mock(), shutdown=Mock()
    )
    monkeypatch.setitem(sys.modules, "rclpy", ros)
    clock = iter([0, 2])
    monkeypatch.setattr(ros2_probe.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError, match="discovery failed"):
        ros2_probe.main()
    node.destroy_node.assert_called_once()
    ros.shutdown.assert_called_once()


def test_probe_init_error_is_not_suppressed(monkeypatch):
    ros = SimpleNamespace(init=Mock(side_effect=RuntimeError("init failed")))
    monkeypatch.setitem(sys.modules, "rclpy", ros)
    with pytest.raises(RuntimeError, match="init failed"):
        ros2_probe.main()


def test_stderr_tail_is_bounded_and_keeps_exception_redacted():
    runner = BoundedCommand()
    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x'*9000+'\\nRuntimeError: token=supersecret\\n'); sys.exit(1)",
        ],
        timeout=5,
    )
    assert result.returncode == 1 and len(result.stderr.encode()) <= 4096
    excerpt = sanitize_stderr(result.stderr)
    assert len(excerpt) <= 512 and "RuntimeError:" in excerpt
    assert "supersecret" not in excerpt and "[redacted]" in excerpt
