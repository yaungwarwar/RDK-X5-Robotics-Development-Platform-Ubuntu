#!/usr/bin/env python3
"""Read-only Docker/cgroup preflight and exclusive generation of deployment config.

No kernel settings, cgroup subtree controls, daemon settings or processes are changed.
Only the explicit output directory is written. Uses JSON Compose (YAML 1.2 subset).
"""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class CompatibilityError(RuntimeError):
    pass


def command(argv, timeout=15):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout


def read(path):
    try:
        return path.read_text().strip()
    except OSError as error:
        raise CompatibilityError(
            f"Required cgroup evidence unreadable: {path} (errno {error.errno})"
        ) from error


def safe_relative(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"/?[a-zA-Z0-9_./:@-]*", value)
        or ".." in Path(value).parts
    ):
        raise CompatibilityError("Invalid cgroup path")
    return value.lstrip("/")


def mount_table(text):
    entries = []
    for line in text.splitlines():
        before, after = line.split(" - ", 1)
        fields, extra = before.split(), after.split()
        # Escaped/masked mount paths are unsupported rather than guessed.
        if "\\" in fields[4] or fields[3] != "/":
            continue
        entries.append(
            {
                "root": fields[3],
                "mount": fields[4],
                "type": extra[0],
                "options": extra[2].split(","),
            }
        )
    return entries


def assess(info, mounts, parent, root=Path("/"), live_paths=None):
    """Pure read-only assessment. root remaps absolute paths for fixtures."""
    version = str(info.get("CgroupVersion", ""))
    driver = info.get("CgroupDriver")
    if version not in {"1", "2"} or driver not in {"systemd", "cgroupfs"}:
        raise CompatibilityError("Unsupported or unknown Docker cgroup version/driver")
    if any("rootless" in option for option in info.get("SecurityOptions", [])):
        raise CompatibilityError("Rootless Docker delegation requires explicit separate validation")
    if not info.get("MemoryLimit") or not info.get("PidsLimit"):
        raise CompatibilityError("Docker reports required memory/PID limits unavailable")
    parent = safe_relative(parent)
    entries = mount_table(mounts)
    evidence = []
    supported = {}
    for controller, interface in [
        ("cpu", "cpu.max" if version == "2" else "cpu.cfs_quota_us"),
        ("memory", "memory.max" if version == "2" else "memory.limit_in_bytes"),
        ("pids", "pids.max"),
    ]:
        match = next(
            (
                m
                for m in entries
                if m["type"] == ("cgroup2" if version == "2" else "cgroup")
                and (version == "2" or controller in m["options"])
            ),
            None,
        )
        if match is None:
            supported[controller] = False
            evidence.append(f"{controller}: matching cgroup mount absent")
            continue
        mount = root / match["mount"].lstrip("/")
        target = mount / parent
        try:
            if version == "2":
                chain = [mount]
                for part in Path(parent).parts:
                    chain.append(chain[-1] / part)
                ok = True
                for index, directory in enumerate(chain):
                    available = read(directory / "cgroup.controllers").split()
                    if controller not in available:
                        ok = False
                    if (
                        index < len(chain) - 1
                        and controller not in read(directory / "cgroup.subtree_control").split()
                    ):
                        ok = False
                if controller not in read(target / "cgroup.subtree_control").split():
                    ok = False
                # Root has no cpu.max; non-root parent must expose the interface.
                if parent:
                    if not (target / interface).is_file():
                        ok = False
                    else:
                        read(target / interface)
            else:
                ok = (target / interface).is_file()
            # A running dashboard's actual leaf gives stronger effective evidence.
            leaf = (live_paths or {}).get(controller)
            if leaf is not None:
                actual = mount / safe_relative(leaf)
                if not (actual / interface).is_file():
                    ok = False
                else:
                    read(actual / interface)
            if controller == "cpu" and not info.get("CpuCfsQuota", False):
                ok = False
            supported[controller] = ok
            evidence.append(f"{controller}: parent=/{parent} interface={interface} effective={ok}")
        except CompatibilityError as error:
            supported[controller] = False
            evidence.append(str(error))
    if not supported["memory"] or not supported["pids"]:
        raise CompatibilityError(
            "Required memory/PID isolation is not effective: " + "; ".join(evidence)
        )
    warnings = []
    if not supported["cpu"]:
        warnings.append(
            "RDK-COMPAT-001: effective Docker CPU quota controller unavailable; CPU quota omitted. Memory/PID limits and security controls remain required. Kernel compilation flags do not establish delegation. Watchdog causation is unproven."
        )
    return {
        "cgroup_version": version,
        "cgroup_driver": driver,
        "parent": "/" + parent,
        "controllers": supported,
        "evidence": evidence,
        "warnings": warnings,
    }


