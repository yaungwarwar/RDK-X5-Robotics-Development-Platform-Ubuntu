# Unified local QA

From the project root run:

```sh
./scripts/qa-full.sh
```

The command is workstation-only and uses synthetic/mock tests. It validates the recovered Python dependencies, Python Ruff lint/format and compilation, runs the Python suite once, checks dashboard and lab TypeScript/lint/format, builds both frontends from current inputs, runs real Nginx/proxy/security/WebSocket and Compose-profile validation, and runs both browser suites. It checks the immutable release archive/manifest and all three preserved laboratory bundle hashes before and after the tests. It does not connect to the RDK or install packages.

Defaults are project-local `.venv-recovered/bin/python`, `.venv-qa-tools/nginx/usr/sbin/nginx`, `.venv-qa-tools/bin/docker-compose`, `.venv-qa-tools/wheels`, and an existing Chromium installation under the user's Playwright cache. Set explicit absolute paths where needed:

```sh
RDK_QA_PYTHON=/path/to/python \
RDK_QA_NGINX=/path/to/nginx \
RDK_QA_COMPOSE=/path/to/docker-compose \
RDK_QA_CHROMIUM=/path/to/chrome \
RDK_QA_WHEELS=/path/to/persistent/wheels \
RDK_QA_OUTPUT=/path/to/qa-output \
  ./scripts/qa-full.sh
```

The cache is checked for availability; QA does not install from it. Node, npm, installed frontend dependencies and Linux `/proc` listener ownership visibility are required. The output defaults to ignored `qa-results/`, separate from release artifacts. `qa-report.json` records stages, exit status, timings, versions, test counts, warnings, artifact digests, owned listeners and cleanup. A unique run directory contains JUnit, Playwright JSON and proxy ownership evidence. Treat these results as local operational material and inspect before publication.

All listed validation stages are required; no optional stages are currently selected. Missing tools, occupied QA ports, test failures/skips/flaky tests, build changes during tests, listener ownership loss, cleanup failure and integrity mismatches return nonzero. QA ports 18088, 18089 and 18100 are checked before startup. The proxy and laboratory browser tests use only owned listeners, and verify served HTML and JavaScript against the just-built outputs. The runner guards service ownership during live/browser tests, then stops only its own processes and verifies listeners are gone. Non-atomic port preflight cannot prevent a race; ownership checks fail closed. The temporary Nginx QA config redirects error logs to a temporary file because a captured stderr pipe cannot always be reopened via `/dev/stderr`; no application Nginx config is changed.

The v0.1.3 recovery report and older test totals in [QA infrastructure](QA_INFRASTRUCTURE.md) are historical. Current status is [implementation status](IMPLEMENTATION_STATUS.md). Hardware validation, physical rollback and target resource isolation are separate pending work and are never inferred from this command.

## Canonical references and publication boundary

- Current scope and test status: [implementation status](IMPLEMENTATION_STATUS.md) and the latest Phase B completion report.
- Current QA procedure and machine output: this guide and `qa-results/qa-report.json`.
- Open and resolved engineering concerns: [findings register](ENGINEERING_FINDINGS_REGISTER.md).
- Provenance and future release process: [source provenance](SOURCE_PROVENANCE_REVIEW.md) and [release plan](RELEASE_REPRODUCIBILITY_PLAN.md).
- Historical physical observations: [v0.1.3 physical acceptance](V0.1.3_PHYSICAL_ACCEPTANCE.md) and [Phase B.1 completion](V0.2.0_PHASE_B1_COMPLETION.md); these are evidence, not current health reports.

Historical deployment, acceptance, incident and diagnostic documents may contain operational paths, addresses, usernames, transaction details or logs. Preserve the originals as local operator evidence; produce a reviewed redacted copy for publication. Never include credentials, backup contents, SSH keys, target-specific generated configurations or raw images. Do not assume an existing public copy has already been sanitized.
