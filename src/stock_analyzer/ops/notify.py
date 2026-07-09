from __future__ import annotations

import subprocess

from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.ops.status import JobStatus, RunStatus


def should_notify(status: JobStatus) -> bool:
    return status.status == RunStatus.FAILED_NEEDS_HUMAN


def notify_mac(title: str, message: str, enabled: bool = False) -> None:
    if not enabled:
        return

    safe_title = redact_secrets(title)
    safe_message = redact_secrets(message)
    script = (
        "display notification "
        f"{_applescript_string(safe_message)} "
        f"with title {_applescript_string(safe_title)}"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def _applescript_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )
    return f'"{escaped}"'
