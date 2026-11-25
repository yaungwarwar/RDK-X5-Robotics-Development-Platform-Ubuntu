"""Fixed read-only sysfs probe. No vendor utility, profiler, permissions or hardware writes."""

import json
from pathlib import Path


def read_sensor(path):
    try:
        with path.open() as stream:
            raw = stream.read(64).strip()
        # Helper communicates raw numeric text; parent validates units/ranges.
        return {"raw": raw, "source": str(path), "error": None}
    except FileNotFoundError:
        return {"raw": None, "source": str(path), "error": "Sensor interface missing"}
    except PermissionError:
        return {"raw": None, "source": str(path), "error": "Sensor read permission denied"}
    except OSError as error:
        return {
            "raw": None,
            "source": str(path),
            "error": f"Sensor read failed (errno {error.errno})",
        }


def discover(root=Path("/sys/class/hwmon")):
    for directory in sorted(root.glob("hwmon*")):
        try:
            if (directory / "name").read_text().strip() == "pvt":
                return directory
        except OSError:
            continue
    return None


def main():
    device = discover()
    if device is None:
        print(
            json.dumps(
                {
                    "dedicated": {
                        "raw": None,
                        "source": "hwmon name=pvt / temp2_input",
                        "error": "hwmon device named pvt not found",
                    }
                }
            ),
            flush=True,
        )
        return
    # Only the dedicated BPU sensor is read here. The optional CPU proxy reuses
    # the already-working thermal-cpu observation, avoiding another risky read.
    print(json.dumps({"dedicated": read_sensor(device / "temp2_input")}), flush=True)


if __name__ == "__main__":
    main()
