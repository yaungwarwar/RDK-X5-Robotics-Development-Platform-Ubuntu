import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import cgroup_compat as compat
from upgrade import Transaction, UpgradeError, target_guard


INFO = {
    "CgroupVersion": "2",
    "CgroupDriver": "systemd",
    "MemoryLimit": True,
    "PidsLimit": True,
    "CpuCfsQuota": True,
    "SecurityOptions": [],
}
MOUNT = "1 0 0:28 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"


def hierarchy(root, cpu=False):
    base = root / "sys/fs/cgroup"
    parent = base / "system.slice"
    parent.mkdir(parents=True)
    for directory in [base, parent]:
        (directory / "cgroup.controllers").write_text(
            "cpuset cpu io memory pids" if cpu or directory == base else "cpuset io memory pids"
        )
        (directory / "cgroup.subtree_control").write_text(
            "cpu memory pids" if cpu else "memory pids"
        )
    for file in ["memory.max", "pids.max"] + (["cpu.max"] if cpu else []):
        (parent / file).write_text("max")
    return parent


def report(cpu=False):
    return {
        "controllers": {"cpu": cpu, "memory": True, "pids": True},
        "warnings": [],
        "parent": "/system.slice",
        "cgroup_version": "2",
        "cgroup_driver": "systemd",
    }


def compose(root, cpus=None):
    frontend = root / "frontend"
    frontend.mkdir(exist_ok=True, parents=True)
    nginx = frontend / "nginx.conf"
    nginx.write_text("events {}\nhttp { server {\n listen 127.0.0.1:8088 default_server;\n} }\n")
    service = {
        "image": "rdk-control-center-dashboard:0.1.2",
        "build": {"context": str(frontend)},
        "network_mode": "host",
        "user": "101:101",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": 100663296,
        "pids_limit": 64,
        "volumes": [
            {
                "type": "bind",
                "source": str(nginx),
                "target": "/etc/nginx/nginx.conf",
                "read_only": True,
            }
        ],
    }
    if cpus is not None:
        service["cpus"] = cpus
    return {"name": "rdk-control-center", "services": {"dashboard": service}}


def test_missing_cpu_controller_despite_kernel_support(tmp_path):
    hierarchy(tmp_path)
    # Root advertises cpu but does not propagate it to system.slice; compile flags are irrelevant.
    r = compat.assess(INFO, MOUNT, "/system.slice", tmp_path)
    assert not r["controllers"]["cpu"]
    assert "RDK-COMPAT-001" in r["warnings"][0] and "unproven" in r["warnings"][0]
    assert r["controllers"]["memory"] and r["controllers"]["pids"]


def test_effective_cpu_controller_and_leaf(tmp_path):
    parent = hierarchy(tmp_path, True)
    leaf = parent / "docker-test.scope"
    leaf.mkdir()
    for file in ["memory.max", "pids.max", "cpu.max"]:
        (leaf / file).write_text("max")
    paths = {key: "/system.slice/docker-test.scope" for key in ["cpu", "memory", "pids"]}
    assert compat.assess(INFO, MOUNT, "/system.slice", tmp_path, paths)["controllers"]["cpu"]
    (leaf / "cpu.max").unlink()
    assert not compat.assess(INFO, MOUNT, "/system.slice", tmp_path, paths)["controllers"]["cpu"]


@pytest.mark.parametrize("file", ["memory.max", "pids.max"])
def test_missing_required_isolation_fails_closed(tmp_path, file):
    parent = hierarchy(tmp_path)
    (parent / file).unlink()
    with pytest.raises(compat.CompatibilityError, match="Required memory/PID"):
        compat.assess(INFO, MOUNT, "/system.slice", tmp_path)


def test_docker_reports_missing_required_limit(tmp_path):
    hierarchy(tmp_path)
    with pytest.raises(compat.CompatibilityError):
        compat.assess({**INFO, "PidsLimit": False}, MOUNT, "/system.slice", tmp_path)