def require_local_docker(run=command):
    endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
    if endpoint is None:
        endpoint = json.loads(
            run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"])
        )
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise CompatibilityError(
            "A local Unix-socket Docker endpoint is required; TCP/SSH/remote contexts are refused"
        )


def running_dashboard(run=command):
    ids = run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=rdk-control-center",
            "--filter",
            "label=com.docker.compose.service=dashboard",
        ]
    ).split()
    if len(ids) > 1:
        raise CompatibilityError("Multiple dashboard containers found; resolve explicitly")
    return json.loads(run(["docker", "inspect", ids[0]]))[0] if ids else None


def detect(run=command, root=Path("/"), parent_override=None):
    require_local_docker(run)
    info = json.loads(run(["docker", "info", "--format", "{{json .}}"]))
    live = running_dashboard(run)
    parent = None
    paths = {}
    if live and live["State"].get("Pid", 0) > 0:
        pid = int(live["State"]["Pid"])
        lines = read(root / f"proc/{pid}/cgroup").splitlines()
        for line in lines:
            _, controllers, path = line.split(":", 2)
            if info.get("CgroupVersion") in ("2", 2) and controllers == "":
                for controller in ["cpu", "memory", "pids"]:
                    paths[controller] = path
                parent = str(Path(path).parent)
            elif set(controllers.split(",")) & {"cpu", "memory", "pids"}:
                for controller in controllers.split(","):
                    paths[controller] = path
                derived = str(Path(path).parent)
                if parent is not None and derived != parent:
                    raise CompatibilityError("Split v1 cgroup parents require explicit review")
                parent = derived
    if parent_override:
        specified = "/" + safe_relative(parent_override)
        if parent is not None and specified != parent:
            raise CompatibilityError("Explicit parent disagrees with running dashboard cgroup")
        parent = specified
    if parent is None:
        # Discover daemon parent settings without modifying them. Conflicting
        # custom parents are rejected; no guess from the caller's own cgroup.
        config = root / "etc/docker/daemon.json"
        daemon_config = json.loads(config.read_text()) if config.exists() else {}
        parent = daemon_config.get("cgroup-parent")
        pid = run(
            ["/usr/bin/systemctl", "show", "docker.service", "--property=MainPID", "--value"]
        ).strip()
        if not pid.isdecimal() or int(pid) <= 0:
            raise CompatibilityError(
                "Cannot verify Docker daemon command line; supply --parent after inspection"
            )
        args = (root / f"proc/{pid}/cmdline").read_bytes().decode().split("\0")
        for index, arg in enumerate(args):
            if arg.startswith("--cgroup-parent="):
                parent = arg.split("=", 1)[1]
            elif arg == "--cgroup-parent" and index + 1 < len(args):
                parent = args[index + 1]
        parent = parent or ("/system.slice" if info.get("CgroupDriver") == "systemd" else "/")
        if parent.endswith(".slice") and parent.count("-"):
            raise CompatibilityError(
                "Nested systemd slice must be supplied as resolved --parent path"
            )
    result = assess(info, read(root / "proc/self/mountinfo"), parent, root, paths)
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    return result


