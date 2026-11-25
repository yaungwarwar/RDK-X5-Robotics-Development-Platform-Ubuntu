from app.version import VERSION
import asyncio
import copy
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from app.models.telemetry import freshen, now


class Monitor:
    def __init__(self, hardware, ros2, settings):
        self.hardware, self.ros2, self.settings = hardware, ros2, settings
        self.history = deque(maxlen=settings.history_size)
        self.latest = None
        self.sequence = 0
        self.task = None
        self.slow_task = None
        self.auxiliary = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rdk-sampler")
        self.error = None

    def sample(self):
        started = time.monotonic()
        try:
            data = self.hardware.collect()
            data.update(self.auxiliary)
            self.sequence += 1
            sample = {
                "version": VERSION,
                "mode": self.hardware.mode,
                "timestamp": now(),
                "sequence": self.sequence,
                "interval_seconds": self.settings.interval_seconds,
                "stale_after_seconds": self.settings.stale_after_seconds,
                "collection_seconds": round(time.monotonic() - started, 3),
                "data": data,
            }
            self.latest = sample
            self.history.append(sample)
            self.error = None
        except Exception:
            logging.exception("Telemetry collection failed")
            self.error = "Collection failed; last successful readings retained"

    def sample_auxiliary(self):
        try:
            data = self.ros2.collect()
            if callable(getattr(self.hardware, "services", None)):
                data["services"] = self.hardware.services()
            self.auxiliary = data
        except Exception:
            logging.exception("Auxiliary collection failed; cached graph retained")

    async def start(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, self.sample_auxiliary)
        await loop.run_in_executor(self.executor, self.sample)
        self.task = asyncio.create_task(self.run())
        self.slow_task = asyncio.create_task(self.run_auxiliary())

    async def run(self):
        delay = self.settings.interval_seconds
        while True:
            await asyncio.sleep(delay)
            started = time.monotonic()
            await asyncio.get_running_loop().run_in_executor(self.executor, self.sample)
            delay = max(0.05, self.settings.interval_seconds - (time.monotonic() - started))

    async def run_auxiliary(self):
        while True:
            await asyncio.sleep(self.settings.ros2_interval_seconds)
            await asyncio.get_running_loop().run_in_executor(self.executor, self.sample_auxiliary)

    async def stop(self):
        for task in [self.task, self.slow_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.executor.shutdown(wait=True, cancel_futures=True)
        if callable(getattr(self.hardware, "close", None)):
            self.hardware.close()

    def snapshot(self):
        latest = self.latest
        if latest is None:
            return None
        result = freshen(copy.deepcopy(latest), self.settings.stale_after_seconds)
        for section in ["ros2", "cameras", "services"]:
            if section in latest["data"]:
                result["data"][section] = freshen(
                    copy.deepcopy(latest["data"][section]),
                    max(
                        self.settings.stale_after_seconds, self.settings.ros2_interval_seconds * 2.5
                    ),
                )
        result["data"]["bpu"]["temperature"] = freshen(
            copy.deepcopy(latest["data"]["bpu"]["temperature"]),
            max(
                self.settings.stale_after_seconds,
                self.settings.bpu_temperature_interval_seconds * 2.5,
            ),
        )
        result["age_seconds"] = max(
            0.0,
            (
                datetime.now(timezone.utc) - datetime.fromisoformat(result["timestamp"])
            ).total_seconds(),
        )
        result["stale"] = result["age_seconds"] > self.settings.stale_after_seconds
        result["collector_error"] = self.error
        return result
