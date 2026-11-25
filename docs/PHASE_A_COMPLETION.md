# Phase A: upgrade transaction reliability

## Implemented

- Atomic, private preparation journal with transaction ID, stage, last
  successful stage, pending operation, timestamp, release and backup paths,
  failure details and diagnostic log references; PREPARED activation guard.
- Private per-command logs with duration, status, bounded streaming output,
  timeout and launch failures, redacted arguments and output. Environment-bearing
  command output is omitted. A failing `pip check` exposes its conflict text.
- Journal states for preparation, activation and rollback; failed rollback is
  recorded and propagated. Inspection is read-only and classifies interrupted
  preparation separately from completed or failed states. Fresh retry is
  documented; no resume or cleanup is performed.
- Focused simulations cover preparation failures, interrupted backup,
  incomplete-preparation refusal, health failure, rollback failure, atomic
  replacement, logging bounds, permissions, redaction and status inspection.

## Validation

Python 3.10.22: `python -m pytest -q tests/unit/test_deployment.py
tests/unit/test_dependency_isolation.py` — **57 passed, 0 failed**.
Ruff lint and Ruff formatting checks passed for the three modified Python files;
Python compile checks passed for those files. No browser tests, physical target
operations or release packaging were performed in this phase.

## Acceptance and remaining limits

The requested focused Phase A implementation and local checks are complete.
Redaction is heuristic, not a guarantee that arbitrary program output contains
no secrets; inspect logs before sharing. The command output retained for logs
is limited, and excessively large stdout fails the command rather than being
used as incomplete configuration. Abrupt process or machine termination cannot
mark the journal FAILED; its recorded pending stage identifies the interrupted
work. Physical ARM64 upgrade and recovery remain unvalidated. Version migration,
release-wide regression and packaging remain outside this phase; this is not a
release-readiness determination.
