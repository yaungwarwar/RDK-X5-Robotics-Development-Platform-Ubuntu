"""One bounded subprocess slot; worker stdout uses the framed IPC protocol."""

import asyncio
import os
import re
import time
from pathlib import Path

import anyio

from native_protocol import MAX_PAYLOAD, read_record

WORKER = Path(__file__).with_name("native_worker.py")
START_TIMEOUT = 12
STOP_TIMEOUT = 3
RECORD_TIMEOUT = 15


class NativeSupervisor:
    def __init__(self, command=None):
        self.command = command
        self.process = None
        self.reader_task = None
        self.stderr_task = None
        self.stderr_tail = b""
        self.error = None
        self.ready = None
        self.reserved = False
        self.last_cpu = None
        self.owner = None
        self.stopping = False
        self.stopped_event = None
        self.cleanup_task = None

    def metrics(self):
        if not self.process or self.process.returncode is not None:
            return {"worker_rss_kib": None, "worker_cpu_pct": None}
        try:
            root = Path("/proc") / str(self.process.pid)
            status = (root / "status").read_text()
            rss = next(
                int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")
            )
            stat = (root / "stat").read_text().rsplit(")", 1)[1].split()
            cpu = (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")
            now = time.monotonic()
            percent = (
                None
                if self.last_cpu is None
                else round(100 * (cpu - self.last_cpu[1]) / (now - self.last_cpu[0]), 2)
            )
            self.last_cpu = (now, cpu)
            return {"worker_rss_kib": rss, "worker_cpu_pct": percent}
        except (OSError, ValueError, IndexError, StopIteration, ZeroDivisionError):
            return {"worker_rss_kib": None, "worker_cpu_pct": None}

    async def drain_stderr(self):
        while True:
            data = await self.process.stderr.read(1024)
            if not data:
                return
            self.stderr_tail = (self.stderr_tail + data)[-2048:]

    async def start(self, view, image_format, slot, owner=None):
        if self.reserved and self.stopping and self.stopped_event is not None:
            try:
                await asyncio.wait_for(self.stopped_event.wait(), STOP_TIMEOUT * 2 + 2)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Previous native worker is still stopping") from exc
        if self.reserved or self.process is not None:
            raise RuntimeError("Native preview already active")
        if (
            view not in ("left", "right", "combined")
            or image_format not in ("raw", "compressed")
            or (image_format == "compressed" and view != "combined")
        ):
            raise ValueError("Unsupported native view or format")
        self.reserved = True
        self.stopping = False
        self.stopped_event = asyncio.Event()
        self.cleanup_task = None
        self.stderr_tail = b""
        self.error = None
        self.owner = owner
        env = os.environ.copy()
        env.pop("PYTHONHOME", None)
        ros_pythonpath = env.pop("RDK_LAB_ROS_PYTHONPATH", None)
        if ros_pythonpath is not None:
            env["PYTHONPATH"] = ros_pythonpath
        cmd = self.command or [
            "/usr/bin/python3",
            "-u",
            str(WORKER),
            "--view",
            view,
            "--format",
            image_format,
        ]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=MAX_PAYLOAD + 8192,
            )
            self.stderr_task = asyncio.create_task(self.drain_stderr())
            head, _ = await asyncio.wait_for(read_record(self.process.stdout), START_TIMEOUT)
            if head["type"] != "ready" or head.get("view") != view:
                raise ValueError("Native worker did not send valid readiness")
            self.ready = head
            self.reader_task = asyncio.create_task(self.read_frames(slot, view))
        except BaseException as exc:
            with anyio.CancelScope(shield=True):
                await self.stop()
            if isinstance(exc, asyncio.CancelledError):
                raise
            tail = self.stderr_tail.decode("utf-8", "replace")[-512:]
            tail = " ".join("".join(c if c.isprintable() else " " for c in tail).split())
            tail = re.sub(
                r"(?i)(password|token|secret|authorization)([=: ]+)[^ ,;]+", r"\1\2[redacted]", tail
            )
            raise RuntimeError((str(exc) + ("; " + tail if tail else ""))[-300:]) from exc

    async def read_frames(self, slot, view):
        try:
            while True:
                header, data = await asyncio.wait_for(
                    read_record(self.process.stdout), RECORD_TIMEOUT
                )
                if header["type"] == "frame":
                    width, height = header.get("width"), header.get("height")
                    mime = header.get("mime")
                    if (
                        header.get("view") != view
                        or mime not in ("image/png", "image/jpeg")
                        or type(width) is not int
                        or type(height) is not int
                        or not 1 <= width <= 1280
                        or not 1 <= height <= 1280
                    ):
                        raise ValueError("Invalid frame metadata")
                    if (mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n")) or (
                        mime == "image/jpeg" and not data.startswith(b"\xff\xd8")
                    ):
                        raise ValueError("Invalid image payload")
                    slot.publish_native(data, header)
                elif header["type"] == "error":
                    self.error = str(header.get("message", "Invalid image"))[:160]
                    if header.get("invalid_frames") is not None:
                        self.error += f" (invalid messages: {header['invalid_frames']})"
                    if header.get("diagnostic_overflow"):
                        self.error += (
                            f" (diagnostic queue overflow: {header['diagnostic_overflow']})"
                        )
                    slot.report_error(self.error)
                elif header["type"] == "status":
                    count = header.get("publishers")
                    if type(count) is not int or not 0 <= count <= 100000:
                        raise ValueError("Invalid publisher count")
                    slot.publishers = count
                    slot.status_pending = True
                    slot.event.set()
                else:
                    raise ValueError("Unexpected IPC record")
        except asyncio.CancelledError:
            raise
        except (Exception, asyncio.IncompleteReadError) as exc:
            self.error = "Native worker disconnected: " + str(exc)[:120]
            slot.report_error(self.error, fatal=True)

    async def stop(self):
        if self.cleanup_task is None:
            self.stopping = True
            self.cleanup_task = asyncio.create_task(self._stop_impl())
        await asyncio.shield(self.cleanup_task)

    async def _stop_impl(self):
        if self.reader_task:
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            self.reader_task = None
        proc = self.process
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
                except asyncio.TimeoutError:
                    self.error = "Native worker could not be reaped"
                    raise RuntimeError(self.error)
        if self.stderr_task:
            try:
                await asyncio.wait_for(self.stderr_task, 1)
            except asyncio.TimeoutError:
                self.stderr_task.cancel()
            self.stderr_task = None
        self.process = None
        self.reserved = False
        self.last_cpu = None
        self.owner = None
        self.stopping = False
        if self.stopped_event is not None:
            self.stopped_event.set()
