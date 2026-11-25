"""Native system-Python ROS2 image subscriber. No camera capture or ROS imports in broker."""

import argparse
import binascii
import math
import queue
import re
import struct
import sys
import threading
import time
import zlib

from native_protocol import MAX_PAYLOAD, pack_record

TOPICS = {
    "left": ("/image_left_raw", ["/image_left_raw/camera_info"]),
    "right": ("/image_right_raw", ["/image_right_raw/camera_info"]),
    "combined": (
        "/image_combine_raw",
        ["/image_combine_raw/left/camera_info", "/image_combine_raw/right/camera_info"],
    ),
}
MAX_WIDTH, MAX_HEIGHT = 1280, 1280
# Keep the original raw-byte ceiling despite increasing the height bound.
MAX_RAW = 1280 * 720 * 3


def chunk(tag, payload):
    return (
        struct.pack("!I", len(payload))
        + tag
        + payload
        + struct.pack("!I", binascii.crc32(tag + payload) & 0xFFFFFFFF)
    )


def raw_to_png(msg):
    width, height, step = int(msg.width), int(msg.height), int(msg.step)
    if len(msg.encoding) > 64:
        raise ValueError("raw encoding exceeds limit")
    encoding = str(msg.encoding).lower()
    channels = {"rgb8": 3, "bgr8": 3, "mono8": 1, "nv12": 1}.get(encoding)
    if channels is None:
        raise ValueError("unsupported raw encoding: " + encoding[:64])
    height_limit = MAX_HEIGHT if encoding == "nv12" else 720
    if not 1 <= width <= MAX_WIDTH or not 1 <= height <= height_limit:
        raise ValueError("raw dimensions exceed limit")
    if encoding == "nv12" and (width % 2 or height % 2 or step % 2):
        raise ValueError("NV12 dimensions and stride must be even")
    expected = step * height * (3 if encoding == "nv12" else 2) // 2
    if step < width * channels or step > width * channels + 4096 or expected > MAX_RAW:
        raise ValueError("invalid or oversized row stride")
    if len(msg.data) != expected:
        raise ValueError("raw data length mismatch")
    data = memoryview(msg.data)
    rows = bytearray()
    for y in range(height):
        row = data[y * step : y * step + width * channels]
        if encoding == "bgr8":
            row = bytes(
                component
                for x in range(0, len(row), 3)
                for component in (row[x + 2], row[x + 1], row[x])
            )
        rows.extend(b"\x00")
        rows.extend(row)

    hdr = struct.pack("!IIBBBBB", width, height, 8, 0 if channels == 1 else 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", hdr)
        + chunk(b"IDAT", zlib.compress(rows, 3))
        + chunk(b"IEND", b"")
    )
    if len(png) > MAX_PAYLOAD:
        raise ValueError("encoded frame exceeds limit")
    return png, "image/png", width, height, encoding