def test_v1_cgroup_driver_detection(tmp_path):
    mounts = []
    for i, (controller, file) in enumerate(
        [("cpu", "cpu.cfs_quota_us"), ("memory", "memory.limit_in_bytes"), ("pids", "pids.max")]
    ):
        path = tmp_path / f"sys/fs/cgroup/{controller}/docker"
        path.mkdir(parents=True)
        (path / file).write_text("100")
        mounts.append(
            f"{i + 1} 0 0:2 / /sys/fs/cgroup/{controller} rw - cgroup cgroup rw,{controller}"
        )
    r = compat.assess(
        {**INFO, "CgroupVersion": "1", "CgroupDriver": "cgroupfs"},
        "\n".join(mounts),
        "/docker",
        tmp_path,
    )
    assert all(r["controllers"].values())


def test_generation_preserves_limits_workaround_and_administrator_file(tmp_path):
    old = compose(tmp_path, 0.5)
    original = copy.deepcopy(old)
    compatible = compat.generate(old, report(False))
    service = compatible["services"]["dashboard"]
    assert "cpus" not in service
    assert service["mem_limit"] == 100663296 and service["pids_limit"] == 64
    assert service["user"] == "101:101" and service["read_only"] and service["cap_drop"] == ["ALL"]
    assert old == original
    bundle = tmp_path / "bundle"
    config = compat.write_bundle(bundle, compatible, report(False))
    assert json.loads(config.read_text()) == compatible
    with pytest.raises(FileExistsError):
        compat.write_bundle(bundle, compatible, report(False))
    assert (
        "cpus" not in compat.generate(compatible, report(True), "preserve")["services"]["dashboard"]
    )
    assert compat.generate(compatible, report(True), "auto")["services"]["dashboard"]["cpus"] == 0.5


@pytest.mark.parametrize(
    "field,value",
    [
        ("privileged", True),
        ("user", "0:0"),
        ("read_only", False),
        ("mem_limit", 0),
        ("pids_limit", 0),
        ("devices", ["/dev/bpu"]),
        ("ports", ["8088:8088"]),
        ("cap_add", ["SYS_ADMIN"]),
    ],
)
def test_generator_rejects_security_regression(tmp_path, field, value):
    config = compose(tmp_path)
    config["services"]["dashboard"][field] = value
    with pytest.raises(compat.CompatibilityError):
        compat.generate(config, report())


def test_generator_rejects_lan_binding_in_upgrade(tmp_path):
    config = compose(tmp_path)
    (tmp_path / "frontend/nginx.conf").write_text("listen 0.0.0.0:8088;")
    with pytest.raises(compat.CompatibilityError):
        compat.generate(config, report())


def test_frontend_release_metadata_matches_source_version():
    root = Path(__file__).resolve().parents[2]
    package = json.loads((root / "frontend/package.json").read_text())
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    assert (root / "VERSION").read_text().strip() == package["version"] == "0.1.3"
    assert lock["version"] == lock["packages"][""]["version"] == package["version"]
    source = (root / "frontend/src/main.tsx").read_text()
    assert "version as releaseVersion" in source
    assert "v0.1.1" not in source


