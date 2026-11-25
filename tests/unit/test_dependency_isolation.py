import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.adapters.ros2 import Ros2Adapter
from upgrade import Transaction, UpgradeError, run, save


def test_upgrade_python_commands_ignore_pythonpath_and_pythonhome(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path))
    # Exercise the same system interpreter used to create the release venv.
    output = run(
        [
            "/usr/bin/python3",
            "-c",
            "import os; print(os.getenv('PYTHONPATH'), os.getenv('PYTHONHOME'))",
        ]
    )
    assert output.strip() == "None None"


def test_ros_probe_receives_saved_ros_path_only(monkeypatch):
    monkeypatch.setenv("RDK_ROS_PYTHONPATH", "/opt/tros/lib/python3.10/site-packages")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PYTHONHOME", "/bad")
    env = Ros2Adapter().runner.env
    assert env["PYTHONPATH"] == "/opt/tros/lib/python3.10/site-packages"
    assert "PYTHONHOME" not in env
    assert "RDK_ROS_PYTHONPATH" not in env


def test_failed_command_exposes_conflict_and_redacts_secret():
    with pytest.raises(UpgradeError) as caught:
        run(
            [
                "/usr/bin/python3",
                "-c",
                "import sys; print('fixture requires missing-package'); print('token=secret-value', file=sys.stderr); sys.exit(1)",
            ]
        )
    assert "fixture requires missing-package" in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_isolated_pip_check_rejects_injected_broken_distribution(tmp_path):
    vendor = tmp_path / "vendor"
    metadata = vendor / "rdk_fixture-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: rdk-fixture\nVersion: 1.0\n"
        "Requires-Dist: rdk-missing-fixture>=1\n"
    )
    env = {**os.environ, "PYTHONPATH": str(vendor)}
    dirty = subprocess.run(
        [sys.executable, "-m", "pip", "check"], env=env, capture_output=True, text=True
    )
    assert dirty.returncode != 0
    assert "rdk-missing-fixture" in dirty.stdout
    clean = subprocess.run(
        [sys.executable, "-I", "-m", "pip", "check"], env=env, capture_output=True, text=True
    )
    assert "rdk-missing-fixture" not in clean.stdout


def test_actual_zope_setuptools_conflict_is_isolated(tmp_path):
    external = tmp_path / "vendor"
    for name, version, requirement in [
        ("zope_event", "5.1.1", "Requires-Dist: setuptools>=75.8.2\n"),
        ("setuptools", "59.6.0", ""),
    ]:
        metadata = external / f"{name}-{version}.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\n"
            f"Version: {version}\n{requirement}"
        )
    venv = tmp_path / "app-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    assert "include-system-site-packages = false" in (venv / "pyvenv.cfg").read_text()
    python = str(venv / "bin/python")
    env = {**os.environ, "PYTHONPATH": str(external)}
    env.pop("PYTHONHOME", None)
    dirty = subprocess.run([python, "-m", "pip", "check"], env=env, capture_output=True, text=True)
    assert dirty.returncode == 1
    assert "zope-event 5.1.1" in dirty.stdout
    assert "setuptools 59.6.0" in dirty.stdout
    env.pop("PYTHONPATH")
    clean = subprocess.run([python, "-m", "pip", "check"], env=env, capture_output=True, text=True)
    assert clean.returncode == 0, clean.stdout + clean.stderr


def test_subprocess_log_is_private_bounded_and_redacted(tmp_path):
    import json

    log = tmp_path / "command.json"
    code = "import sys; print('zope-event requires setuptools>=75.8.2'); print('token=secret-value', file=sys.stderr); print('x'*2000000); sys.exit(7)"
    with pytest.raises(UpgradeError, match="zope-event requires setuptools") as error:
        run(
            [sys.executable, "-c", code, "--password", "hunter2"],
            log_path=log,
            operation="DEPENDENCIES_VALIDATED",
        )
    data = json.loads(log.read_text())
    assert data["operation"] == "DEPENDENCIES_VALIDATED"
    assert data["exit_status"] == 7 and data["duration_seconds"] >= 0
    assert data["started_at"] and data["ended_at"]
    assert data["truncated"]["stdout"] and len(data["stdout"]) <= 8192
    assert "hunter2" not in log.read_text() and "secret-value" not in log.read_text()
    assert "secret-value" not in str(error.value)
    assert log.stat().st_mode & 0o777 == 0o600


def test_subprocess_timeout_is_logged(tmp_path):
    import json

    log = tmp_path / "timeout.json"
    with pytest.raises(UpgradeError, match="Timed out"):
        run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1, log_path=log)
    data = json.loads(log.read_text())
    assert "Timed out" in data["failure"]
    assert data["duration_seconds"] >= 0.1


def test_journal_atomic_replace_preserves_old_file_on_failure(tmp_path, monkeypatch):
    journal = tmp_path / "journal.json"
    save(journal, {"state": "NEW"})
    old = journal.read_bytes()

    def fail(*args):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("upgrade.os.replace", fail)
    with pytest.raises(OSError):
        save(journal, {"state": "PREPARED"})
    assert journal.read_bytes() == old
    assert list(tmp_path.iterdir()) == [journal]


def test_transaction_command_references_private_log(tmp_path):
    import json

    logs = tmp_path / "logs"
    logs.mkdir(mode=0o700)
    task = Transaction(installed=tmp_path)
    task.preparation_journal = tmp_path / "preparation.json"
    task.preparation_state = {"state": "VENV_CREATED", "next_stage": "DEPENDENCIES_INSTALLED"}
    assert task.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    state = json.loads(task.preparation_journal.read_text())
    log = json.loads(Path(state["last_log"]).read_text())
    assert log["operation"] == "DEPENDENCIES_INSTALLED"
    assert log["stdout"].strip() == "ok"
    assert Path(state["last_log"]).stat().st_mode & 0o777 == 0o600
