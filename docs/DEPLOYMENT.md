# Historical v0.1.2 → v0.1.3 deployment

The native ARM64 upgrade used fresh staging and backup directories. Preparation resolved the active generated Compose configuration from `.deployment/active.json`. The operator inspected the PREPARED journal, isolated venv, backup, recovery scripts, actual generated configuration, image identity and isolation settings before activation.

Activation used the stable recovery copy in the new backup. Native health, loopback dashboard access, telemetry and ROS2 discovery were verified. The original transaction identifiers, private paths and operational commands are retained in the operator record. Physical rollback remains untested.

See [physical acceptance](V0.1.3_PHYSICAL_ACCEPTANCE.md), [transaction recovery](UPGRADE_RECOVERY.md) and the [current laboratory acceptance gates](V0.2.0_PHASE_B5_ACCEPTANCE_PLAN.md). The separate laboratory bundle requires its own authorization and installation outside the active application.

## Historical command reference

During a separately authorized v0.1.2 → v0.1.3 maintenance window, the operator selects the existing installation, fresh extracted staging tree and unused backup directory in the private runbook. The examples use those absolute paths through shell variables. Preparation must succeed before inspecting the generated configuration, image backup, security settings and transaction state.

```bash
/usr/bin/python3 "${RDK_STAGE:?set verified staging path}/scripts/upgrade.py" prepare \
  --release "$RDK_STAGE" --backup "${RDK_BACKUP:?set unused backup path}"
```

After inspecting PREPARED and confirming the activation window, use the recovery copy for that transaction. Verify service and dashboard health and the loopback configuration after activation.

```bash
/usr/bin/python3 "${RDK_BACKUP:?set prepared backup path}/recovery/upgrade.py" apply \
  --transaction "$RDK_BACKUP/transaction.json"
```

```bash
(cd "${RDK_INSTALL:?set existing installation path}" && ./scripts/healthcheck.sh && ./scripts/compose.sh ps)
systemctl status rdk-control-center.service --no-pager
```
