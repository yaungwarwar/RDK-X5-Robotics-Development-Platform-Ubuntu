#!/usr/bin/env python3
"""Run pytest with a bounded selector poll if socketpair wakeups are denied.

Some restricted test sandboxes deny socket.send even on a local socketpair.
The application and its security policy are untouched. On those hosts only,
periodic selector wakeups let asyncio observe queued cross-thread callbacks.
"""

import errno
import selectors
import socket
import sys

import pytest


def configure_selector():
    left, right = socket.socketpair()
    try:
        try:
            right.send(b"x")
        except PermissionError as error:
            if error.errno != errno.EPERM:
                raise
            original = selectors.DefaultSelector.select

            def select_with_poll(self, timeout=None):
                return original(self, min(timeout, 0.05) if timeout is not None else 0.05)

            selectors.DefaultSelector.select = select_with_poll
            print("QA: socket wakeup denied; using periodic selector polling", file=sys.stderr)
    finally:
        left.close()
        right.close()


if __name__ == "__main__":
    configure_selector()
    raise SystemExit(pytest.main(sys.argv[1:]))
