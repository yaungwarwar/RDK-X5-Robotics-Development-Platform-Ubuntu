# Stationary camera laboratory procedure

The [B.5 acceptance checklist](V0.2.0_PHASE_B5_ACCEPTANCE_PLAN.md) governs future runs. The previous Phase B instructions described an earlier bundle and frame limits. Keep target connection details, local paths and execution records in the private operator copy.

1. Obtain the cooling confirmation and separate authorization for read-only preflight. Record installed service health, camera process identity and the thermal baseline. Stop if the required publisher is absent. The operator controls the existing camera application.
2. During authorized graph inspection, use the installed ROS environment and query `ros2 topic list -t` and `ros2 topic info -v` for the selected image and calibration topics. Record types, counts and offered QoS. Measuring encoding, stride, dimensions or calibration values requires a separately authorized subscription.
3. For authorized preparation, use the reviewed standalone archive and its manifest. Choose a fresh private laboratory directory and isolated broker venv. The native ROS worker uses system Python. Verify the loopback listener, private tunnel, effective limits and deadline using the B.5 gates before streaming.
4. Follow the view-specific acceptance and stop conditions in the checklist. Verify owned-worker, subscription, listener and tunnel cleanup even on an abort. Retain measurements and event ordering in private evidence. Leave the existing camera and monitoring service running.
