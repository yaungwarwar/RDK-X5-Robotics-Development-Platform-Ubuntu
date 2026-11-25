"""Validate both generated hardware profiles with real Compose, without Docker daemon access."""

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cgroup_compat as compat


def main():
    executable = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [executable, "-f", str(root / "compose.yaml"), "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    original = json.loads(result.stdout)
    for cpu in [False, True]:
        report = {"controllers": {"cpu": cpu, "memory": True, "pids": True}, "warnings": []}
        configured = copy.deepcopy(original)
        configured["services"]["dashboard"]["cpus"] = 0.5
        profile = compat.generate(configured, report)
        with tempfile.TemporaryDirectory(prefix="rdk-compose-profile-") as tmp:
            file = compat.write_bundle(Path(tmp) / "bundle", profile, report)
            validated = subprocess.run(
                [executable, "-f", str(file), "config", "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            service = json.loads(validated.stdout)["services"]["dashboard"]
            assert int(service["mem_limit"]) == 100663296 and service["pids_limit"] == 64
            assert (
                service["user"] == "101:101"
                and service["read_only"]
                and service["cap_drop"] == ["ALL"]
            )
            assert ("cpus" in service) == cpu
            assert (
                service["network_mode"] == "host"
                and not service.get("ports")
                and not service.get("devices")
            )
    print(
        "COMPOSE: generated CPU-supported and CPU-unavailable profiles validated; memory/PID/security controls retained"
    )


if __name__ == "__main__":
    main()
