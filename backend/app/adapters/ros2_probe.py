"""Fixed read-only subprocess, using system Python and native rclpy; never subscribe."""

import json
import time


def main():
    import rclpy

    rclpy.init(args=["--ros-args", "--disable-external-lib-logs"])
    node = rclpy.create_node(
        "rdk_control_center_monitor", enable_rosout=False, start_parameter_services=False
    )
    try:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        nodes = sorted(
            set((ns.rstrip("/") + "/" + name) for name, ns in node.get_node_names_and_namespaces())
        )
        topics = [
            {"name": name, "types": types, "publishers": node.count_publishers(name)}
            for name, types in node.get_topic_names_and_types()
        ]
        if len(nodes) > 2048 or len(topics) > 4096:
            raise RuntimeError("Graph exceeds monitoring limits")
        encoded = json.dumps({"nodes": nodes, "topics": topics})
        if len(encoded) > 2_000_000:
            raise RuntimeError("Graph output exceeds monitoring limits")
        print(encoded)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