def compressed_image(msg):
    if len(msg.format) > 128:
        raise ValueError("compressed format exceeds limit")
    fmt = str(msg.format).lower().strip()
    if not 0 < len(msg.data) <= MAX_PAYLOAD:
        raise ValueError("compressed frame exceeds limit or is empty")
    data = bytes(msg.data)
    if not data or len(data) > MAX_PAYLOAD:
        raise ValueError("compressed frame exceeds limit or is empty")
    token = re.search(r"(?:^|[;\s])(png|jpeg|jpg)(?=$|[;\s])", fmt)
    if token and token.group(1) == "png":
        if (
            len(data) < 33
            or not data.startswith(b"\x89PNG\r\n\x1a\n")
            or data[12:16] != b"IHDR"
            or data[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ):
            raise ValueError("invalid PNG container")
        width, height = struct.unpack("!II", data[16:24])
        position = 8
        chunks = 0
        has_data = False
        while position < len(data):
            if position + 12 > len(data):
                raise ValueError("truncated PNG chunk")
            length = struct.unpack("!I", data[position : position + 4])[0]
            end = position + 12 + length
            if end > len(data):
                raise ValueError("truncated PNG chunk")
            tag = data[position + 4 : position + 8]
            expected = struct.unpack("!I", data[end - 4 : end])[0]
            if binascii.crc32(data[position + 4 : end - 4]) & 0xFFFFFFFF != expected:
                raise ValueError("invalid PNG checksum")
            if chunks == 0 and (tag != b"IHDR" or length != 13):
                raise ValueError("invalid PNG header")
            if tag == b"IDAT":
                has_data = True
            chunks += 1
            if chunks > 256:
                raise ValueError("too many PNG chunks")
            position = end
            if tag == b"IEND":
                if length or position != len(data) or not has_data:
                    raise ValueError("invalid PNG end")
                break
        if position != len(data) or not has_data or tag != b"IEND":
            raise ValueError("invalid PNG container")
        mime = "image/png"
    elif token and token.group(1) in ("jpeg", "jpg"):
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("invalid JPEG container")
        width = height = None
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 255:
                raise ValueError("invalid JPEG marker")
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in (0xD9, 0xDA):
                break
            if marker in range(0xD0, 0xD8) or marker == 1:
                continue
            if pos + 2 > len(data):
                raise ValueError("invalid JPEG length")
            size = int.from_bytes(data[pos : pos + 2], "big")
            if size < 2 or pos + size > len(data):
                raise ValueError("invalid JPEG segment")
            if marker in (0xC0, 0xC1, 0xC2):
                if size < 8:
                    raise ValueError("invalid JPEG dimensions")
                height, width = struct.unpack("!HH", data[pos + 3 : pos + 7])
                break
            pos += size
        if width is None:
            raise ValueError("JPEG dimensions unavailable")
        mime = "image/jpeg"
    else:
        raise ValueError("unsupported compressed format: " + fmt[:64])
    if not 1 <= width <= MAX_WIDTH or not 1 <= height <= 720:
        raise ValueError("compressed dimensions exceed limit")
    return data, mime, width, height, fmt[:64]


def calibration(msg):
    def numbers(values, limit):
        if len(values) > limit:
            raise ValueError("invalid calibration")
        values = [float(v) for v in values]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("invalid calibration")
        return values

    k = numbers(msg.k, 9)
    d = numbers(msg.d, 16)
    if len(k) != 9 or len(str(msg.distortion_model)) > 64:
        raise ValueError("invalid calibration")
    width, height = int(msg.width), int(msg.height)
    if not 0 <= width <= MAX_WIDTH or not 0 <= height <= MAX_HEIGHT:
        raise ValueError("invalid calibration dimensions")
    return {
        "width": width,
        "height": height,
        "model": str(msg.distortion_model),
        "k": k,
        "d": d,
        "calibrated": k[0] != 0,
    }


class Writer:
    def __init__(self, stream):
        self.stream = stream
        self.frames = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.first_written = threading.Event()
        self.dropped = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def offer(self, header, payload=b""):
        packet = pack_record(header, payload)
        try:
            self.frames.put_nowait(packet)
        except queue.Full:
            try:
                self.frames.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            self.frames.put_nowait(packet)

    def run(self):
        while not self.closed.is_set():
            try:
                packet = self.frames.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.stream.write(packet)
                self.stream.flush()
                self.first_written.set()
            except (BrokenPipeError, OSError):
                self.closed.set()
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", required=True, choices=TOPICS)
    parser.add_argument("--format", choices=("raw", "compressed"), default="raw")
    args = parser.parse_args()
    if args.format == "compressed" and args.view != "combined":
        parser.error("compressed topic only configured for combined view")
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from sensor_msgs.msg import CameraInfo, CompressedImage, Image

    writer = Writer(sys.stdout.buffer)
    rclpy.init(args=["--ros-args", "--disable-external-lib-logs"])
    node = rclpy.create_node(
        "rdk_camera_lab_preview", enable_rosout=False, start_parameter_services=False
    )
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=1, reliability=ReliabilityPolicy.BEST_EFFORT
    )
    topic, info_topics = TOPICS[args.view]
    if args.format == "compressed":
        topic = "/image_combine_jpeg"
    cal = {}
    last = [0.0]
    seq = [0]
    errors = [0]

    def image_callback(msg):
        now = time.monotonic()
        if now - last[0] < 0.2:
            return
        last[0] = now
        try:
            data, mime, width, height, encoding = (
                compressed_image(msg) if args.format == "compressed" else raw_to_png(msg)
            )
            seq[0] += 1
            stamp = getattr(getattr(msg, "header", None), "stamp", None)
            capture = (
                None if stamp is None else {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)}
            )
            writer.offer(
                {
                    "type": "frame",
                    "sequence": seq[0],
                    "view": args.view,
                    "mime": mime,
                    "width": width,
                    "height": height,
                    "encoding": encoding,
                    "display_mode": "grayscale luminance (NV12)"
                    if encoding == "nv12"
                    else "native color/mono",
                    "calibration": cal,
                    "source_stamp": capture,
                    "worker_dropped": writer.dropped,
                    "invalid_frames": errors[0],
                },
                data,
            )
        except (ValueError, TypeError, OverflowError) as exc:
            errors[0] += 1
            writer.offer({"type": "error", "message": str(exc)[:160], "invalid_frames": errors[0]})

    def on_info(msg, name):
        try:
            cal[name] = calibration(msg)
        except (ValueError, TypeError, OverflowError):
            cal.pop(name, None)

    try:
        node.create_subscription(
            CompressedImage if args.format == "compressed" else Image, topic, image_callback, qos
        )
        for name in info_topics:
            node.create_subscription(CameraInfo, name, lambda msg, n=name: on_info(msg, n), qos)
        writer.offer({"type": "ready", "topic": topic, "view": args.view})
        if not writer.first_written.wait(2):
            raise RuntimeError("IPC startup failed")
        heartbeat_at = time.monotonic()
        while rclpy.ok() and not writer.closed.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() - heartbeat_at >= 5:
                writer.offer({"type": "status", "publishers": node.count_publishers(topic)})
                heartbeat_at = time.monotonic()
    finally:
        node.destroy_node()
        rclpy.shutdown()
        writer.closed.set()


if __name__ == "__main__":
    main()
