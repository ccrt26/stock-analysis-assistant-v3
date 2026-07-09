from __future__ import annotations

import re
from collections.abc import Iterable


REDACTION_MARKER = "[REDACTED]"

_AUTHORIZATION_BEARER_RE = re.compile(
    r"\b(Authorization\s*:\s*Bearer\s+)([^\s,;]+)",
    flags=re.IGNORECASE,
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"\b[A-Z0-9_]*(?:KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*\s*[:=]\s*[^\s,;]+",
    flags=re.IGNORECASE,
)


def redact_secrets(text: str, explicit_secrets: Iterable[str] = ()) -> str:
    """Remove known secret values and common credential forms from text."""
    redacted = text
    for secret in sorted(_clean_explicit_secrets(explicit_secrets), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTION_MARKER)
    redacted = _AUTHORIZATION_BEARER_RE.sub(
        lambda match: f"{match.group(1)}{REDACTION_MARKER}",
        redacted,
    )
    return _CREDENTIAL_ASSIGNMENT_RE.sub(REDACTION_MARKER, redacted)


def _clean_explicit_secrets(explicit_secrets: Iterable[str]) -> set[str]:
    return {secret.strip() for secret in explicit_secrets if secret and secret.strip()}