def validate_security(config):
    if config.get("name") != "rdk-control-center" or set(config.get("services", {})) != {
        "dashboard"
    }:
        raise CompatibilityError("Only the rdk-control-center dashboard project is accepted")
    service = config["services"]["dashboard"]
    if (
        service.get("user") != "101:101"
        or not service.get("read_only")
        or service.get("privileged")
        or service.get("network_mode") != "host"
        or service.get("devices")
        or service.get("ports")
        or service.get("cap_add")
        or service.get("pid") == "host"
    ):
        raise CompatibilityError(
            "Dashboard execution/security boundary differs from supported profile"
        )
    if set(service.get("cap_drop", [])) != {"ALL"} or not any(
        x in {"no-new-privileges:true"} for x in service.get("security_opt", [])
    ):
        raise CompatibilityError("Required capability/no-new-privileges controls absent")
    if int(service.get("mem_limit", 0)) <= 0 or int(service.get("pids_limit", 0)) <= 0:
        raise CompatibilityError("Required positive memory and PID limits absent")
    volumes = service.get("volumes", [])
    if (
        len(volumes) != 1
        or volumes[0].get("target") != "/etc/nginx/nginx.conf"
        or not volumes[0].get("read_only")
        or "docker.sock" in str(volumes)
    ):
        raise CompatibilityError("Only the read-only Nginx config bind is accepted")
    source = Path(volumes[0]["source"])
    text = source.read_text()
    includes = re.findall(r"\binclude\s+([^;]+);", text)
    if any(value.strip() != "/etc/nginx/mime.types" for value in includes):
        raise CompatibilityError("Unreviewed Nginx includes prevent loopback-only validation")
    listeners = re.findall(r"^\s*listen\s+([^;]+);", text, re.M)
    if not listeners or any(
        not re.fullmatch(r"127\.0\.0\.1:8088(?:\s+default_server)?", value.strip())
        for value in listeners
    ):
        raise CompatibilityError("Upgrade/deployment requires loopback-only Nginx on 8088")
    return service


def generate(config, assessment, cpu_policy="auto"):
    result = copy.deepcopy(config)
    service = validate_security(result)
    if not assessment["controllers"]["memory"] or not assessment["controllers"]["pids"]:
        raise CompatibilityError("Memory/PID controller validation failed")
    # Normalized standalone config, never an in-place edit or null quota override.
    supported = assessment["controllers"]["cpu"]
    for field in ["cpu_quota", "cpu_period", "cpu_shares", "cpu_rt_period", "cpu_rt_runtime"]:
        if not supported or cpu_policy == "none":
            service.pop(field, None)
    limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
    if not supported or cpu_policy == "none":
        service.pop("cpus", None)
        limits.pop("cpus", None)
    elif cpu_policy == "auto":
        service.setdefault("cpus", 0.5)
    elif cpu_policy != "preserve":
        raise CompatibilityError("Invalid CPU policy")
    return result


def write_bundle(directory, config, assessment):
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, value in [("compose.compat.json", config), ("compatibility.json", assessment)]:
        path = directory / name
        with path.open("x") as out:
            json.dump(value, out, indent=2)
            out.write("\n")
        path.chmod(0o600)
    return directory / "compose.compat.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, action="append", required=True)
    parser.add_argument("--parent")
    parser.add_argument("--cpu-policy", choices=["auto", "preserve", "none"], default="auto")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    argv = ["docker", "compose", "-p", "rdk-control-center"]
    for file in args.compose_file:
        argv += ["-f", str(file.resolve())]
    require_local_docker()
    config = json.loads(command(argv + ["config", "--format", "json"]))
    report = detect(parent_override=args.parent)
    rendered = generate(config, report, args.cpu_policy)
    if args.check:
        print(json.dumps(report, indent=2))
        return
    if args.output_dir is None:
        parser.error("--output-dir is required unless --check is used")
    report["input_sha256"] = {
        str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.compose_file
    }
    output = write_bundle(args.output_dir.resolve(), rendered, report)
    command(["docker", "compose", "-p", "rdk-control-center", "-f", str(output), "config", "-q"])
    for warning in report["warnings"]:
        print("WARNING:", warning)
    print("Validated separate config:", output)


if __name__ == "__main__":
    try:
        main()
    except (CompatibilityError, OSError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(f"Compatibility preflight stopped: {error}")
