"""One fixed-command slot; bounded pipe capture, deadline, no shell or stuck-worker growth."""

import os
import selectors
import subprocess
import time


class CommandBusy(RuntimeError):
    pass


class OutputLimit(RuntimeError):
    pass


class BoundedCommand:
    def __init__(self, env=None):
        self.process = None
        self.env = env

    def run(self, argv, timeout, max_stdout=2_000_000, max_stderr=4096):
        if self.process is not None:
            if self.process.poll() is None:
                raise CommandBusy("Previous probe has not exited; no replacement spawned")
            self.process = None
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=self.env,
        )
        self.process = process
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + timeout
        try:
            for stream, name in [(process.stdout, "stdout"), (process.stderr, "stderr")]:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout, stderr=bytes(buffers["stderr"]))
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    limit = max_stdout if key.data == "stdout" else max_stderr
                    buffer = buffers[key.data]
                    if key.data == "stdout" and len(buffer) + len(data) > limit:
                        raise OutputLimit("Probe stdout exceeded the graph limit")
                    if key.data == "stderr":
                        buffer.extend(data)
                        if len(buffer) > limit:
                            del buffer[: len(buffer) - limit]
                    else:
                        buffer.extend(data[: max(0, limit - len(buffer))])
            return subprocess.CompletedProcess(
                argv,
                process.returncode,
                buffers["stdout"].decode("utf-8", "strict"),
                buffers["stderr"].decode("utf-8", "replace"),
            )
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass  # Keep the single slot occupied until the kernel releases it.
            for stream in [process.stdout, process.stderr]:
                stream.close()
            if process.poll() is not None:
                self.process = None