class FakeTarget:
    def __init__(self, tmp_path):
        self.installed = tmp_path / "installed"
        self.installed.mkdir()
        self.release = tmp_path / "staging"
        self.release.mkdir()
        self.backup = tmp_path / "backup"
        self.calls = []
        for root, version in [(self.installed, "0.1.2"), (self.release, "0.1.3")]:
            (root / "VERSION").write_text(version)
            (root / "config").mkdir()
            (root / "config/rdkx5.yaml").write_text('{"mode":"native"}')
            (root / "backend").mkdir()
            (root / "backend/requirements.txt").write_text("fastapi==0.162.5")
        (self.installed / ".venv/bin").mkdir(parents=True)
        (self.installed / ".venv/bin/python").write_text("old python")
        self.config = compose(self.installed)
        base = copy.deepcopy(self.config)
        base["services"]["dashboard"]["cpus"] = 0.5
        (self.installed / "compose.yaml").write_text(json.dumps(base))
        deployment = self.installed / ".deployment"
        bundle = deployment / "v0.1.2-existing"
        bundle.mkdir(parents=True)
        (deployment / "active.json").write_text(
            json.dumps({"compose": ".deployment/v0.1.2-existing/compose.compat.json"})
        )
        (bundle / "compose.compat.json").write_text(json.dumps(self.config))
        compose(self.release)
        self.unit = tmp_path / "units/rdk-control-center.service"
        self.unit.parent.mkdir()
        self.unit.write_text(
            f"[Service]\nUser=sunrise\nWorkingDirectory={self.installed}\nPrivateTmp=true\nProtectSystem=strict\n"
        )
        self.container = {
            "State": {"Status": "running", "Pid": 123},
            "Image": "sha256:old-image",
            "Config": {"User": "101:101"},
            "HostConfig": {
                "NetworkMode": "host",
                "Privileged": False,
                "ReadonlyRootfs": True,
                "Devices": [],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Memory": 100663296,
                "PidsLimit": 64,
                "NanoCpus": 0,
                "CpuQuota": 0,
            },
        }
        self.health = Mock()
        self.task = Transaction(
            self.installed, self.unit, self.run, lambda **kw: report(False), self.health
        )

    def run(self, args, timeout=120):
        self.calls.append(args)
        if args[:3] == ["docker", "context", "inspect"]:
            return json.dumps("unix:///var/run/docker.sock")
        if args[:3] == ["docker", "compose", "-p"] and args[-2:] == ["--format", "json"]:
            return json.dumps(self.config)
        if args[:3] == ["docker", "ps", "-q"]:
            return "dashboard-id"
        if args[:2] == ["docker", "inspect"]:
            return json.dumps([self.container])
        if args[:3] == ["/usr/bin/systemctl", "is-active", "rdk-control-center.service"]:
            return "active"
        if "--property=DropInPaths" in args:
            return ""
        if "--property=Environment" in args:
            return f"RDK_CONFIG={self.installed}/config/rdkx5.yaml"
        if "--property=User" in args:
            return "sunrise"
        if args[:3] == ["docker", "image", "save"]:
            Path(args[4]).write_bytes(b"old-image-backup")
        if args[:3] == ["/usr/bin/python3", "-m", "venv"]:
            path = Path(args[-1]) / "bin"
            path.mkdir(parents=True)
            (path / "python").write_text("new python")
        return ""


@pytest.fixture
def target(tmp_path, monkeypatch):
    monkeypatch.setattr("upgrade.shutil.disk_usage", lambda _: SimpleNamespace(free=10**12))
    return FakeTarget(tmp_path)


def test_upgrade_prepare_preserves_running_release_and_venv(target):
    journal = target.task.prepare(target.release, target.backup)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert (target.backup / "source-and-venv/.venv/bin/python").read_text() == "old python"
    assert (target.backup / "frontend-image.tar").is_file()
    assert not any(call[0] == "sudo" for call in target.calls)
    manifest = json.loads(journal.read_text())
    state = json.loads((target.backup / "preparation.json").read_text())
    assert manifest["source_version"] == state["source_version"] == "0.1.2"
    assert manifest["target_version"] == state["target_version"] == "0.1.3"
    assert manifest["activation_health_version"] == "0.1.3"
    assert manifest["rollback_health_version"] == "0.1.2"
    assert manifest["old_image_id"] == "sha256:old-image"
    assert manifest["old_image_tag"] == "rdk-control-center-dashboard:0.1.2"
    assert manifest["new_image_tag"] == "rdk-control-center-dashboard:0.1.3"
    assert state["staged_hashes"] == manifest["staged_hashes"]
    service = json.loads((target.release / manifest["new_compose"]).read_text())["services"][
        "dashboard"
    ]
    assert (
        "cpus" not in service and service["mem_limit"] == 100663296 and service["pids_limit"] == 64
    )
    assert service["image"] == "rdk-control-center-dashboard:0.1.3"
    active = target.installed / ".deployment/v0.1.2-existing/compose.compat.json"
    assert any(str(active) in call for call in target.calls)
    assert (
        json.loads((target.backup / "compose.previous.json").read_text())["services"]["dashboard"][
            "image"
        ]
        == "rdk-control-center-dashboard:0.1.2"
    )
    assert json.loads((target.release / "config/rdkx5.yaml").read_text())["mode"] == "native"


