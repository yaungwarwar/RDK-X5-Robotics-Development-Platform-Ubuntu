# ROS2 logging compatibility: RDK-COMPAT-002

The user reports that on the physical RDK X5, `rclpy` imported but
`rclpy.init(args=[])` failed under the service's mount namespace with:

```text
RuntimeError: Failed opening file <service-home>/.ros/log/<log-file> for writing: Read-only file system
```

Three controlled tests as the configured service user in that service namespace showed: (A) default
initialization failed as above; (B) setting ROS_LOG_DIR to a private writable
temporary directory succeeded; (C) initialization with
`["--ros-args", "--disable-external-lib-logs"]` succeeded. The user also
reports that interactive execution of the original graph probe completed in
3.387 seconds and found the GS130WI node and seven image/calibration topics.

The confirmed cause is external ROS library log-file creation under the
read-only home. The v0.1.3 fixed system-Python subprocess uses option C. Python
exceptions and stderr remain available; the bounded diagnostic excerpt retains
the tail so the final exception is visible. The eight-second default and native
ROS environment remain unchanged. No writable home exception is introduced;
ProtectHome, ProtectSystem, PrivateTmp and other service protections stay intact.

The option was experimentally validated in the v0.1.2 service namespace by the
user, but the v0.1.3 application has not been physically tested. After a
controlled upgrade, check actual graph discovery, camera publishers, elapsed
probe time, error and stale-data behavior, ROS environment, and security
properties. Physical rollback and dynamic BPU load testing remain pending.
