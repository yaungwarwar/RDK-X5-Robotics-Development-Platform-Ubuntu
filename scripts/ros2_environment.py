#!/usr/bin/env python3
"""Read-only, allowlisted shell/service environment evidence. No ROS2 configuration changes."""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

KEYS = [
    "ROS_DISTRO",
    "ROS_VERSION",
    "ROS_PYTHON_VERSION",
    "ROS_DOMAIN_ID",
    "RMW_IMPLEMENTATION",
    "ROS_LOCALHOST_ONLY",
    "AMENT_PREFIX_PATH",
    "COLCON_PREFIX_PATH",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
    "PATH",
    "ROS_DISCOVERY_SERVER",
    "RMW_FASTRTPS_USE_QOS_FROM_XML",
]
PROFILES = ["CYCLONEDDS_URI", "FASTRTPS_DEFAULT_PROFILES_FILE", "FASTDDS_DEFAULT_PROFILES_FILE"]


def inspect(pid):
    process = Path("/proc") / str(pid)
    try:
        env = dict(
            item.split("=", 1)
            for item in (process / "environ").read_bytes().decode(errors="replace").split("\0")
            if "=" in item
        )
    except OSError as error:
        raise SystemExit(
            f"Cannot read own-user process environment (errno {error.errno}); do not change permissions/hardening"
        ) from error

    def link(name):
        try:
            return os.readlink(process / name)
        except OSError as error:
            return f"unavailable (errno {error.errno})"

    def details(path):
        try:
            metadata = path.stat()
            return {
                "mode": oct(stat.S_IMODE(metadata.st_mode)),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "device": metadata.st_dev,
            }
        except OSError as error:
            return {"unavailable_errno": error.errno}

    return {
        "pid": pid,
        "executable": link("exe"),
        "cwd": link("cwd"),
        "environment": {
            key: "".join(c if c.isprintable() else "?" for c in env[key])[:2048]
            if key in env
            else None
            for key in KEYS
        },
        "profile_variables": {
            key: {
                "set": key in env,
                "sha256": hashlib.sha256(env[key].encode()).hexdigest() if key in env else None,
            }
            for key in PROFILES
        },
        "namespaces": {name: link("ns/" + name) for name in ["mnt", "net", "ipc", "user"]},
        "dev_shm": details(process / "root/dev/shm"),
        "tmp": details(process / "root/tmp"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=os.getpid())
    args = parser.parse_args()
    if not 1 <= args.pid < 2**31:
        parser.error("positive Linux PID required")
    print(json.dumps(inspect(args.pid), indent=2))


if __name__ == "__main__":
    main()
