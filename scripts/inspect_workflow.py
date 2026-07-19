"""Print the normalized, testable contract of the delivery workflow."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_WORKFLOW = Path(".github/workflows/army-morning-brief.yml")
ACTION_PATTERN = re.compile(
    r"uses:\s+(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})\s+#\s+(?P<release>v\S+)"
)
SECRET_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CHANNEL_ID")
RECIPIENT_EXPRESSION = "${{ secrets.TELEGRAM_CHAT_ID }},${{ secrets.TELEGRAM_CHANNEL_ID }}"


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected a YAML mapping")
    return value


def _steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = _mapping(document.get("jobs"))
    job = _mapping(jobs.get("briefing"))
    value = job.get("steps")
    if not isinstance(value, list) or not all(isinstance(step, dict) for step in value):
        raise ValueError("briefing steps must be a list of mappings")
    return value


def _step_by_id(steps: list[dict[str, Any]], step_id: str) -> dict[str, Any]:
    try:
        return next(step for step in steps if step.get("id") == step_id)
    except StopIteration:
        raise ValueError(f"missing step id: {step_id}") from None


def _step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    try:
        return next(step for step in steps if step.get("name") == name)
    except StopIteration:
        raise ValueError(f"missing step name: {name}") from None


def _boolean(value: Any) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"expected YAML boolean text, got {value!r}")


def _condition(step: dict[str, Any]) -> str:
    value = step.get("if")
    if not isinstance(value, str):
        raise ValueError("step condition must be text")
    return " ".join(value.removeprefix("${{").removesuffix("}}").split())


def inspect_workflow(path: Path) -> dict[str, object]:
    """Load with BaseLoader so YAML 1.1 never coerces the top-level ``on`` key."""
    raw = path.read_text(encoding="utf-8")
    document = _mapping(yaml.load(raw, Loader=yaml.BaseLoader))
    triggers = _mapping(document.get("on"))
    schedule = triggers.get("schedule")
    if not isinstance(schedule, list):
        raise ValueError("schedule must be a list")
    crons = [str(_mapping(item).get("cron")) for item in schedule]
    dispatch = _mapping(triggers.get("workflow_dispatch"))
    force_send = _mapping(_mapping(dispatch.get("inputs")).get("force_send"))

    permissions = _mapping(document.get("permissions"))
    concurrency = _mapping(document.get("concurrency"))
    job = _mapping(_mapping(document.get("jobs")).get("briefing"))
    steps = _steps(document)
    setup_python = _step_by_name(steps, "Set up Python")
    setup_uv = _step_by_name(steps, "Set up uv")
    sync = _step_by_name(steps, "Install frozen dependencies")
    date = _step_by_id(steps, "kst_date")
    restore = _step_by_id(steps, "sent_marker")
    dry_run = _step_by_name(steps, "Manual dry-run")
    send = _step_by_id(steps, "send")
    create_marker = _step_by_name(steps, "Create successful scheduled-send marker")
    save = _step_by_name(steps, "Save successful scheduled-send marker")
    safe_log = _step_by_name(steps, "Log safe trigger type")

    action_pins = {
        match.group("action"): {
            "release": match.group("release"),
            "sha": match.group("sha"),
        }
        for match in ACTION_PATTERN.finditer(raw)
    }
    send_condition = _condition(send)
    success_condition = "github.event_name == 'schedule' && steps.send.outcome == 'success'"
    secret_steps = [
        step
        for step in steps
        if isinstance(step.get("env"), dict)
        and any(
            name in key or name in str(value)
            for key, value in _mapping(step["env"]).items()
            for name in SECRET_NAMES
        )
    ]
    all_commands = "\n".join(str(step.get("run", "")) for step in steps)
    restore_index = steps.index(restore)
    send_index = steps.index(send)
    create_index = steps.index(create_marker)
    save_index = steps.index(save)

    return {
        "actions": action_pins,
        "commands": {
            "dry_run": str(dry_run.get("run", "")).strip(),
            "send": str(send.get("run", "")).strip(),
            "sync": str(sync.get("run", "")).strip(),
        },
        "concurrency": {
            "cancel_in_progress": _boolean(concurrency.get("cancel-in-progress")),
            "group": concurrency.get("group"),
        },
        "duplicate_guard": {
            "cache_key": _mapping(restore.get("with")).get("key"),
            "cache_path": _mapping(restore.get("with")).get("path"),
            "date_command": "TZ=Asia/Seoul date +%F"
            if "TZ=Asia/Seoul date +%F" in str(date.get("run"))
            else None,
            "restore_before_send": restore_index < send_index,
            "save_after_successful_scheduled_send": (
                send_index < create_index < save_index
                and _condition(create_marker) == success_condition
                and _condition(save) == success_condition
            ),
            "scheduled_send_condition": (
                "github.event_name == 'schedule' && steps.sent_marker.outputs.cache-hit != 'true'"
                if "github.event_name == 'schedule'" in send_condition
                and "steps.sent_marker.outputs.cache-hit != 'true'" in send_condition
                else None
            ),
        },
        "job": {
            "python": _mapping(setup_python.get("with")).get("python-version"),
            "runner": job.get("runs-on"),
            "timeout_minutes": int(str(job.get("timeout-minutes"))),
            "uv": _mapping(setup_uv.get("with")).get("version"),
        },
        "manual": {
            "false_is_dry_run": _condition(dry_run)
            == "github.event_name == 'workflow_dispatch' && inputs.force_send == false",
            "force_send_bypasses_guard": (
                "github.event_name == 'workflow_dispatch' && inputs.force_send == true"
                in send_condition
            ),
            "input": {
                "default": _boolean(force_send.get("default")),
                "required": _boolean(force_send.get("required")),
                "type": force_send.get("type"),
            },
        },
        "permissions": {"contents": permissions.get("contents")},
        "secrets": {
            "command_arguments": "${{ secrets." in all_commands
            or "--token" in all_commands
            or "--chat-id" in all_commands,
            "names": list(SECRET_NAMES),
            "only_on_send_step": secret_steps == [send]
            and _mapping(send.get("env"))
            == {
                "TELEGRAM_BOT_TOKEN": "${{ secrets.TELEGRAM_BOT_TOKEN }}",
                "TELEGRAM_CHAT_ID": RECIPIENT_EXPRESSION,
            },
            "recipient_expression": _mapping(send.get("env")).get("TELEGRAM_CHAT_ID"),
        },
        "trigger": {
            "safe_log": str(safe_log.get("run", ""))
            .strip()
            .removeprefix('echo "')
            .removesuffix('"'),
            "schedule": crons,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", nargs="?", type=Path, default=DEFAULT_WORKFLOW)
    arguments = parser.parse_args()
    print(
        json.dumps(
            inspect_workflow(arguments.workflow), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
