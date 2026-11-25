"""Small, versioned and bounded worker-to-broker binary protocol."""

import json
import struct

VERSION = 1
MAX_HEADER = 4096
MAX_PAYLOAD = 2 * 1024 * 1024
PREFIX = struct.Struct("!II")


def pack_record(header, payload=b""):
    header = dict(header, version=VERSION)
    raw = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
    if not raw or len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError("IPC record exceeds limit")
    return PREFIX.pack(len(raw), len(payload)) + raw + payload


async def read_record(reader):
    prefix = await reader.readexactly(PREFIX.size)
    header_size, payload_size = PREFIX.unpack(prefix)
    if not 0 < header_size <= MAX_HEADER or payload_size > MAX_PAYLOAD:
        raise ValueError("IPC length exceeds limit")
    try:

        def reject_constant(value):
            raise ValueError("invalid JSON constant: " + value)

        header = json.loads(await reader.readexactly(header_size), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid IPC header") from exc
    if not isinstance(header, dict) or header.get("version") != VERSION:
        raise ValueError("unsupported IPC version")
    if header.get("type") not in ("ready", "frame", "error", "status"):
        raise ValueError("invalid IPC message type")
    payload = await reader.readexactly(payload_size)
    if header["type"] != "frame" and payload:
        raise ValueError("payload not allowed")
    if header["type"] == "frame" and not payload:
        raise ValueError("empty frame")
    return header, payload
