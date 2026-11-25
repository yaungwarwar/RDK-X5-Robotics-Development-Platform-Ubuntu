# RDK Control Center 0.1.2 release candidate

**Locally validated release candidate, approved for controlled physical upgrade testing.**
This is not a claim of physical validation or production certification.

The user reports the final unrestricted workstation QA completed with exit 0:
192 Python and 12 browser tests passed (204 total), including both Nginx
configurations, real proxy, REST, security headers, mutation rejection,
WebSocket reconnection and foreign-origin rejection. One existing Starlette
TestClient deprecation warning remains. Codex separately validated 192 Python
tests and isolated AMD64 application dependencies; Codex's network sandbox
denied TCP sockets, so the real proxy/browser result is user-provided.

The supported migration is 0.1.0 → 0.1.2, with rollback to 0.1.0. Preserve
the failed 0.1.1 staging and backup directories. The archive contains one
`rdk-platform/` root; use the commands in `docs/DEPLOYMENT.md`, inspect a
successful preparation and backup, and explicitly apply only after review.

The 0.1.1 X5 preparation failed because visible zope-event 5.1.1 required
setuptools >=75.8.2 while the staged environment saw 59.6.0; the exact package
shadowing locations remain unverified. The 0.1.1 cgroup detector was physically
observed reporting cgroup v2/systemd, unavailable CPU quota, and available
memory and PID controllers. Physical v0.1.2 ARM64 dependency installation,
upgrade/rollback, BPU dynamic utilization and dedicated temperature, and native
ROS2 service discovery remain unvalidated.

Default access is loopback-only through an SSH tunnel; authentication and TLS
are not implemented. The fixed `systemctl show` command has a one-second timeout
but no explicit output byte cap. Credential redaction is best-effort; review
diagnostics before sharing. Full details and physical checklist are in the
archive documentation.

Archive SHA-256: `d23c1248a44f18ba8878a0443a1b923b95b1401fff86af67ef7a8b49731cd1cd`.
The separate release source manifest records each archived source file; the
original 67-file Phase C manifest is preserved under `docs/` in the archive.
