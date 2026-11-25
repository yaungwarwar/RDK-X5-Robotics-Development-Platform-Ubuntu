# Upgrade transaction recovery

The upgrade creates a new private backup directory before preflight and records
progress atomically in `preparation.json`. The directory and `logs/` have mode
0700; journal and command log files have mode 0600. The journal contains a
transaction ID, paths, current and last successful states, pending stage, UTC
timestamp, failure details when applicable, and log references. Individual
command logs record operation, redacted arguments, timestamps, duration, exit
status, bounded output, truncation and execution or timeout errors. Output from
commands likely to contain complete environments is omitted. Redaction is
best-effort: review logs for sensitive information before sharing them.

Inspect either a backup directory, its preparation journal, or the activation
journal without changing it:

```bash
/usr/bin/python3 /path/to/staging/scripts/upgrade.py status --transaction /path/to/backup
/usr/bin/python3 /path/to/staging/scripts/upgrade.py diagnose --transaction /path/to/backup
```

Both commands show the journal and classify failed, prepared, active,
rolled-back and interrupted operations. A process killed or interrupted between
atomic updates can leave the last state and pending stage rather than FAILED;
it is not prepared. Inspect referenced logs in the backup directory. A `pip
check` failure includes its captured conflict message. Never apply without a
PREPARED journal and matching activation manifest.

For a failed or interrupted **preparation**, leave the staged tree, its venv,
and the backup directory untouched for investigation. Extract fresh source to
a new staging path and use a new backup path. Preparation does not support
resume, automatic cleanup or reuse of an unverified venv. Preparation does not
stop or replace the running installation.

For interrupted activation or rollback, retain the backup and consult the
activation journal and logs. The recovery copy in `backup/recovery/upgrade.py`
supports explicit rollback with `--transaction /path/to/backup/transaction.json`.
Automatic rollback failures are reported and recorded as FAILED; do not treat
them as a successful restoration. Resolve the recorded problem and review the
actual installed and backup paths before attempting recovery. No physical
upgrade or rollback has been validated with these changes.

## Direct migration paths

The v0.1.3 tool supports operational `/home/sunrise/rdk-platform` (0.1.2) to fresh `/home/sunrise/rdk-platform-0.1.3`, with new backup `/home/sunrise/rdk-backups/before-0.1.3`; rollback restores 0.1.2. Preserve `/home/sunrise/rdk-backups/before-0.1.2` and older transactions. The previous 0.1.0 → 0.1.2 recovery tool remains with its own backup. The active generated compatibility configuration is authoritative; do not use the stale base Compose file. Physical v0.1.3 upgrade and rollback remain unvalidated.
