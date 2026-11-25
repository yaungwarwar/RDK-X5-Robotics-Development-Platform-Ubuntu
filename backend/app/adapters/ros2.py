import json
import copy
import logging
import re
import threading
import os
import subprocess
import time
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from app.models.telemetry import metric, now
from app.adapters.bounded_command import BoundedCommand, CommandBusy, OutputLimit

CAMERA_TOPICS = [
    "/image_left_raw",
    "/image_right_raw",
    "/image_combine_raw",
    "/image_combine_jpeg",
    "/image_left_raw/camera_info",
    "/image_right_raw/camera_info",
    "/image_combine_raw/left/camera_info",
    "/image_combine_raw/right/camera_info",
]


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(max_length=256, pattern=r"^/[a-zA-Z0-9_/]+$")
    types: list[str] = Field(max_length=16)
    publishers: int = Field(ge=0, le=100000)

    @field_validator("types")
    @classmethod
    def types_valid(cls, values):
        import re

        if any(len(v) > 256 or not re.fullmatch(r"[a-zA-Z0-9_/]+", v) for v in values):
            raise ValueError("Invalid ROS message type")
        return values


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nodes: list[str] = Field(max_length=2048)
    topics: list[Topic] = Field(max_length=4096)

    @field_validator("nodes")
    @classmethod
    def nodes_valid(cls, values):
        import re

        if any(len(v) > 256 or not re.fullmatch(r"/[a-zA-Z0-9_/]+", v) for v in values):
            raise ValueError("Invalid ROS node name")
        return values


def graph_result(data=None, reason=None, source="rclpy graph discovery"):
    graph = Graph.model_validate(data).model_dump() if data is not None else None
    ros = {
        "available": metric(True if graph is not None else None, "boolean", source, reason),
        "nodes": metric(graph["nodes"] if graph is not None else None, "nodes", source, reason),
        "topics": metric(graph["topics"] if graph is not None else None, "topics", source, reason),
        "probe_duration": metric(None, "s", source, "Not measured by fixture"),
        "last_success": metric(now() if graph is not None else None, "UTC", source, reason),
        "consecutive_failures": metric(0, "attempts", source),
        "diagnostic": metric(
            "success_empty"
            if graph is not None and not graph["nodes"] and not graph["topics"]
            else "success"
            if graph is not None
            else "not_sampled",
            "state",
            source,
            reason,
        ),
        "detail": metric(reason or "Graph discovered", "text", source),
        "stderr_excerpt": metric(None, "text", source, "No stderr recorded"),
    }
    camera = []
    for name in CAMERA_TOPICS:
        found = next((t for t in graph["topics"] if t["name"] == name), None) if graph else None
        camera.append(
            {
                "name": name,
                "publishers": metric(
                    found["publishers"] if found else (0 if graph else None),
                    "publishers",
                    source,
                    reason,
                ),
            }
        )
    return {
        "ros2": ros,
        "cameras": {
            "node_present": metric(
                "/mipi_cam" in graph["nodes"] if graph else None, "boolean", source, reason
            ),
            "topics": camera,
            "capture": metric(
                None,
                "state",
                "read-only monitor",
                "No capture or image subscriptions are performed",
            ),
        },
    }


