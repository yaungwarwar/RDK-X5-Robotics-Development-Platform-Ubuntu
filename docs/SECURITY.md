# Security

The user reports successful local workstation proxy, origin, mutation and
security-header validation for the 0.1.2 release candidate; physical acceptance
is pending. The fixed `systemctl show` subprocess has a one-second timeout but
no explicit captured-output byte cap. Diagnostic credential redaction is
best-effort; review logs before sharing. This is not an independent security audit.

Version 0.1.2 is read-only and **has no authentication or TLS termination**. It discloses hostname, platform details, network addresses, resource measurements and ROS2 graph names. Anyone able to reach the dashboard/API in an allowed network context can read them. Host and origin validation are browser protections, not an identity system; non-browser clients can set those headers.

The default deployment binds dashboard 127.0.0.1:8088 and backend 127.0.0.1:8089. Prefer the documented SSH tunnel. Optional LAN binding is for explicitly trusted networks only. Do not expose it to the Internet, route it through an unauthenticated public proxy or use Docker TCP. Authentication, TLS, role-based controls and multi-user operation are outside v0.1.2.

## Implemented controls

- Only GET API routes and server-push telemetry. No command, upload, hardware write, capture, service-control or arbitrary file endpoints.
- Fixed full executable paths and argument arrays for `systemctl show` and the ROS2 probe; `shell=True` and command interpolation are never used. Commands have fixed deadlines. No passwordless sudo or sudo in the backend.
- Pydantic configuration rejects extra fields, wildcards, unsupported modes, malformed origins, traversal and command-like storage paths. Only a trusted local operator can edit config or select its startup path.
- Exact allowed hosts (TrustedHostMiddleware) and exact allowed origins (CORS and WebSocket checks). Missing/foreign WebSocket Origin is denied. This is why command-line WebSocket clients need an explicit accepted Origin.
- Nginx rejects non-GET/HEAD methods and untrusted WebSocket origins. It adds CSP, frame denial, no-sniff, no-referrer, permissions restrictions and no-store headers. Inline styles are permitted for chart/bar positions; inline scripts and external runtime assets are forbidden. HTTP, not HTTPS, is intentional on loopback/tunnels.
- Uvicorn binds only loopback, disables trusting proxy headers and runs one worker. A remote proxy is not configured.
- systemd runs as sunrise, drops capabilities, uses no-new-privileges and read-only system/home protection, blocks kernel/control-group modifications, and hides Docker/containerd sockets. Native drivers are never installed or edited.
- Nginx runs uid/gid 101 with all capabilities dropped, no-new-privileges, read-only root, bounded tmpfs and resource limits. No privileged mode, hardware devices, host filesystem tree or Docker socket mount. Host networking is needed only to reach the native loopback backend; it is not network isolation.
- No Docker API calls, TCP endpoints or socket-based inventory. Systemd state is queried without changing services.
- No telemetry persistence by default, no remote fonts or analytics, no stored secrets. OpenTelemetry API is a transitive FastAPI dependency; no exporter or remote telemetry is configured.
- History/client buffering is bounded. Failed collection retains aging data visibly. Shutdown and reconnect behavior are tested.

A local process running as the same user or root remains trusted and can edit source/config, access loopback or impersonate a frontend client. Docker group membership already grants extensive host privileges; this project does not add it or alter Docker daemon settings. A compromised frontend container has host network visibility despite lacking privileges. Never assume this dashboard can secure an otherwise untrusted host.

## Operation and maintenance

Keep the source and config writable only by the target operator. Keep SSH credentials outside the project. Python dependencies are installed into an isolated venv with access to system packages only for vendor compatibility; no global sudo pip. Review dependency updates and re-run tests before deployment. Frontend uses a lockfile; runtime Python versions and relevant transitives are pinned. Container base tags are multi-architecture tags and should be rebuilt/scanned before a production installation; a Docker-image vulnerability scan was not possible in this session.

The installer refuses non-ARM64/non-X5/non-Ubuntu-22.04 environments, root execution, the wrong user/path, an existing virtual environment or an existing service unit. It never runs automatically. A failed install may leave a new venv/image; remove only this application's failed artifacts after inspection and retry. It does not install OS packages or modify vendor/ROS2/Docker configuration.

Baseline JSON files contain hostnames and addresses. The collection script creates new files exclusively with mode 0600 and refuses replacement. Treat those files as operational information and exclude them, logs, environment files, key material and credentials from transfers or publication.

See [DEPLOYMENT.md](DEPLOYMENT.md) for startup, access and rollback. No SSH connection, remote install, deployment or workstation service mutation was performed during implementation.

## 0.1.1 maintenance boundaries

The backend never executes hrut_somstatus: the user's utility inspection identified conditional profiler writes. Utilization and dedicated temperature use direct read-only interfaces. Temperature child quarantine and ROS2 bounded subprocess capture/timeout prevent worker/process accumulation under errors. Dedicated BPU temperature is never populated with a CPU proxy.

Only explicitly invoked installation/upgrade scripts use Docker CLI and ordinary interactive sudo for this application's unit. They are not API endpoints or background monitoring actions. They reject remote TCP/SSH Docker contexts, preserve non-root/read-only/capability/no-new-privileges/loopback controls and require effective memory/PID isolation. They never write cgroup subtree controls or alter watchdog/kernel/global Docker settings. Unit/drop-ins remain unchanged across upgrade; hashes stop activation when administrator edits would be lost.

Backups are created in private directories and can contain administrator configuration/venv/source. Do not publish them. The environment diagnostic prints only allowlisted discovery variables; profile values are hashed, not dumped. Sanitized stderr can still disclose operational paths; review before sharing. Physical acceptance is still needed for the new paths; prior 0.1.0 physical success is user-reported evidence, not a new security/performance audit.