def test_failed_pip_check_records_stage_and_preserves_running_installation(target):
    original_run = target.task.run

    def fail_check(args, timeout=120):
        if args[-3:] == ["-m", "pip", "check"]:
            raise UpgradeError("fixture dependency conflict")
        return original_run(args, timeout)

    target.task.run = fail_check
    with pytest.raises(UpgradeError, match="fixture dependency conflict"):
        target.task.prepare(target.release, target.backup)
    state = json.loads((target.backup / "preparation.json").read_text())
    assert state["state"] == "FAILED"
    assert state["last_successful_stage"] == "DEPENDENCIES_INSTALLED"
    assert state["failed_stage"] == "DEPENDENCIES_VALIDATED"
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert (target.backup / "source-and-venv/.venv/bin/python").is_file()
    assert not (target.backup / "transaction.json").exists()
    assert (target.backup / "preparation.json").stat().st_mode & 0o777 == 0o600


def test_apply_rejects_interrupted_preparation(target):
    journal = target.task.prepare(target.release, target.backup)
    state_path = target.backup / "preparation.json"
    state = json.loads(state_path.read_text())
    state["state"] = "IMAGE_BUILT"
    state_path.write_text(json.dumps(state))
    with pytest.raises(UpgradeError, match="did not complete"):
        target.task.apply(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert not any(call[0] == "sudo" for call in target.calls)


def test_activation_and_rollback_record_states(target):
    journal = target.task.prepare(target.release, target.backup)
    target.task.apply(journal)
    state_path = target.backup / "preparation.json"
    assert json.loads(state_path.read_text())["state"] == "ACTIVE"
    target.task.rollback(journal)
    assert json.loads(state_path.read_text())["state"] == "ROLLED_BACK"


@pytest.mark.parametrize(
    "match, expected",
    [
        (
            lambda a: a[-3:] == ["-m", "pip", "install"] or "install" in a and "pip" in a,
            "DEPENDENCIES_INSTALLED",
        ),
        (lambda a: a[-3:] == ["-m", "pip", "check"], "DEPENDENCIES_VALIDATED"),
        (lambda a: a[:2] == ["docker", "build"], "IMAGE_BUILT"),
    ],
)
def test_failed_prepare_stages_keep_running_installation(target, match, expected):
    original = target.task.run

    def fail(args, timeout=120):
        if match(args):
            raise UpgradeError("simulated subprocess failure")
        return original(args, timeout)

    target.task.run = fail
    with pytest.raises(UpgradeError, match="simulated subprocess"):
        target.task.prepare(target.release, target.backup)
    state = json.loads((target.backup / "preparation.json").read_text())
    assert state["state"] == "FAILED" and state["failed_stage"] == expected
    assert state["transaction_id"] and state["timestamp"] and state["log_directory"]
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert not (target.backup / "transaction.json").exists()


def test_interrupted_backup_and_read_only_inspection(target, monkeypatch):
    from upgrade import inspect_transaction

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("upgrade.shutil.copytree", interrupt)
    with pytest.raises(KeyboardInterrupt):
        target.task.prepare(target.release, target.backup)
    journal = target.backup / "preparation.json"
    before = journal.read_bytes(), journal.stat().st_mtime_ns
    result = inspect_transaction(target.backup)
    assert result["classification"] == "interrupted preparation"
    assert result["transaction"]["state"] == "BACKUP_STARTED"
    assert (journal.read_bytes(), journal.stat().st_mtime_ns) == before
    assert (target.installed / "VERSION").read_text() == "0.1.2"


@pytest.mark.parametrize(
    "state, classification",
    [
        ("FAILED", "failed"),
        ("PREPARED", "prepared"),
        ("ACTIVE", "active"),
        ("ROLLED_BACK", "rolled_back"),
        ("ACTIVATING", "interrupted activation or rollback"),
        ("VENV_CREATED", "interrupted preparation"),
    ],
)
def test_inspection_classifies_without_writing(tmp_path, state, classification):
    from upgrade import inspect_transaction, save

    journal = tmp_path / "preparation.json"
    save(journal, {"state": state})
    original = journal.read_bytes(), journal.stat().st_mtime_ns
    assert inspect_transaction(journal)["classification"] == classification
    assert (journal.read_bytes(), journal.stat().st_mtime_ns) == original


def test_preparation_records_ordered_transitions(target, monkeypatch):
    from upgrade import save

    states = []

    def record(path, data):
        if path.name == "preparation.json" and (not states or states[-1] != data["state"]):
            states.append(data["state"])
        return save(path, data)

    monkeypatch.setattr("upgrade.save", record)
    target.task.prepare(target.release, target.backup)
    assert states == [
        "NEW",
        "PREFLIGHT_PASSED",
        "BACKUP_STARTED",
        "BACKUP_COMPLETED",
        "VENV_CREATED",
        "DEPENDENCIES_INSTALLED",
        "DEPENDENCIES_VALIDATED",
        "CONFIG_VALIDATED",
        "COMPATIBILITY_GENERATED",
        "IMAGE_BUILT",
        "PREPARED",
    ]
    assert target.backup.stat().st_mode & 0o777 == 0o700
    assert (target.backup / "logs").stat().st_mode & 0o777 == 0o700


def test_configuration_validation_failure_recorded(target):
    original = target.task.run

    def fail(args, timeout=120):
        if "-c" in args and any("load_settings" in arg for arg in args):
            raise UpgradeError("invalid configuration")
        return original(args, timeout)

    target.task.run = fail
    with pytest.raises(UpgradeError, match="invalid configuration"):
        target.task.prepare(target.release, target.backup)
    state = json.loads((target.backup / "preparation.json").read_text())
    assert state["failed_stage"] == "CONFIG_VALIDATED"
    assert state["last_successful_stage"] == "DEPENDENCIES_VALIDATED"


def test_compatibility_failure_recorded(target, monkeypatch):
    original = compat.generate
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise compat.CompatibilityError("compatibility failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(compat, "generate", fail_second)
    with pytest.raises(compat.CompatibilityError, match="compatibility failure"):
        target.task.prepare(target.release, target.backup)
    state = json.loads((target.backup / "preparation.json").read_text())
    assert state["failed_stage"] == "COMPATIBILITY_GENERATED"


def test_rollback_failure_is_reported_and_recorded(target):
    journal = target.task.prepare(target.release, target.backup)
    original = target.task.run
    stops = 0

    def fail_second_stop(args, timeout=120):
        nonlocal stops
        if args[:3] == ["sudo", "/usr/bin/systemctl", "stop"]:
            stops += 1
            if stops == 2:
                raise UpgradeError("rollback stop failed")
        return original(args, timeout)

    target.task.run = fail_second_stop
    target.task.health = lambda version: (_ for _ in ()).throw(UpgradeError("health failure"))
    with pytest.raises(UpgradeError, match="automatic rollback also failed"):
        target.task.apply(journal)
    state = json.loads((target.backup / "preparation.json").read_text())
    assert state["state"] == "FAILED" and state["failed_stage"] == "ROLLING_BACK"
    assert "rollback stop failed" in state["failure_reason"]


def test_upgrade_apply_and_explicit_rollback_restore_original(target):
    journal = target.task.prepare(target.release, target.backup)
    unit = target.unit.read_bytes()
    target.task.apply(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.3"
    assert json.loads(journal.read_text())["phase"] == "complete"
    target.task.rollback(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert (target.installed / ".venv/bin/python").read_text() == "old python"
    assert target.unit.read_bytes() == unit
    assert json.loads(journal.read_text())["phase"] == "rolled_back"
    target.task.rollback(journal)  # idempotent completion


def test_upgrade_health_failure_rolls_back(target):
    journal = target.task.prepare(target.release, target.backup)

    def check(version):
        if version == "0.1.3":
            raise UpgradeError("failed health")

    target.task.health = check
    with pytest.raises(UpgradeError, match="failed health"):
        target.task.apply(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert json.loads(journal.read_text())["phase"] == "rolled_back"


def test_upgrade_preflight_rejects_overlay_and_wrong_version(target):
    with pytest.raises(UpgradeError):
        target.task.preflight(target.installed)
    (target.release / "VERSION").write_text("0.1.2")
    with pytest.raises(UpgradeError):
        target.task.preflight(target.release)


@pytest.mark.parametrize("version", ["0.1.2", "0.1.1", "0.2.0"])
def test_incorrect_staged_release_version_rejected(target, version):
    (target.release / "VERSION").write_text(version)
    with pytest.raises(UpgradeError, match="0.1.3"):
        target.task.preflight(target.release)


@pytest.mark.parametrize("version", ["0.1.0", "0.1.3", "0.0.9"])
def test_unsupported_installed_versions_rejected(target, version):
    (target.installed / "VERSION").write_text(version)
    with pytest.raises(UpgradeError, match="0.1.2"):
        target.task.preflight(target.release)


@pytest.mark.parametrize(
    "field",
    [
        "source_version",
        "target_version",
        "activation_health_version",
        "rollback_health_version",
        "new_image_tag",
        "old_image_id",
        "compatibility_hash",
    ],
)
def test_inconsistent_transaction_metadata_refuses_activation(target, field):
    journal = target.task.prepare(target.release, target.backup)
    data = json.loads(journal.read_text())
    data[field] = "incorrect"
    journal.write_text(json.dumps(data))
    with pytest.raises(UpgradeError):
        target.task.apply(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert not any(call[0] == "sudo" for call in target.calls)


def test_failed_previous_release_artifacts_do_not_interfere(target):
    old_stage = target.release.parent / "rdk-platform-0.1.1"
    old_backup = target.backup.parent / "before-0.1.1"
    old_stage.mkdir()
    old_backup.mkdir()
    (old_stage / "partial-venv").write_text("retain")
    (old_backup / "partial-backup").write_text("retain")
    previous = target.backup.parent / "before-0.1.2"
    previous.mkdir()
    (previous / "transaction.json").write_text("original transaction")
    journal = target.task.prepare(target.release, target.backup)
    target.task.apply(journal)
    target.task.rollback(journal)
    assert (old_stage / "partial-venv").read_text() == "retain"
    assert (old_backup / "partial-backup").read_text() == "retain"
    assert (previous / "transaction.json").read_text() == "original transaction"


def test_base_compose_is_rejected_if_generated_deployment_is_active(target):
    with pytest.raises(UpgradeError, match="active generated deployment"):
        target.task.prepare(target.release, target.backup, [target.installed / "compose.yaml"])
    assert (target.installed / "VERSION").read_text() == "0.1.2"


@pytest.mark.parametrize("compose", ["/etc/passwd", "../../outside.json", "missing.json"])
def test_invalid_active_deployment_is_rejected(target, compose):
    (target.installed / ".deployment/active.json").write_text(json.dumps({"compose": compose}))
    with pytest.raises(UpgradeError, match="Invalid or missing active deployment"):
        target.task.prepare(target.release, target.backup)
    assert (target.installed / "VERSION").read_text() == "0.1.2"
    assert not any(call[0] == "sudo" for call in target.calls)


def test_changed_active_marker_refuses_activation(target):
    journal = target.task.prepare(target.release, target.backup)
    (target.installed / ".deployment/active.json").write_text('{"compose":"other.json"}')
    with pytest.raises(UpgradeError, match="config changed"):
        target.task.apply(journal)
    assert not any(call[0] == "sudo" for call in target.calls)


def test_upgrade_refuses_changed_admin_config_before_stop(target):
    journal = target.task.prepare(target.release, target.backup)
    (target.installed / "config/rdkx5.yaml").write_text('{"mode":"native","history_size":100}')
    with pytest.raises(UpgradeError, match="config changed"):
        target.task.apply(journal)
    assert not any(c[0] == "sudo" for c in target.calls)


def test_upgrade_refuses_changed_unit(target):
    journal = target.task.prepare(target.release, target.backup)
    target.unit.write_text(target.unit.read_text() + "ProtectHome=read-only\n")
    with pytest.raises(UpgradeError, match="unit/drop-in changed"):
        target.task.apply(journal)
    assert not any(c[0] == "sudo" for c in target.calls)


def test_upgrade_workstation_guard():
    with pytest.raises(UpgradeError):
        target_guard()


def test_upgrade_refuses_changed_staged_source_before_stop(target):
    journal = target.task.prepare(target.release, target.backup)
    (target.release / "backend/requirements.txt").write_text("changed")
    with pytest.raises(UpgradeError, match="Staged release changed"):
        target.task.apply(journal)
    assert not any(c[0] == "sudo" for c in target.calls)


def test_docker_detect_uses_running_container_hierarchy(tmp_path):
    parent = hierarchy(tmp_path, True)
    leaf = parent / "docker-abc.scope"
    leaf.mkdir()
    for file in ["cpu.max", "memory.max", "pids.max"]:
        (leaf / file).write_text("max")
    process = tmp_path / "proc/123"
    process.mkdir(parents=True)
    (process / "cgroup").write_text("0::/system.slice/docker-abc.scope\n")
    mount = tmp_path / "proc/self"
    mount.mkdir()
    (mount / "mountinfo").write_text(MOUNT)

    def run(args):
        if args[1] == "context":
            return json.dumps("unix:///var/run/docker.sock")
        if args[1] == "info":
            return json.dumps(INFO)
        if args[1] == "ps":
            return "abc"
        return json.dumps([{"State": {"Pid": 123}}])

    result = compat.detect(run, root=tmp_path)
    assert result["parent"] == "/system.slice" and result["controllers"]["cpu"]


def test_cgroup_read_permission_failure_is_closed(tmp_path, monkeypatch):
    hierarchy(tmp_path, True)
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.name == "pids.max":
            raise PermissionError(13, "denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(compat.CompatibilityError):
        compat.assess(INFO, MOUNT, "/system.slice", tmp_path)


def test_remote_docker_context_refused(monkeypatch):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://sunrise@example.invalid")
    with pytest.raises(compat.CompatibilityError, match="local Unix-socket"):
        compat.require_local_docker(Mock(side_effect=AssertionError("no remote contact")))


def test_upgrade_interrupted_after_old_directory_move_can_recover(target):
    journal = target.task.prepare(target.release, target.backup)
    manifest = json.loads(journal.read_text())
    target.installed.rename(target.backup / "previous-installation")
    manifest["phase"] = "old_moved"
    journal.write_text(json.dumps(manifest))
    assert (target.backup / "recovery/upgrade.py").is_file()
    assert (target.backup / "recovery/cgroup_compat.py").is_file()
    target.task.rollback(journal)
    assert (target.installed / "VERSION").read_text() == "0.1.2"


def test_v1_detect_ignores_unrelated_controller_parent(tmp_path):
    mounts = []
    for index, (controller, file) in enumerate(
        [("cpu", "cpu.cfs_quota_us"), ("memory", "memory.limit_in_bytes"), ("pids", "pids.max")]
    ):
        directory = tmp_path / f"sys/fs/cgroup/{controller}/docker"
        leaf = directory / "abc"
        leaf.mkdir(parents=True)
        (directory / file).write_text("100")
        (leaf / file).write_text("100")
        mounts.append(
            f"{index + 1} 0 0:2 / /sys/fs/cgroup/{controller} rw - cgroup cgroup rw,{controller}"
        )
    process = tmp_path / "proc/123"
    process.mkdir(parents=True)
    (process / "cgroup").write_text(
        "1:cpu,cpuacct:/docker/abc\n2:memory:/docker/abc\n3:pids:/docker/abc\n4:perf_event:/\n"
    )
    own = tmp_path / "proc/self"
    own.mkdir()
    (own / "mountinfo").write_text("\n".join(mounts))

    def run(args):
        if args[1] == "context":
            return json.dumps("unix:///var/run/docker.sock")
        if args[1] == "info":
            return json.dumps({**INFO, "CgroupVersion": "1", "CgroupDriver": "cgroupfs"})
        if args[1] == "ps":
            return "abc"
        return json.dumps([{"State": {"Pid": 123}}])

    result = compat.detect(run, root=tmp_path)
    assert result["parent"] == "/docker" and all(result["controllers"].values())


@pytest.mark.parametrize("tree", ["installed", "release"])
def test_upgrade_refuses_recursive_backup_destination(target, tree):
    backup = getattr(target, tree) / "backup"
    with pytest.raises(UpgradeError, match="outside both"):
        target.task.prepare(target.release, backup)
    assert not backup.exists()
