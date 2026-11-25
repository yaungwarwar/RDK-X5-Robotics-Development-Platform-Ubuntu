"""Polled single subprocess slot: even an unkillable sysfs read cannot add workers."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from app.models.telemetry import metric
from app.adapters.hardware import temperature


class BpuTemperature:
    def __init__(self, settings, popen=subprocess.Popen, clock=time.monotonic):
        self.settings, self.popen, self.clock = settings, popen, clock
        self.process = None
        self.started = 0.0
        self.next_attempt = 0.0
        self.failures = 0
        self.timed_out = False
        self.measurement = metric(
            None, "°C", "hwmon name=pvt / temp2_input", "Dedicated BPU sensor not sampled yet"
        )

    def failure(self, reason):
        self.failures += 1
        self.measurement = metric(None, "°C", "hwmon name=pvt / temp2_input", reason, "error")
        delay = min(
            self.settings.bpu_temperature_max_backoff_seconds,
            self.settings.bpu_temperature_interval_seconds * 2 ** min(self.failures - 1, 10),
        )
        self.next_attempt = self.clock() + delay

    def poll(self):
        # Called by the fast sampler: nonblocking pipe reads/polls only, no wait().
        if self.process is not None:
            if self.process.poll() is None:
                if (
                    not self.timed_out
                    and self.clock() - self.started >= self.settings.bpu_temperature_timeout_seconds
                ):
                    self.timed_out = True
                    self.failure(
                        "Dedicated BPU temperature read timed out; retry waits for helper exit and backoff"
                    )
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                return self.measurement
            if not self.timed_out:
                try:
                    raw = self.process.stdout.read(8193)
                    if not raw or len(raw) > 8192 or self.process.returncode != 0:
                        raise ValueError("invalid helper result")
                    payload = json.loads(raw)["dedicated"]
                    # Only a known discovered hwmon temp2_input may identify BPU.
                    source = payload["source"]
                    if not isinstance(source, str) or not (
                        source == "hwmon name=pvt / temp2_input"
                        or (re.fullmatch(r"/sys/class/hwmon/hwmon[0-9]+/temp2_input", source))
                    ):
                        raise ValueError("unexpected source")
                    if payload["error"]:
                        self.failure(payload["error"])
                        self.measurement["source"] = source
                    else:
                        if not isinstance(payload["raw"], str) or not re.fullmatch(
                            r"-?[0-9]{1,9}", payload["raw"]
                        ):
                            raise ValueError("Expected integer millidegrees Celsius")
                        value = temperature(payload["raw"])
                        self.measurement = metric(value, "°C", source)
                        self.failures = 0
                        self.next_attempt = (
                            self.clock() + self.settings.bpu_temperature_interval_seconds
                        )
                except (OSError, ValueError, KeyError, TypeError):
                    self.failure("Dedicated BPU temperature helper returned an invalid result")
            self.process.stdout.close()
            self.process = None
        if self.process is None and self.clock() >= self.next_attempt:
            try:
                self.process = self.popen(
                    [sys.executable, str(Path(__file__).with_name("bpu_temperature_probe.py"))],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                os.set_blocking(self.process.stdout.fileno(), False)
                self.started = self.clock()
                self.timed_out = False
            except OSError:
                self.failure("Dedicated BPU sensor helper could not start or configure its pipe")
                # Retain any child already created; never lose ownership of a live slot.
                if self.process is not None and self.process.poll() is None:
                    self.process.kill()
                    self.timed_out = True
        return self.measurement

    def close(self):
        if self.process is not None:
            if self.process.poll() is None and not self.timed_out:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
            # No blocking wait: a D-state kernel read may not be interruptible.
            if self.process.poll() is not None:
                self.process.stdout.close()
                self.process = None


def temperature_report(dedicated, cpu, proxy_enabled):
    use_proxy = dedicated["value"] is None and proxy_enabled and cpu["value"] is not None
    if use_proxy:
        proxy = dict(cpu)
        proxy["reason"] = (
            "CPU-temperature proxy only; not an independently measured BPU temperature"
        )
    else:
        proxy = metric(
            None,
            "°C",
            "thermal-cpu (optional CPU proxy)",
            "Proxy disabled"
            if not proxy_enabled
            else "Proxy not needed or CPU temperature unavailable",
        )
    return {
        "temperature": dedicated,
        "cpu_temperature_proxy": proxy,
        "temperature_fallback": metric(
            "cpu_proxy"
            if use_proxy
            else "none"
            if dedicated["value"] is not None
            else "unavailable",
            "state",
            "BPU temperature policy",
            "Dedicated BPU measurement is never replaced by CPU temperature",
        ),
    }
