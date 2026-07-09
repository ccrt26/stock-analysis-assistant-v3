from __future__ import annotations

import re
from collections.abc import Iterable
from os import environ
from typing import Mapping


REDACTION_MARKER = "[REDACTED]"
KNOWN_SECRET_ENV_NAMES = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "TUSHARE_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "REPORT_PASSWORD",
    "REPORT_SESSION_SECRET",
)

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
    secrets = _clean_explicit_secrets(explicit_secrets)
    secrets.update(known_env_secret_values())
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTION_MARKER)
    redacted = _AUTHORIZATION_BEARER_RE.sub(
        lambda match: f"{match.group(1)}{REDACTION_MARKER}",
        redacted,
    )
    return _CREDENTIAL_ASSIGNMENT_RE.sub(REDACTION_MARKER, redacted)


def known_env_secret_values(env: Mapping[str, str] | None = None) -> set[str]:
    values = environ if env is None else env
    return _clean_explicit_secrets(values.get(name) for name in KNOWN_SECRET_ENV_NAMES)


def _clean_explicit_secrets(explicit_secrets: Iterable[str]) -> set[str]:
    return {secret.strip() for secret in explicit_secrets if secret and secret.strip()}