def sanitize_stderr(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", (value or "")[-4096:])
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    text = re.sub(
        r"(?i)(password|token|secret|authorization)([=: ]+)[^ ,;]+", r"\1\2[redacted]", text
    )
    return text[-512:]


class Ros2Adapter:
    def __init__(self, enabled=False, interval=10.0, timeout=8.0, runner=None):
        if not isinstance(timeout, (int, float)) or not 2 <= timeout <= 30:
            raise ValueError("ROS2 timeout must be 2–30 seconds")
        self.enabled = enabled
        self.interval = interval
        self.timeout = timeout
        environment = os.environ.copy()
        ros_path = environment.pop("RDK_ROS_PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        if ros_path is not None:
            environment["PYTHONPATH"] = ros_path
        self.runner = runner or BoundedCommand(env=environment)
        self.last = -1e9
        self.cache = graph_result(reason="Discovery not sampled yet")
        self.success = None
        self.last_success = None
        self.failures = 0
        self.lock = threading.Lock()

    def collect(self):
        if not self.lock.acquire(blocking=False):
            return copy.deepcopy(self.cache)
        try:
            if time.monotonic() - self.last < self.interval:
                return copy.deepcopy(self.cache)
            started = time.monotonic()
            duration = None
            excerpt = None
            reason = None
            code = "success"
            result = None
            if not self.enabled:
                code, reason = "disabled", "ROS2 discovery disabled in configuration"
            elif not any(Path(p).is_dir() for p in ["/opt/ros/humble", "/opt/tros/humble"]):
                code, reason = "environment_missing", "ROS2 Humble environment not installed"
            elif os.environ.get("ROS_DISTRO") != "humble":
                code, reason = (
                    "environment_unsourced",
                    "ROS2 Humble environment must be sourced before startup (ROS_DISTRO is not humble)",
                )
            else:
                try:
                    proc = self.runner.run(
                        ["/usr/bin/python3", str(Path(__file__).with_name("ros2_probe.py"))],
                        timeout=self.timeout,
                    )
                    excerpt = sanitize_stderr(proc.stderr)
                    if proc.returncode != 0:
                        code, reason = (
                            "exit_error",
                            f"ROS2 probe exited with status {proc.returncode}",
                        )
                    else:
                        try:
                            decoded = json.loads(proc.stdout)
                        except (json.JSONDecodeError, UnicodeError):
                            code, reason = (
                                "invalid_json",
                                "ROS2 probe stdout is not valid UTF-8 JSON",
                            )
                        else:
                            try:
                                result = graph_result(Graph.model_validate(decoded).model_dump())
                            except ValidationError:
                                code, reason = (
                                    "invalid_graph",
                                    "ROS2 graph schema validation failed",
                                )
                except subprocess.TimeoutExpired as error:
                    code, reason = "timeout", f"ROS2 probe timed out after {self.timeout:g} seconds"
                    excerpt = sanitize_stderr(error.stderr)
                except CommandBusy:
                    code, reason = (
                        "probe_unreaped",
                        "Previous ROS2 probe has not exited; replacement deferred",
                    )
                except OutputLimit:
                    code, reason = "output_limit", "ROS2 probe output exceeded the graph size limit"
                except UnicodeError:
                    code, reason = "invalid_json", "ROS2 probe stdout is not valid UTF-8 JSON"
                except OSError as error:
                    code, reason = (
                        "spawn_error",
                        f"ROS2 probe could not start (errno {error.errno})",
                    )
                duration = round(time.monotonic() - started, 4)
            self.last = time.monotonic()
            if result is not None:
                self.last_success = now()
                self.failures = 0
                if not result["ros2"]["nodes"]["value"] and not result["ros2"]["topics"]["value"]:
                    code = "success_empty"
                self.success = copy.deepcopy(result)
            else:
                if code != "disabled":
                    self.failures += 1
                result = (
                    copy.deepcopy(self.success)
                    if self.success is not None
                    else graph_result(reason=reason)
                )
                result["ros2"]["available"] = metric(
                    None, "boolean", "rclpy graph discovery", reason
                )
                if self.success is not None:

                    def retained(value):
                        if isinstance(value, dict):
                            if "unit" in value and "timestamp" in value:
                                value.update(
                                    stale=True, reason="Retained after discovery failure: " + reason
                                )
                            else:
                                for child in value.values():
                                    retained(child)
                        elif isinstance(value, list):
                            for child in value:
                                retained(child)

                    for key in ["nodes", "topics"]:
                        retained(result["ros2"][key])
                    retained(result["cameras"])
            source = "rclpy probe diagnostics"
            result["ros2"].update(
                probe_duration=metric(
                    duration,
                    "s",
                    source,
                    None if duration is not None else "No subprocess executed",
                ),
                last_success=metric(
                    self.last_success,
                    "UTC",
                    source,
                    None if self.last_success else "No successful discovery yet",
                ),
                consecutive_failures=metric(self.failures, "attempts", source),
                diagnostic=metric(code, "state", source),
                detail=metric(
                    reason
                    or (
                        "Successfully discovered an empty graph"
                        if code == "success_empty"
                        else "Graph discovered"
                    ),
                    "text",
                    source,
                ),
                stderr_excerpt=metric(
                    excerpt or None, "text", source, None if excerpt else "No stderr recorded"
                ),
            )
            if excerpt:
                logging.getLogger(__name__).warning("ROS2 probe %s stderr: %s", code, excerpt)
            self.cache = result
            return copy.deepcopy(self.cache)
        finally:
            self.lock.release()
