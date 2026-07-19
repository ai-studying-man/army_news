from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "army-morning-brief.yml"
INSPECTOR = ROOT / "scripts" / "inspect_workflow.py"


def test_c003_workflow_contract_is_pinned_safe_and_duplicate_guarded() -> None:
    assert WORKFLOW.is_file(), "C003 workflow must exist"
    assert INSPECTOR.is_file(), "C003 workflow inspector must exist"

    completed = subprocess.run(
        [sys.executable, str(INSPECTOR), str(WORKFLOW)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    contract = json.loads(completed.stdout)

    assert contract == {
        "actions": {
            "actions/cache/restore": {
                "release": "v5.0.5",
                "sha": "27d5ce7f107fe9357f9df03efb73ab90386fccae",
            },
            "actions/cache/save": {
                "release": "v5.0.5",
                "sha": "27d5ce7f107fe9357f9df03efb73ab90386fccae",
            },
            "actions/checkout": {
                "release": "v6.0.2",
                "sha": "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            },
            "actions/setup-python": {
                "release": "v6.3.0",
                "sha": "ece7cb06caefa5fff74198d8649806c4678c61a1",
            },
            "astral-sh/setup-uv": {
                "release": "v8.1.0",
                "sha": "08807647e7069bb48b6ef5acd8ec9567f424441b",
            },
        },
        "commands": {
            "dry_run": "uv run --frozen python -m army_morning_brief --dry-run",
            "send": "uv run --frozen python -m army_morning_brief --send",
            "sync": "uv sync --frozen --dev",
        },
        "concurrency": {
            "cancel_in_progress": False,
            "group": "army-morning-brief-delivery",
        },
        "duplicate_guard": {
            "cache_key": "army-morning-brief-sent-${{ steps.kst_date.outputs.kst_date }}",
            "cache_path": ".cache/army-morning-brief",
            "date_command": "TZ=Asia/Seoul date +%F",
            "restore_before_send": True,
            "save_after_successful_scheduled_send": True,
            "scheduled_send_condition": (
                "github.event_name == 'schedule' && steps.sent_marker.outputs.cache-hit != 'true'"
            ),
        },
        "job": {
            "python": "3.12",
            "runner": "ubuntu-latest",
            "timeout_minutes": 20,
            "uv": "0.11.28",
        },
        "manual": {
            "false_is_dry_run": True,
            "force_send_bypasses_guard": True,
            "input": {"default": False, "required": True, "type": "boolean"},
        },
        "permissions": {"contents": "read"},
        "secrets": {
            "command_arguments": False,
            "names": [
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
                "TELEGRAM_CHANNEL_ID",
            ],
            "only_on_send_step": True,
            "recipient_expression": (
                "${{ secrets.TELEGRAM_CHAT_ID }},${{ secrets.TELEGRAM_CHANNEL_ID }}"
            ),
        },
        "trigger": {
            "safe_log": "trigger=${{ github.event_name }}",
            "schedule": ["30 21 * * *"],
        },
    }

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert "--token" not in workflow_text
    assert "--chat-id" not in workflow_text
