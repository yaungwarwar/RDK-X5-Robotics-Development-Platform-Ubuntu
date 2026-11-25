# Manual v0.1.2 → v0.1.3 upgrade (development)

> Historical operator procedure: target-specific paths and addresses belong in private operator records; review and redact a copy before publication.

The user reports v0.1.2 is physically active on the RDK X5. The v0.1.3 release is not physically validated; do not deploy until the requested local validation and release artifact are complete. Preserve `/home/sunrise/rdk-backups/before-0.1.2` and all older transactions. Use a fresh staging tree and backup. This upgrade supports only 0.1.2 → 0.1.3, with rollback to 0.1.2. Use the active generated compatibility deployment, not the old base Compose file. Preparation resolves `.deployment/active.json`, validates the path, and rejects an explicit mismatching `--compose-file`.

After a release archive and checksum have been verified and transferred manually to `/home/sunrise/rdk-incoming`:

```bash
cd /home/sunrise/rdk-incoming
sha256sum -c rdk-control-center-0.1.3.tar.gz.sha256
mkdir -m 700 /home/sunrise/rdk-platform-0.1.3 && tar -xzf rdk-control-center-0.1.3.tar.gz --strip-components=1 -C /home/sunrise/rdk-platform-0.1.3
/usr/bin/python3 /home/sunrise/rdk-platform-0.1.3/scripts/upgrade.py prepare --release /home/sunrise/rdk-platform-0.1.3 --backup /home/sunrise/rdk-backups/before-0.1.3
/usr/bin/python3 /home/sunrise/rdk-platform-0.1.3/scripts/upgrade.py status --transaction /home/sunrise/rdk-backups/before-0.1.3
/usr/bin/python3 /home/sunrise/rdk-platform-0.1.3/scripts/upgrade.py diagnose --transaction /home/sunrise/rdk-backups/before-0.1.3
cat /home/sunrise/rdk-backups/before-0.1.3/compatibility.json
cat /home/sunrise/rdk-backups/before-0.1.3/transaction.json
ls -lh /home/sunrise/rdk-backups/before-0.1.3/frontend-image.tar
```

Inspect the backup, active deployment, generated compatibility configuration, image and security limits before activation. CPU quota must remain omitted where unavailable; memory/PID limits, unprivileged container, read-only filesystem, dropped capabilities, no-new-privileges, loopback access and systemd hardening remain required. If preparation fails, retain all evidence and retry only with new paths. Do not overwrite old backups.

After review, explicitly activate and check health:

```bash
/usr/bin/python3 /home/sunrise/rdk-backups/before-0.1.3/recovery/upgrade.py apply --transaction /home/sunrise/rdk-backups/before-0.1.3/transaction.json
cd /home/sunrise/rdk-platform
./scripts/healthcheck.sh
./scripts/compose.sh ps
systemctl status rdk-control-center.service --no-pager
curl -fsS http://127.0.0.1:8089/api/v1/ros2
```

For explicit rollback, including interrupted directory moves:

```bash
/usr/bin/python3 /home/sunrise/rdk-backups/before-0.1.3/recovery/upgrade.py rollback --transaction /home/sunrise/rdk-backups/before-0.1.3/transaction.json
```

Review the ROS2 graph and camera publisher diagnostics. Physical v0.1.3 initialization, dynamic BPU load and physical rollback remain unvalidated. Use the loopback dashboard through the established SSH tunnel. No authentication or TLS is provided. See `ROS2_LOGGING_COMPATIBILITY.md`, `UPGRADE_RECOVERY.md` and historical Phase D documentation.
