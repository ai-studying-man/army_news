"""Configurable monitoring rules and collection time window."""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import cast

KST = timezone(timedelta(hours=9), name="KST")
CONFIG_ENV_VAR = "ARMY_BRIEF_CONFIG_JSON"


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence of strings")
    items = tuple(cast(Sequence[object], value))
    if not items or not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError(f"{field_name} must contain non-empty strings")
    strings = cast(tuple[str, ...], items)
    if len(set(strings)) != len(strings):
        raise ValueError(f"{field_name} must not contain duplicates")
    return strings


@dataclass(frozen=True, slots=True)
class DivisionRule:
    name: str
    aliases: tuple[str, ...]
    regions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("division name must not be empty")
        if not self.aliases:
            raise ValueError("division aliases must not be empty")
        if not self.regions:
            raise ValueError("division regions must not be empty")


@dataclass(frozen=True, slots=True)
class BriefConfig:
    divisions: tuple[DivisionRule, ...]

    def __post_init__(self) -> None:
        if not self.divisions:
            raise ValueError("at least one division rule is required")
        aliases = [alias for rule in self.divisions for alias in rule.aliases]
        if len(set(aliases)) != len(aliases):
            raise ValueError("division aliases must be unique across rules")

    @classmethod
    def default(cls) -> "BriefConfig":
        return cls(
            divisions=(
                DivisionRule(
                    name="제8기동사단",
                    aliases=("8사단", "8기동사단", "3070부대", "오뚜기부대"),
                    regions=("양주", "동두천", "포천", "연천", "의정부"),
                ),
            )
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "BriefConfig":
        raw_divisions = data.get("divisions")
        if isinstance(raw_divisions, str) or not isinstance(raw_divisions, Sequence):
            raise ValueError("divisions must be a sequence")

        rules: list[DivisionRule] = []
        for index, raw_rule in enumerate(cast(Sequence[object], raw_divisions)):
            if not isinstance(raw_rule, Mapping):
                raise ValueError(f"divisions[{index}] must be a mapping")
            rule_mapping = cast(Mapping[object, object], raw_rule)
            name = rule_mapping.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"divisions[{index}].name must be a non-empty string")
            rules.append(
                DivisionRule(
                    name=name,
                    aliases=_string_tuple(
                        rule_mapping.get("aliases"), f"divisions[{index}].aliases"
                    ),
                    regions=_string_tuple(
                        rule_mapping.get("regions"), f"divisions[{index}].regions"
                    ),
                )
            )
        return cls(divisions=tuple(rules))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "BriefConfig":
        environment = os.environ if environ is None else environ
        raw_config = environment.get(CONFIG_ENV_VAR)
        if raw_config is None:
            return cls.default()
        try:
            decoded: object = json.loads(raw_config)
        except json.JSONDecodeError as error:
            raise ValueError(f"{CONFIG_ENV_VAR} must contain valid JSON") from error
        if not isinstance(decoded, Mapping):
            raise ValueError(f"{CONFIG_ENV_VAR} must contain a JSON object")
        decoded_mapping = cast(Mapping[object, object], decoded)
        if not all(isinstance(key, str) for key in decoded_mapping):
            raise ValueError(f"{CONFIG_ENV_VAR} object keys must be strings")
        return cls.from_mapping(cast(Mapping[str, object], decoded_mapping))


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_aware(self.start, "window start")
        _require_aware(self.end, "window end")
        if self.start > self.end:
            raise ValueError("window start must not be after window end")

    def contains(self, value: datetime) -> bool:
        _require_aware(value, "candidate time")
        return self.start <= value <= self.end


def kst_collection_window(run_at: datetime) -> CollectionWindow:
    _require_aware(run_at, "run_at")
    end = run_at.astimezone(KST)
    previous_day = end.date() - timedelta(days=1)
    start = datetime.combine(previous_day, time(hour=14), tzinfo=KST)
    return CollectionWindow(start=start, end=end)
