# Operations

The workflow runs at `30 21 * * *` UTC, which is 06:30 KST the next day. GitHub Actions
schedules are best-effort: a queued run can start later, and GitHub may disable scheduled workflows
after 60 days without repository activity in a public repository. The collection window ends at the
actual run time, so a delayed run has a later window end.

## Local dry-run

Use Python 3.12 and the lock file. This collects only configured public HTTPS sources and prints the
briefing without calling Telegram.

```powershell
uv sync --frozen --dev
uv run --frozen python -m army_morning_brief --dry-run
```

Do not add private, authenticated, operational, location, movement, strength, or deployment sources.
Review dry-run output for public-source safety before enabling delivery.

## GitHub setup and manual runs

Add these repository or environment secrets in GitHub Settings > Secrets and variables > Actions:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Credential handoff is currently pending: this change has not written or validated Telegram
credentials. After an authorized operator adds them, first run a manual dry-run:

```powershell
gh workflow run army-morning-brief.yml -f force_send=false
```

After reviewing that run, an explicit manual resend bypasses the scheduled date guard:

```powershell
gh workflow run army-morning-brief.yml -f force_send=true
```

The workflow logs only the trigger type. Telegram secrets are environment variables only on the send
step and are never command-line arguments.

## Duplicate guard and delivery limits

Scheduled runs restore an exact cache key containing the current KST date. A marker is saved only after
that scheduled send succeeds. One static concurrency group serializes scheduled and manual runs to
prevent overlapping delivery races. Manual `force_send=true` intentionally ignores the marker; manual
`false` always performs a dry-run.

This is an at-least-once guard, not a transactional ledger. If Telegram accepts a message and the runner
crashes before the marker is saved, a retry can send it again. GitHub can evict cache entries, after
which a rerun for that KST date can send again. Inspect Actions history before a forced resend. This
workflow does not call the Actions API or write secrets.

Inspect the normalized workflow contract locally with:

```powershell
uv run --frozen python scripts/inspect_workflow.py
```
