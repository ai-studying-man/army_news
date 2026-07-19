# Operations

Army News shares DAPA News's collection, publishing, and Telegram delivery architecture, but not
its topic or collection schedule. Army News collects from D-1 14:00 KST through D-day 05:00 KST
and delivers at 06:30 KST. The workflow runs at `30 21 * * *` UTC, which is 06:30 KST the next day.
GitHub Actions schedules are best-effort: a queued run can start later, and GitHub may disable
scheduled workflows after 60 days without repository activity in a public repository. A delayed
workflow must still honor the fixed 05:00 KST collection cutoff.

The Army News scope uses these aliases: `육군`, `8사단`, `8기동사단`, `3070부대`, and `오뚜기부대`.
Regional monitoring covers `양주`, `동두천`, `포천`, `연천`, and `의정부`. Alcohol incidents
and natural disasters qualify when the configured region and allowed subject are present; they do
not require Army context. Military-related municipal work or events require the relevant military
or Army context to be confirmed.

## Local dry-run

Use Python 3.12 and the lock file. This collects only the code-reviewed public HTTPS sources and
prints the briefing without calling Telegram. Division names, aliases, and regions may be replaced
without a code change through `ARMY_BRIEF_CONFIG_JSON`:

```json
{
  "divisions": [
    {
      "name": "제8기동사단",
      "aliases": ["육군", "8사단", "8기동사단", "3070부대", "오뚜기부대"],
      "regions": ["양주", "동두천", "포천", "연천", "의정부"]
    }
  ]
}
```

The same object is accepted by `BriefConfig.from_mapping` and `BriefConfig.from_env`; malformed
JSON, empty strings, and duplicate aliases fail validation. Source URLs and priorities are not
environment-configurable in this release. The initial list is explicitly code-reviewed in
`src/army_morning_brief/sources.py`: 국방부 보도자료 (100), 국방부 공지사항 (80), Google News
RSS for division aliases (60), and Google News RSS for regions (40).

```powershell
uv sync --frozen --dev
uv run --frozen python -m army_morning_brief --dry-run
```

Do not add private, authenticated, operational, location, movement, strength, or deployment sources.
Review dry-run output for public-source safety before enabling delivery.

Collection is bounded and failure-isolated: transient HTTP/transport errors retry at most twice per
source, with a 60-second source budget and capped backoff. The pipeline canonicalizes URLs and uses
event anchors to retain one representative original per incident while keeping distinct state,
country, region, and training/safety events separate.

## GitHub setup and manual runs

Add these repository or environment secrets in GitHub Settings > Secrets and variables > Actions.
Both values are GitHub Secrets; never commit a bot token or chat ID to this repository:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Credential handoff is currently pending: this change has not written or validated Telegram
credentials. No real send is allowed until `TELEGRAM_CHAT_ID` exists. If a token is exposed in chat,
revoke and rotate it before production. After an authorized operator adds the rotated secrets, first
run a manual dry-run:

```powershell
gh workflow run army-morning-brief.yml -f force_send=false
```

After reviewing that run, an explicit manual resend bypasses the scheduled date guard:

```powershell
gh workflow run army-morning-brief.yml -f force_send=true
```

The workflow logs only the trigger type. Telegram secrets are environment variables only on the send
step and are never command-line arguments.

## Message format and duplicate handling

Keep only the representative original article for each incident; do not send syndicated duplicates.
Each item is exactly three logical lines, with a blank line between items. Telegram HTML renders the
HTTPS URL line as an escaped clickable `<a href="…">…</a>` link:

```text
■ [사단] 기사 제목 (신문명)
기사 URL
- 한두문장으로 기사 요약
```

Use `[지역]` instead of `[사단]` for a regional item.

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
