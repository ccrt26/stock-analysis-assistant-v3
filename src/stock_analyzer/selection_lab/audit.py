from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_FORMATION = re.compile(
    r"(?:形成日|formation_date|formation date)[^\d]{0,30}(20\d{2}-\d{2}-\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateUse:
    date: str
    document: str
    future_opened: bool
    evidence: str


def classify_formation_date_uses(
    documents: Mapping[str, str],
    *,
    excluded_paths: set[str] | None = None,
) -> list[DateUse]:
    excluded = excluded_paths or set()
    uses: list[DateUse] = []
    for path, text in sorted(documents.items()):
        if path in excluded:
            continue
        for match in _FORMATION.finditer(text):
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 120)
            evidence = text[start:end].replace("\n", " ")
            uses.append(
                DateUse(
                    date=match.group(1),
                    document=path,
                    future_opened=bool(
                        re.search(
                            r"未来.{0,12}(?:打开|揭盲)|future_data_opened\s*[:=]\s*true",
                            evidence,
                            re.IGNORECASE,
                        )
                    ),
                    evidence=evidence,
                )
            )
    return uses


def scan_public_payload(payload: Any) -> list[str]:
    findings: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        lowered_key = key.lower()
        if any(word in lowered_key for word in ("token", "secret", "password")):
            findings.add("token_or_secret")
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, key)
        elif isinstance(value, str):
            if re.search(r"(?:^|\s)/(?:Users|home)/[^\s]+", value):
                findings.add("local_absolute_path")
            if re.search(r"(?:^|[/\\])\.env(?:\.|$)", value):
                findings.add("env_file")

    visit(payload)
    return sorted(findings)


def deterministic_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
