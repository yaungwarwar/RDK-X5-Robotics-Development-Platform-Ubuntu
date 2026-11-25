#!/usr/bin/env python3
"""Explicit local target upgrade transaction: prepare, apply, rollback. Never auto-run."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import pwd
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
import cgroup_compat as compat

UNIT = "rdk-control-center.service"
TARGET = Path("/home/sunrise/rdk-platform")
SOURCE_VERSION = "0.1.2"
NEW_VERSION = "0.1.3"
NEW_IMAGE = f"rdk-control-center-dashboard:{NEW_VERSION}"


class UpgradeError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    fd, name = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


OUTPUT_LIMIT = 1_048_576
LOG_LIMIT = 8192


def redact(value):
    value = str(value)
    value = re.sub(
        r"(?i)(password|passwd|token|secret|authorization|api[_-]?key)([=: ]+)[^\s,;]+",
        r"\1\2[redacted]",
        value,
    )
    return re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", value)[:LOG_LIMIT]


def safe_command(argv):
    result = []
    hide_next = False
    for arg in argv:
        arg = str(arg)
        if hide_next:
            result.append("[redacted]")
            hide_next = False
        elif re.match(r"(?i)^--?(password|passwd|token|secret|authorization|api[-_]?key)$", arg):
            result.append(arg)
            hide_next = True
        elif result and result[-1] == "-c":
            result.append("[code omitted]")
        else:
            result.append(redact(arg))
    return result


def run(argv, timeout=120, log_path=None, operation="command"):
    environment = os.environ.copy()
    if argv[0] == "/usr/bin/python3" or "/.venv/bin/python" in argv[0]:
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
    start = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    status = None
    failure = None
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=environment,
        )
        for stream, name in [(process.stdout, "stdout"), (process.stderr, "stderr")]:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                failure = f"Timed out after {timeout} seconds"
                process.kill()
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[key.data]
                limit = OUTPUT_LIMIT if key.data == "stdout" else LOG_LIMIT
                truncated[key.data] |= len(buffer) + len(chunk) > limit
                buffer.extend(chunk[: max(0, limit - len(buffer))])
        status = process.wait()
        if not failure and status:
            failure = f"Command failed with exit status {status}"
        if not failure and truncated["stdout"]:
            failure = "Command stdout exceeded capture limit"
    except OSError as error:
        failure = f"Command execution failed: {error.__class__.__name__}: {error}"
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                stream.close()
    stdout = buffers["stdout"].decode("utf-8", "replace")
    stderr = buffers["stderr"].decode("utf-8", "replace")
    sensitive_output = (
        "--property=Environment" in argv
        or argv[:2] in (["docker", "inspect"], ["docker", "info"])
        or (argv[:2] == ["docker", "compose"] and "config" in argv)
    )
    if log_path is not None:
        save(
            log_path,
            {
                "operation": operation,
                "command": safe_command(argv),
                "started_at": start,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(time.monotonic() - started, 6),
                "exit_status": status,
                "failure": redact(failure) if failure else None,
                "stdout": "[omitted: may contain environment]"
                if sensitive_output
                else redact(stdout),
                "stderr": redact(stderr),
                "truncated": {
                    "stdout": truncated["stdout"] or len(stdout) > LOG_LIMIT,
                    "stderr": truncated["stderr"] or len(stderr) > LOG_LIMIT,
                },
            },
        )
    if failure:
        visible_stdout = (
            "[omitted: may contain environment]" if sensitive_output else redact(stdout)
        )
        raise UpgradeError(
            f"{redact(failure)}; stdout: {visible_stdout}; stderr: {redact(stderr)}"
            + (f"; log: {log_path}" if log_path else "")
        )
    return stdout


def target_guard():
    if (
        platform.machine() != "aarch64"
        or os.geteuid() == 0
        or pwd.getpwuid(os.geteuid()).pw_name != "sunrise"
    ):
        raise UpgradeError(
            "Run manually as sunrise on the ARM64 RDK X5; no workstation/root upgrade"
        )
    model = Path("/proc/device-tree/model").read_text().lower().replace("\0", "")
    if "rdk" not in model or "x5" not in model:
        raise UpgradeError("Cannot verify RDK X5 model")
    release = platform.freedesktop_os_release()
    if (
        release.get("ID") != "ubuntu"
        or release.get("VERSION_ID") != "22.04"
        or sys.version_info[:2] != (3, 10)
    ):
        raise UpgradeError("Ubuntu 22.04 and Python 3.10 required")


class Transaction:
    def __init__(
        self,
        installed=TARGET,
        unit_path=Path("/etc/systemd/system") / UNIT,
        run_command=run,
        detect=compat.detect,
        health=None,
    ):
        self.installed = installed.resolve()
        self.unit_path = unit_path
        self.command = run_command
        self.preparation_journal = None
        self.preparation_state = None
        self.run = self.record_command
        self.detect = detect
        self.health = health or self.wait_health

    def record_command(self, argv, timeout=120):
        if self.command is not run or self.preparation_journal is None:
            return self.command(argv, timeout=timeout)
        log_dir = self.preparation_journal.parent / "logs"
        log_path = log_dir / (uuid.uuid4().hex + ".json")
        operation = self.preparation_state.get("next_stage") or self.preparation_state["state"]
        self.preparation_state["last_log"] = str(log_path)
        save(self.preparation_journal, self.preparation_state)
        return run(argv, timeout=timeout, log_path=log_path, operation=operation)

    def compose(self, config, *args):
        return self.run(["docker", "compose", "-p", "rdk-control-center", "-f", str(config), *args])

    def unit_files(self):
        files = [self.unit_path]
        directory = self.unit_path.with_name(UNIT + ".d")
        if directory.exists():
            files += sorted(directory.glob("*.conf"))
        # Reject additional /run or vendor drop-ins rather than omit them from backup.
        paths = self.run(
            ["/usr/bin/systemctl", "show", UNIT, "--property=DropInPaths", "--value"]
        ).split()
        if set(paths) != {str(p) for p in files[1:]}:
            raise UpgradeError("Unaccounted systemd drop-ins; back up/review explicitly first")
        return files

    def preflight(self, release):
        if (
            not self.installed.is_dir()
            or (self.installed / "VERSION").read_text().strip() != SOURCE_VERSION
        ):
            raise UpgradeError(
                f"Expected operational v{SOURCE_VERSION} installation; refuse overlay/repeated apply"
            )
        compat.require_local_docker(self.run)
        self.health(SOURCE_VERSION)
        release = release.resolve()
        if (
            release == self.installed
            or self.installed in release.parents
            or release in self.installed.parents
        ):
            raise UpgradeError("Release must be a separate sibling staging tree")
        if (release / "VERSION").read_text().strip() != NEW_VERSION or (release / ".venv").exists():
            raise UpgradeError(
                f"New source-only {NEW_VERSION} staging tree required (no transferred venv)"
            )
        if not (self.installed / ".venv/bin/python").is_file() or not self.unit_path.is_file():
            raise UpgradeError("Existing native venv and systemd unit required")
        text = self.unit_path.read_text()
        if "User=sunrise" not in text or f"WorkingDirectory={self.installed}" not in text:
            raise UpgradeError(
                "Existing service user/path differs; explicit administrator review needed"
            )
        if self.run(["/usr/bin/systemctl", "is-active", UNIT]).strip() != "active":
            raise UpgradeError("Existing backend must be active before preparing upgrade")
        self.unit_files()
        effective_user = self.run(
            ["/usr/bin/systemctl", "show", UNIT, "--property=User", "--value"]
        ).strip()
        if effective_user != "sunrise":
            raise UpgradeError("Effective service user must remain sunrise")
        if self.installed.stat().st_dev != release.stat().st_dev:
            raise UpgradeError("Staging and installation must share a filesystem for atomic rename")
        return release

    def prepare(self, release, backup, compose_files=None, parent=None):
        self.preparation_state = None
        self.preparation_journal = None
        try:
            return self._prepare(release, backup, compose_files, parent)
        except Exception as error:
            if self.preparation_journal is not None:
                self.preparation_state.update(
                    {
                        "state": "FAILED",
                        "failed_stage": self.preparation_state["next_stage"],
                        "failure_reason": redact(error),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "recovery": "Preserve this backup and staged tree; retry with fresh source and a new backup directory.",
                    }
                )
                save(self.preparation_journal, self.preparation_state)
                print(
                    f"Preparation failed at {self.preparation_state['failed_stage']}; "
                    f"inspect {self.preparation_journal}. Preserve artifacts and retry "
                    "using a fresh release and backup directory.",
                    file=sys.stderr,
                )
            raise

    def transition(self, state, next_stage):
        self.preparation_state.update(
            {
                "state": state,
                "next_stage": next_stage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if state not in {"BACKUP_STARTED", "ACTIVATING", "ROLLING_BACK"}:
            self.preparation_state["last_successful_stage"] = state
        save(self.preparation_journal, self.preparation_state)

    def _prepare(self, release, backup, compose_files=None, parent=None):
        release = release.resolve()
        backup = backup.resolve()
        if any(
            backup == tree or tree in backup.parents or backup in tree.parents
            for tree in [self.installed, release]
        ):
            raise UpgradeError("Backup must be outside both installation and staging trees")
        if backup.exists() or backup.parent.stat().st_dev != self.installed.stat().st_dev:
            raise UpgradeError("Use a new backup directory on the installation filesystem")
        backup.mkdir(mode=0o700)
        (backup / "logs").mkdir(mode=0o700)
        self.preparation_journal = backup / "preparation.json"
        self.preparation_state = {
            "transaction_id": uuid.uuid4().hex,
            "release": str(release),
            "backup": str(backup),
            "installed": str(self.installed),
            "version": NEW_VERSION,
            "source_version": SOURCE_VERSION,
            "target_version": NEW_VERSION,
            "activation_health_version": NEW_VERSION,
            "rollback_health_version": SOURCE_VERSION,
            "new_image_tag": NEW_IMAGE,
            "state": "NEW",
            "last_successful_stage": None,
            "next_stage": "PREFLIGHT_PASSED",
            "last_log": None,
            "log_directory": str(backup / "logs"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        save(self.preparation_journal, self.preparation_state)
        release = self.preflight(release)
        # Enough space to preserve the full old source/venv plus image and stage.
        size = sum(
            p.stat().st_size
            for p in self.installed.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        if shutil.disk_usage(backup.parent).free < 2 * size + 1_073_741_824:
            raise UpgradeError("Insufficient free storage for backup, image and staging")
        marker = self.installed / ".deployment/active.json"
        try:
            relative = Path(json.loads(marker.read_text())["compose"])
            active = (self.installed / relative).resolve()
            if (
                relative.is_absolute()
                or self.installed not in active.parents
                or not active.is_file()
            ):
                raise ValueError("invalid path")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UpgradeError("Invalid or missing active deployment marker") from error
        if compose_files and [p.resolve() for p in compose_files] != [active]:
            raise UpgradeError("Compose file must match the active generated deployment")
        files = [active]
        nginx_files = sorted((self.installed / "frontend").glob("nginx*.conf"))
        arguments = ["docker", "compose", "-p", "rdk-control-center"]
        for path in files:
            arguments += ["-f", str(path.resolve())]
        original_hashes = {
            str(p): digest(p)
            for p in [
                *files,
                marker,
                *nginx_files,
                *self.unit_files(),
                *((self.installed / "config").rglob("*.yaml")),
            ]
        }
        old = json.loads(self.run(arguments + ["config", "--format", "json"]))
        service = compat.validate_security(old)
        container = compat.running_dashboard(self.run)
        if not container or container["State"].get("Status") != "running":
            raise UpgradeError("Operational dashboard container required")
        # Verify actual container boundaries as well as resolved source config.
        host = container["HostConfig"]
        if (
            host.get("NetworkMode") != "host"
            or host.get("Privileged")
            or not host.get("ReadonlyRootfs")
            or host.get("Devices")
            or set(host.get("CapDrop") or []) != {"ALL"}
            or container["Config"].get("User") != "101:101"
            or not any("no-new-privileges" in item for item in host.get("SecurityOpt") or [])
            or host.get("Memory", 0) <= 0
            or host.get("PidsLimit", 0) <= 0
        ):
            raise UpgradeError("Running dashboard does not match required isolation profile")
        report = self.detect(run=self.run, parent_override=parent)
        previous = compat.generate(old, report, "preserve")
        # Preserve the actual administrator quota workaround even when stale
        # source files still contain cpus. No new quota is added during upgrades.
        if not host.get("NanoCpus", 0) and host.get("CpuQuota", 0) <= 0:
            previous["services"]["dashboard"].pop("cpus", None)
            previous["services"]["dashboard"].pop("cpu_quota", None)
            previous["services"]["dashboard"].get("deploy", {}).get("resources", {}).get(
                "limits", {}
            ).pop("cpus", None)
        self.transition("PREFLIGHT_PASSED", "BACKUP_STARTED")
        self.transition("BACKUP_STARTED", "BACKUP_COMPLETED")
        recovery = backup / "recovery"
        recovery.mkdir(mode=0o700)
        for name in ["upgrade.py", "cgroup_compat.py"]:
            shutil.copy2(Path(__file__).with_name(name), recovery / name)
        shutil.copytree(self.installed, backup / "source-and-venv", symlinks=True)
        units = backup / "units"
        units.mkdir(mode=0o700)
        unit_hashes = {}
        for index, path in enumerate(self.unit_files()):
            shutil.copy2(path, units / f"{index}-{path.name}")
            unit_hashes[str(path)] = digest(path)
        image_id = container["Image"]
        self.preparation_state.update({"old_image_id": image_id, "old_image_tag": service["image"]})
        save(self.preparation_journal, self.preparation_state)
        self.run(
            ["docker", "image", "save", "--output", str(backup / "frontend-image.tar"), image_id],
            timeout=600,
        )
        # New image gets a new tag; the running source image/tag is untouched.
        save(backup / "compose.previous.json", previous)
        save(backup / "compatibility.json", report)
        self.transition("BACKUP_COMPLETED", "VENV_CREATED")
        save(
            backup / "staged-defaults.json",
            {
                str(p.relative_to(release)): p.read_text()
                for p in (release / "config").glob("*.yaml")
            },
        )
        # Existing administrator config and Nginx files are authoritative.
        shutil.copytree(
            self.installed / "config", release / "config", dirs_exist_ok=True, symlinks=True
        )
        for path in (self.installed / "frontend").glob("nginx*.conf"):
            shutil.copy2(path, release / "frontend" / path.name)
        selected = self.run(
            ["/usr/bin/systemctl", "show", UNIT, "--property=Environment", "--value"]
        )
        import shlex

        environment = dict(item.split("=", 1) for item in shlex.split(selected) if "=" in item)
        configured = Path(environment.get("RDK_CONFIG", str(self.installed / "config/rdkx5.yaml")))
        try:
            relative_config = configured.relative_to(self.installed)
        except ValueError as error:
            raise UpgradeError("External RDK_CONFIG needs a separately reviewed upgrade") from error
        if relative_config.parts[0] != "config" or not (release / relative_config).is_file():
            raise UpgradeError("Selected existing service config must be inside config/")
        self.run(["/usr/bin/python3", "-m", "venv", str(release / ".venv")])
        self.transition("VENV_CREATED", "DEPENDENCIES_INSTALLED")
        python = release / ".venv/bin/python"
        self.run(
            [str(python), "-m", "pip", "install", "-r", str(release / "backend/requirements.txt")],
            timeout=600,
        )
        self.transition("DEPENDENCIES_INSTALLED", "DEPENDENCIES_VALIDATED")
        self.run([str(python), "-m", "pip", "check"])
        self.transition("DEPENDENCIES_VALIDATED", "CONFIG_VALIDATED")
        # Fixed code snippet; user configuration is an argument, never code.
        self.run(
            [
                str(python),
                "-c",
                'import sys; sys.path.insert(0, sys.argv[1]); from app.config.settings import load_settings; s=load_settings(sys.argv[2]); assert s.mode == "native"; import app.main',
                str(release / "backend"),
                str(release / relative_config),
            ]
        )
        self.transition("CONFIG_VALIDATED", "COMPATIBILITY_GENERATED")
        final = compat.generate(previous, report, "preserve")
        final["services"]["dashboard"]["image"] = NEW_IMAGE
        final["services"]["dashboard"]["build"] = {"context": str(self.installed / "frontend")}
        bundle_id = f"v{NEW_VERSION}-" + uuid.uuid4().hex[:12]
        deployment = release / ".deployment"
        deployment.mkdir(exist_ok=True, mode=0o700)
        bundle = deployment / bundle_id
        compat.write_bundle(bundle, final, report)
        save(
            deployment / "active.json", {"compose": f".deployment/{bundle_id}/compose.compat.json"}
        )
        self.compose(bundle / "compose.compat.json", "config", "-q")
        self.transition("COMPATIBILITY_GENERATED", "IMAGE_BUILT")
        self.run(
            [
                "docker",
                "build",
                "--tag",
                NEW_IMAGE,
                str(release / "frontend"),
            ],
            timeout=900,
        )
        self.transition("IMAGE_BUILT", "PREPARED")
        # Python itself is relocatable; repair generated entrypoints/activate
        # paths so pip and optional manual activation also survive atomic move.
        for path in (release / ".venv/bin").iterdir():
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                if b"\0" not in data:
                    path.write_bytes(
                        data.replace(str(release).encode(), str(self.installed).encode())
                    )
        if any(digest(Path(path)) != expected for path, expected in original_hashes.items()):
            raise UpgradeError(
                "Installed configuration changed while preparing; nothing stopped, prepare again"
            )
        staged_hashes = {
            str(p.relative_to(release)): digest(p)
            for p in [
                release / "VERSION",
                release / "backend/requirements.txt",
                *release.glob("backend/app/**/*.py"),
                *release.glob("scripts/*"),
                *release.glob("frontend/src/**/*"),
                *release.glob("frontend/public/**/*"),
                *release.glob("frontend/package*.json"),
                *release.glob("frontend/index.html"),
                *release.glob("frontend/tsconfig.json"),
                *release.glob("frontend/vite.config.*"),
                *release.glob("frontend/Dockerfile"),
                *release.glob("compose.yaml"),
                *release.glob("config/**/*"),
                *release.glob("frontend/nginx*.conf"),
                bundle / "compose.compat.json",
            ]
            if p.is_file()
        }
        manifest = {
            "format": 1,
            "transaction_id": self.preparation_state["transaction_id"],
            "phase": "prepared",
            "installed": str(self.installed),
            "release": str(release),
            "backup": str(backup),
            "old_image_id": image_id,
            "old_image_tag": service["image"],
            "new_compose": f".deployment/{bundle_id}/compose.compat.json",
            "unit_hashes": unit_hashes,
            "input_hashes": {str(p): digest(p) for p in [*files, marker, *nginx_files]},
            "config_hashes": {
                str(p): digest(p) for p in (self.installed / "config").rglob("*") if p.is_file()
            },
            "new_version": NEW_VERSION,
            "source_version": SOURCE_VERSION,
            "target_version": NEW_VERSION,
            "activation_health_version": NEW_VERSION,
            "rollback_health_version": SOURCE_VERSION,
            "new_image_tag": NEW_IMAGE,
            "compatibility_hash": digest(bundle / "compose.compat.json"),
            "staged_hashes": staged_hashes,
        }
        self.preparation_state.update(
            {
                "staged_hashes": staged_hashes,
                "new_compose": manifest["new_compose"],
                "compatibility_hash": manifest["compatibility_hash"],
            }
        )
        save(backup / "transaction.json", manifest)
        self.transition("PREPARED", None)
        return backup / "transaction.json"

    def verify_manifest(self, manifest):
        if (
            manifest.get("format") != 1
            or Path(manifest["installed"]).resolve() != self.installed
            or manifest.get("new_version") != NEW_VERSION
            or manifest.get("source_version") != SOURCE_VERSION
            or manifest.get("target_version") != NEW_VERSION
            or manifest.get("activation_health_version") != NEW_VERSION
            or manifest.get("rollback_health_version") != SOURCE_VERSION
            or manifest.get("new_image_tag") != NEW_IMAGE
            or not manifest.get("old_image_id")
            or not manifest.get("old_image_tag")
        ):
            raise UpgradeError("Transaction is not for this installation/release")
        for path, expected in manifest["unit_hashes"].items():
            if digest(Path(path)) != expected:
                raise UpgradeError(
                    "Systemd unit/drop-in changed since preparation; refusing overwrite"
                )
        if set(manifest["unit_hashes"]) != {str(p) for p in self.unit_files()}:
            raise UpgradeError("Systemd drop-in set changed since preparation")

    def apply(self, journal):
        data = json.loads(journal.read_text())
        release, backup = Path(data["release"]), Path(data["backup"])
        self.preparation_journal = backup / "preparation.json"
        self.preparation_state = json.loads(self.preparation_journal.read_text())
        self.verify_manifest(data)
        if data["phase"] != "prepared":
            raise UpgradeError("Only a prepared transaction can be applied once")
        if self.preparation_state.get("state") != "PREPARED":
            raise UpgradeError("Preparation did not complete; use a fresh staged release")
        if data.get("transaction_id") != self.preparation_state.get("transaction_id"):
            raise UpgradeError("Transaction journal identity mismatch")
        if (
            self.preparation_state.get("version") != NEW_VERSION
            or self.preparation_state.get("release") != data["release"]
            or self.preparation_state.get("backup") != data["backup"]
            or self.preparation_state.get("installed") != data["installed"]
        ):
            raise UpgradeError("Preparation journal identity mismatch")
        for key in (
            "source_version",
            "target_version",
            "activation_health_version",
            "rollback_health_version",
            "new_image_tag",
            "old_image_id",
            "old_image_tag",
        ):
            if data.get(key) != self.preparation_state.get(key):
                raise UpgradeError("Transaction version or image metadata mismatch")
        for key in ("staged_hashes", "new_compose", "compatibility_hash"):
            if data.get(key) != self.preparation_state.get(key):
                raise UpgradeError("Transaction release identity mismatch")
        if (self.installed / "VERSION").read_text().strip() != SOURCE_VERSION:
            raise UpgradeError("Installed version changed since preparation")
        if not data.get("staged_hashes") or "VERSION" not in data["staged_hashes"]:
            raise UpgradeError("Missing staged release identity")
        for path, expected in {**data["input_hashes"], **data["config_hashes"]}.items():
            if digest(Path(path)) != expected:
                raise UpgradeError("Installed config changed after prepare; prepare a new release")
        for relative, expected in data.get("staged_hashes", {}).items():
            if digest(release / relative) != expected:
                raise UpgradeError("Staged release changed after preparation; prepare again")
        report = self.detect(run=self.run)
        config = json.loads((release / data["new_compose"]).read_text())
        if (
            digest(release / data["new_compose"]) != data.get("compatibility_hash")
            or config["services"]["dashboard"]["image"] != NEW_IMAGE
        ):
            raise UpgradeError("Generated compatibility configuration or image changed")
        updated = compat.generate(config, report, "preserve")
        if updated != config:
            raise UpgradeError("Cgroup compatibility changed; prepare again before stopping")
        data["phase"] = "stopping"
        save(journal, data)
        self.transition("ACTIVATING", "ACTIVE")
        try:
            self.run(["sudo", "/usr/bin/systemctl", "stop", UNIT])
            self.installed.rename(backup / "previous-installation")
            data["phase"] = "old_moved"
            save(journal, data)
            release.rename(self.installed)
            data["phase"] = "new_active"
            save(journal, data)
            self.run(["sudo", "/usr/bin/systemctl", "start", UNIT])
            self.compose(
                self.installed / data["new_compose"],
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "dashboard",
            )
            self.health(NEW_VERSION)
            data["phase"] = "complete"
            save(journal, data)
            self.transition("ACTIVE", None)
        except Exception as error:
            data["activation_error"] = redact(error)[:512]
            save(journal, data)
            self.preparation_state["activation_failure"] = redact(error)
            save(self.preparation_journal, self.preparation_state)
            try:
                self.rollback(journal)
            except Exception as rollback_error:
                raise UpgradeError(
                    f"Activation failed: {error}; automatic rollback also failed: {rollback_error}. Retained transaction: {journal}. Use the backup recovery script after resolving the failure."
                ) from rollback_error
            raise

    def rollback(self, journal):
        try:
            self._rollback(journal)
        except Exception as error:
            if self.preparation_journal is not None and self.preparation_state is not None:
                self.preparation_state.update(
                    {
                        "state": "FAILED",
                        "failed_stage": "ROLLING_BACK",
                        "failure_reason": redact(error),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "recovery": "Rollback failed; retain artifacts and resolve the error before retrying rollback.",
                    }
                )
                save(self.preparation_journal, self.preparation_state)
            raise

    def _rollback(self, journal):
        data = json.loads(journal.read_text())
        backup = Path(data["backup"])
        self.preparation_journal = backup / "preparation.json"
        self.preparation_state = json.loads(self.preparation_journal.read_text())
        self.verify_manifest(data)
        if data["phase"] == "rolled_back":
            return
        if data["phase"] not in {"stopping", "old_moved", "new_active", "complete"}:
            raise UpgradeError("No activated/stopped transaction to roll back")
        self.transition("ROLLING_BACK", "ROLLED_BACK")
        self.run(["sudo", "/usr/bin/systemctl", "stop", UNIT])
        previous = backup / "previous-installation"
        if previous.exists():
            if self.installed.exists():
                # Stop only this project's dashboard before swapping bind sources.
                self.compose(self.installed / data["new_compose"], "down")
                self.installed.rename(backup / "failed-release")
            previous.rename(self.installed)
        self.run(
            ["docker", "image", "load", "--input", str(backup / "frontend-image.tar")], timeout=600
        )
        self.run(["docker", "image", "tag", data["old_image_id"], data["old_image_tag"]])
        self.run(["sudo", "/usr/bin/systemctl", "start", UNIT])
        self.compose(
            backup / "compose.previous.json",
            "up",
            "-d",
            "--no-build",
            "--force-recreate",
            "dashboard",
        )
        self.health(SOURCE_VERSION)
        data["phase"] = "rolled_back"
        save(journal, data)
        self.transition("ROLLED_BACK", None)

    def wait_health(self, version):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8089/api/v1/health", timeout=3
                ) as response:
                    data = json.load(response)
                with urllib.request.urlopen("http://127.0.0.1:8088/healthz", timeout=3) as response:
                    assert response.status == 200
                container = compat.running_dashboard(self.run)
                if (
                    data["version"] == version
                    and data["mode"] == "native"
                    and data["status"] == "ok"
                    and container is not None
                    and container["State"].get("Health", {}).get("Status") == "healthy"
                ):
                    return
            except (
                OSError,
                ValueError,
                AssertionError,
                compat.CompatibilityError,
                UpgradeError,
                subprocess.SubprocessError,
            ):
                pass
            time.sleep(1)
        raise UpgradeError("Application health checks did not pass within 90 seconds")


@contextlib.contextmanager
def lock():
    with Path("/home/sunrise/.rdk-control-center-upgrade.lock").open("a") as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def inspect_transaction(path):
    path = Path(path)
    if path.is_dir():
        path = path / "preparation.json"
    elif path.name == "transaction.json":
        path = path.with_name("preparation.json")
    data = json.loads(path.read_text())
    state = data.get("state")
    if state == "FAILED":
        classification = "failed"
    elif state in {"PREPARED", "ACTIVE", "ROLLED_BACK"}:
        classification = state.lower()
    elif state in {"ACTIVATING", "ROLLING_BACK"}:
        classification = "interrupted activation or rollback"
    else:
        classification = "interrupted preparation"
    return {"classification": classification, "journal": str(path), "transaction": data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "apply", "rollback", "status", "diagnose"])
    parser.add_argument("--release", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--transaction", type=Path)
    parser.add_argument("--compose-file", type=Path, action="append")
    parser.add_argument("--parent")
    args = parser.parse_args()
    if args.action in {"status", "diagnose"}:
        if not args.transaction:
            parser.error("status/diagnose requires --transaction")
        print(json.dumps(inspect_transaction(args.transaction.resolve()), indent=2))
        return
    target_guard()
    with lock():
        task = Transaction()
        if args.action == "prepare":
            if not args.release or not args.backup:
                parser.error("prepare requires --release and --backup")
            journal = task.prepare(args.release, args.backup, args.compose_file, args.parent)
            report = json.loads((journal.parent / "compatibility.json").read_text())
            for warning in report.get("warnings", []):
                print("WARNING:", warning)
            print("Prepared transaction:", journal)
        else:
            if not args.transaction:
                parser.error("apply/rollback requires --transaction")
            getattr(task, args.action)(args.transaction.resolve())
            print(args.action, "finished; transaction:", args.transaction)


if __name__ == "__main__":
    try:
        main()
    except (
        UpgradeError,
        compat.CompatibilityError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        raise SystemExit(f"Upgrade stopped: {error}")
