"""Fixture only; emits a synthetic ROS-style image and calibration."""

import os
import time


def init(args):
    assert args == ["--ros-args", "--disable-external-lib-logs"]


def create_node(name, **kwargs):
    assert name == "rdk_camera_lab_preview" and not kwargs["enable_rosout"]
    return Node()


def ok():
    return True


def spin_once(node, timeout_sec):
    if not node.sent:
        node.sent = True
        for message, topic, callback, _ in sorted(
            node.subscriptions, key=lambda item: not item[1].endswith("/camera_info")
        ):
            if topic.endswith("/camera_info"):
                m = message()
                m.width = 2
                m.height = 1
                m.distortion_model = "plumb_bob"
                m.k = [1, 0, 0, 0, 1, 0, 0, 0, 1]
                m.d = []
            else:
                m = message()
                if os.environ.get("FAKE_ROS_NV12") == "1":
                    m.width = 1088
                    m.height = 1280
                    m.step = 1088
                    m.encoding = "nv12"
                    m.data = bytes([128]) * 2_088_960
                else:
                    m.width = 2
                    m.height = 1
                    m.step = 6
                    m.encoding = "rgb8"
                    m.data = b"\xff\x00\x00\x00\xff\x00"
            callback(m)
    time.sleep(min(timeout_sec, 0.05))


def shutdown():
    pass


class Node:
    def __init__(self):
        self.subscriptions = []
        self.sent = False

    def create_subscription(self, message, topic, callback, qos):
        self.subscriptions.append((message, topic, callback, qos))

    def count_publishers(self, topic):
        return 1

    def destroy_node(self):
        pass
