import math
import os
import platform
import re
import socket
import stat
import subprocess
import time
from pathlib import Path
from typing import Protocol
import psutil
from app.models.telemetry import metric

DEVFREQ = {"bpu": "3a000000.bpu", "gpu": "3c000000.gc8000", "ddr": "soc:ddrc-freq"}


class HardwareAdapter(Protocol):
    mode: str

    def collect(self) -> dict: ...


def normalize_frequency(value: str | float, unit: str) -> float:
    multipliers = {"Hz": 1e-6, "kHz": 1e-3, "MHz": 1.0}
    if unit not in multipliers:
        raise ValueError("unverified frequency unit")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number * multipliers[unit] > 100000:
        raise ValueError("invalid frequency")
    return round(number * multipliers[unit], 6)


def temperature(value: str) -> float:
    number = float(value) / 1000
    if not math.isfinite(number) or not -50 <= number <= 200:
        raise ValueError("invalid temperature")
    return round(number, 3)


def bpu_ratio(raw):
    if not re.fullmatch(r"[0-9]{1,3}", raw):
        raise ValueError("BPU ratio must be an integer percentage")
    value = int(raw)
    if not 0 <= value <= 100:
        raise ValueError("BPU ratio outside 0–100 percent")
    return value


class SysfsReader:
    def __init__(self, sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev")):
        self.sys = sys_root
        self.dev = dev_root

    def read(self, path: Path, unit: str, convert=lambda x: x):
        try:
            value = convert(path.read_text().strip())
            return metric(value, unit, str(path))
        except FileNotFoundError:
            return metric(None, unit, str(path), "Interface not present")
        except PermissionError:
            return metric(None, unit, str(path), "Read permission denied")
        except (OSError, ValueError, OverflowError):
            return metric(None, unit, str(path), "Unreadable or invalid interface value", "error")

    def thermals(self):
        zones = list((self.sys / "class/thermal").glob("thermal_zone*"))
        result = {}
        for label, zone_type in [("cpu", "thermal-cpu"), ("ddr", "thermal-ddr")]:
            matches = []
            for zone in zones:
                try:
                    if (zone / "type").read_text().strip() == zone_type:
                        matches.append(zone)
                except OSError:
                    continue
            result[label] = (
                self.read(matches[0] / "temp", "°C", temperature)
                if matches
                else metric(
                    None, "°C", "sysfs thermal type=" + zone_type, "Matching thermal zone not found"
                )
            )
        cooling = []
        for device in sorted((self.sys / "class/thermal").glob("cooling_device*")):

            def state(s):
                n = int(s)
                if n < 0:
                    raise ValueError("negative cooling state")
                return n

            cooling.append(
                {
                    "name": device.name,
                    "type": self.read(device / "type", "text"),
                    "state": self.read(device / "cur_state", "state", state),
                    "max_state": self.read(device / "max_state", "state", state),
                }
            )
        result["cooling_devices"] = metric(cooling, "devices", "sysfs thermal")
        return result

    def frequency(self, name):
        path = self.sys / "class/devfreq" / DEVFREQ[name]
        result = {
            key: self.read(path / file, "MHz", lambda s: normalize_frequency(s, "Hz"))
            for key, file in [("current", "cur_freq"), ("min", "min_freq"), ("max", "max_freq")]
        }
        for file in ["governor", "available_governors", "available_frequencies"]:
            converter = (
                (lambda s: [normalize_frequency(v, "Hz") for v in s.split()])
                if file == "available_frequencies"
                else (lambda s: s.split())
                if file == "available_governors"
                else (lambda s: s)
            )
            result[file] = self.read(
                path / file, "MHz" if file == "available_frequencies" else "text", converter
            )
        return result

    def bpu_utilization(self):
        return self.read(self.sys / "devices/platform/soc/3a000000.bpu/ratio", "%", bpu_ratio)

    def bpu_devices(self):
        devices = []
        errors = []
        for name in ["bpu", "bpu_core0"]:
            path = self.dev / name
            try:
                if stat.S_ISCHR(path.stat().st_mode):
                    devices.append({"path": str(path), "readable": os.access(path, os.R_OK)})
            except FileNotFoundError:
                continue
            except OSError:
                errors.append(str(path))
        if errors:
            return metric(None, "devices", "devfs", "Device metadata inaccessible")
        return metric(
            devices or None,
            "devices",
            "devfs",
            None if devices else "Known BPU character devices not present",
        )


class NetworkRates:
    def __init__(self):
        self.previous = None

    def update(self, counters: dict, clock: float) -> dict:
        rates = {}
        for name, counter in counters.items():
            reason = "Waiting for second counter sample"
            rx = tx = None
            if self.previous and name in self.previous[1]:
                elapsed = clock - self.previous[0]
                old = self.previous[1][name]
                if (
                    elapsed > 0
                    and counter.bytes_recv >= old.bytes_recv
                    and counter.bytes_sent >= old.bytes_sent
                ):
                    rx = (counter.bytes_recv - old.bytes_recv) / elapsed
                    tx = (counter.bytes_sent - old.bytes_sent) / elapsed
                    reason = None
                else:
                    reason = "Counter reset or invalid sample interval"
            rates[name] = {
                "rx": metric(rx, "B/s", "psutil net_io_counters delta", reason),
                "tx": metric(tx, "B/s", "psutil net_io_counters delta", reason),
            }
        self.previous = (clock, counters)
        return rates


class NativeHardware:
    mode = "native"

    def __init__(
        self, storage_paths=None, reader=None, proc_root=Path("/proc"), temperature_settings=None
    ):
        self.reader = reader or SysfsReader()
        self.temperature_adapter = None
        self.temperature_settings = temperature_settings
        if temperature_settings is not None:
            from app.adapters.bpu_temperature import BpuTemperature

            self.temperature_adapter = BpuTemperature(temperature_settings)
        self.proc_root = proc_root
        self.storage_paths = storage_paths or ["/"]
        self.network_rates = NetworkRates()
        self.previous_cpu = None
        self.service_cache = None
        self.service_clock = -100.0

    def cpu(self):
        times = psutil.cpu_times(percpu=True)
        try:
            core_ids = [
                int(match.group(1))
                for line in (self.proc_root / "stat").read_text().splitlines()
                if (match := re.match(r"cpu(\d+)\s", line))
            ]
            if len(core_ids) != len(times):
                core_ids = None
        except OSError:
            core_ids = None
        totals = [sum(t) - getattr(t, "guest", 0) - getattr(t, "guest_nice", 0) for t in times]
        idle = [t.idle + getattr(t, "iowait", 0) for t in times]
        values = [None] * len(times)
        busy_sum = total_sum = 0.0
        invalid_delta = False
        if (
            self.previous_cpu
            and len(self.previous_cpu[0]) == len(times)
            and self.previous_cpu[2] == core_ids
        ):
            for i, total in enumerate(totals):
                delta = total - self.previous_cpu[0][i]
                idle_delta = idle[i] - self.previous_cpu[1][i]
                if delta < 0 or idle_delta < 0 or idle_delta > delta:
                    invalid_delta = True
                if delta > 0 and 0 <= idle_delta <= delta:
                    values[i] = round(100 * (delta - idle_delta) / delta, 2)
                    busy_sum += delta - idle_delta
                    total_sum += delta
        self.previous_cpu = (totals, idle, core_ids)

        def usage(v):
            return metric(
                v,
                "%",
                "procfs via psutil CPU time delta",
                "No positive CPU-time delta (warmup, reset, identity change, or zero-jiffy interval)"
                if v is None
                else None,
                "warming_up" if v is None else "ok",
            )

        frequencies = []
        for i in range(len(times)):
            if core_ids is None:
                frequencies.append(
                    metric(
                        None,
                        "MHz",
                        "procfs /stat and sysfs",
                        "CPU identity map unavailable or changed during sampling",
                    )
                )
                continue
            path = self.reader.sys / f"devices/system/cpu/cpu{core_ids[i]}/cpufreq/scaling_cur_freq"
            frequencies.append(
                self.reader.read(path, "MHz", lambda s: normalize_frequency(s, "kHz"))
            )
        return {
            "overall": usage(
                round(100 * busy_sum / total_sum, 2)
                if total_sum > 0 and not invalid_delta
                else None
            ),
            "core_ids": metric(
                core_ids,
                "CPU IDs",
                "procfs /stat",
                None
                if core_ids is not None
                else "CPU identity map unavailable or changed during sampling",
            ),
            "cores": [usage(v) for v in values],
            "frequencies": frequencies,
            "load_average": metric(list(os.getloadavg()), "1/5/15 min", "procfs loadavg"),
        }

    def memory(self):
        mem = psutil.virtual_memory()
        return {
            k: metric(v, u, "procfs via psutil")
            for k, v, u in [
                ("total", mem.total, "B"),
                ("available", mem.available, "B"),
                ("used", mem.total - mem.available, "B"),
                ("percent", (mem.total - mem.available) / mem.total * 100, "%"),
            ]
        }

    def storage(self):
        entries = []
        for path in self.storage_paths:
            try:
                disk = psutil.disk_usage(path)
                entries.append(
                    {
                        "path": path,
                        "total": metric(disk.total, "B", "statvfs"),
                        "used": metric(disk.used, "B", "statvfs"),
                        "free": metric(disk.free, "B", "statvfs"),
                        "percent": metric(disk.percent, "%", "statvfs"),
                    }
                )
            except OSError:
                entries.append(
                    {
                        "path": path,
                        **{
                            key: metric(None, unit, "statvfs", "Storage path unavailable")
                            for key, unit in [
                                ("total", "B"),
                                ("used", "B"),
                                ("free", "B"),
                                ("percent", "%"),
                            ]
                        },
                    }
                )
        return {"volumes": entries}

    def network(self):
        try:
            counters = psutil.net_io_counters(pernic=True, nowrap=False)
        except OSError:
            counters = {}
        rates = self.network_rates.update(counters, time.monotonic())
        try:
            stats = psutil.net_if_stats()
        except OSError:
            stats = {}
        try:
            addresses = psutil.net_if_addrs()
            addresses_available = True
        except OSError:
            addresses = {}
            addresses_available = False
        entries = []
        for name in sorted(set(addresses) | set(counters) | set(stats)):
            interface = stats.get(name)
            entries.append(
                {
                    "name": name,
                    "addresses": metric(
                        [
                            a.address
                            for a in addresses.get(name, [])
                            if a.family in (socket.AF_INET, socket.AF_INET6)
                        ]
                        if addresses_available
                        else None,
                        "IP addresses",
                        "psutil",
                        None if addresses_available else "Interface addresses inaccessible",
                    ),
                    "up": metric(
                        interface.isup if interface else None,
                        "boolean",
                        "psutil",
                        None if interface else "Interface state unavailable",
                    ),
                    **rates.get(
                        name,
                        {
                            k: metric(None, "B/s", "psutil", "Counters unavailable")
                            for k in ["rx", "tx"]
                        },
                    ),
                }
            )
        return {"interfaces": entries}

    def services(self):
        if self.service_cache is not None and time.monotonic() - self.service_clock < 10:
            return self.service_cache
        result = {}
        for service in ["docker", "containerd"]:
            try:
                proc = subprocess.run(
                    [
                        "/usr/bin/systemctl",
                        "show",
                        service + ".service",
                        "--property=LoadState,ActiveState,SubState",
                        "--no-pager",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_PAGER": ""},
                )
                fields = dict(
                    line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
                )
                if (
                    proc.returncode != 0
                    or fields.get("LoadState") != "loaded"
                    or fields.get("ActiveState")
                    not in {
                        "active",
                        "inactive",
                        "failed",
                        "activating",
                        "deactivating",
                        "reloading",
                        "maintenance",
                        "refreshing",
                    }
                ):
                    raise ValueError("Service not loaded or systemd unavailable")
                result[service] = metric(
                    {"active": fields["ActiveState"], "sub": fields.get("SubState", "unknown")},
                    "state",
                    "systemctl show (read-only)",
                )
            except (OSError, subprocess.TimeoutExpired, ValueError):
                result[service] = metric(
                    None,
                    "state",
                    "systemctl show",
                    "Service unavailable, permission denied, or query timed out",
                )
        result["inventory"] = metric(
            None,
            "containers",
            "not collected",
            "Container inventory is outside this release; no Docker socket access",
        )
        self.service_cache = result
        self.service_clock = time.monotonic()
        return result

    def collect(self):
        try:
            os_name = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
        except OSError:
            os_name = platform.system()
        system = {
            key: metric(value, unit, source)
            for key, value, unit, source in [
                ("hostname", socket.gethostname(), "text", "gethostname"),
                ("os", os_name, "text", "os-release"),
                ("kernel", platform.release(), "text", "uname"),
                ("architecture", platform.machine(), "text", "uname"),
                ("uptime", max(0, time.time() - psutil.boot_time()), "s", "procfs via psutil"),
            ]
        }
        thermal = self.reader.thermals()
        from app.adapters.bpu_temperature import temperature_report

        dedicated = (
            self.temperature_adapter.poll()
            if self.temperature_adapter is not None
            else metric(
                None,
                "°C",
                "hwmon name=pvt / temp2_input",
                "Isolated temperature adapter not configured",
            )
        )
        bpu_temperatures = temperature_report(
            dedicated,
            thermal["cpu"],
            self.temperature_settings.bpu_cpu_proxy_enabled if self.temperature_settings else False,
        )
        return {
            "system": system,
            "cpu": self.cpu(),
            "memory": self.memory(),
            "storage": self.storage(),
            "thermal": thermal,
            "bpu": {
                "devices": self.reader.bpu_devices(),
                "frequency": self.reader.frequency("bpu"),
                "utilization": self.reader.bpu_utilization(),
                **bpu_temperatures,
            },
            "frequencies": {
                "gpu": self.reader.frequency("gpu"),
                "ddr": self.reader.frequency("ddr"),
            },
            "network": self.network(),
        }

    def close(self):
        if self.temperature_adapter is not None:
            self.temperature_adapter.close()
