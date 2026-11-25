"""Unified QA preflight failure regressions; never invoke nested test suites."""

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_qa(output, **overrides):
    env = {**os.environ, "RDK_QA_OUTPUT": str(output), **overrides}
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(ROOT / "scripts/qa-full.sh")], env=env, capture_output=True, text=True, timeout=20
    )


def test_required_missing_tool_fails_with_structured_report(tmp_path):
    result = run_qa(tmp_path, RDK_QA_PYTHON="/nonexistent/rdk-python")
    report = json.loads((tmp_path / "qa-report.json").read_text())
    assert result.returncode != 0 and report["result"] == "failed"
    assert report["stages"][0]["required"] and report["stages"][0]["status"] == "failed"
    assert all(stage["status"] == "not_run" for stage in report["stages"][1:])
    assert report["completed_at"] and not report["tests"]


def test_occupied_port_fails_without_stopping_unowned_listener(tmp_path):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 18088))
        listener.listen()
        result = run_qa(tmp_path)
        report = json.loads((tmp_path / "qa-report.json").read_text())
        assert result.returncode != 0 and report["result"] == "failed"
        assert "18088" in report["error"]
        assert listener.getsockname()[1] == 18088


def test_freshness_and_required_browser_count_guards():
    node = shutil.which("node")
    assert node is not None
    subprocess.run([node, str(ROOT / "tests/unit/test_qa_full_checks.mjs")], check=True, timeout=10)
