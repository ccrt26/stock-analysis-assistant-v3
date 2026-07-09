from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx

from stock_analyzer.ops.redaction import redact_secrets


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_FIXTURE_SAMPLE_PATTERNS = (
    re.compile(r"fixture/sample", re.IGNORECASE),
    re.compile(r"\bfixture\b", re.IGNORECASE),
    re.compile(r"\bsample\b", re.IGNORECASE),
    re.compile(r"local sample data", re.IGNORECASE),
    re.compile(r"not production data", re.IGNORECASE),
)
_SENSITIVE_VARIABLE_NAMES = tuple(
    "_".join(parts)
    for parts in (
        ("SUPABASE", "SERVICE", "ROLE", "KEY"),
        ("TUSHARE", "TOKEN"),
        ("CLOUDFLARE", "API", "TOKEN"),
        ("REPORT", "PASSWORD"),
        ("REPORT", "SESSION", "SECRET"),
    )
)
_SENSITIVE_CONTENT_PATTERNS = (
    re.compile(r"\.env(?:\.local)?", re.IGNORECASE),
    *(
        re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        for name in _SENSITIVE_VARIABLE_NAMES
    ),
    re.compile(r"\bAuthorization\s*:\s*Bearer\s+[^\s<>&;]+", re.IGNORECASE),
    re.compile(
        r"\b[A-Z0-9_]*(?:KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*\s*[:=]\s*"
        r"[^\s<>&;]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfake[-_][a-z0-9_-]*(?:key|token|secret|password)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class SmokeFailure:
    code: str
    message: str
    fix_suggestion: str


@dataclass(frozen=True)
class SmokeResult:
    base_url: str
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[SmokeFailure, ...]

    @property
    def fix_suggestion(self) -> str | None:
        if not self.failures:
            return None
        return self.failures[0].fix_suggestion


def smoke_report_site(
    base_url: str,
    password: str | None,
    *,
    expected_trade_date: date | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> SmokeResult:
    normalized_base_url = _normalize_base_url(base_url)
    checks: list[str] = []
    failures: list[SmokeFailure] = []

    try:
        with httpx.Client(
            base_url=normalized_base_url,
            follow_redirects=False,
            timeout=timeout,
            transport=transport,
        ) as client:
            root_response = client.get("/")
            if not _redirects_to(root_response, "/login"):
                return _result(
                    normalized_base_url,
                    checks,
                    _failure(
                        "redirect_to_login_failed",
                        "Unauthenticated report access did not redirect to login.",
                        "Check Cloudflare Pages middleware binding and route coverage.",
                    ),
                )
            checks.append("redirect_to_login")

            login_response = client.get("/login")
            if login_response.status_code != 200:
                return _result(
                    normalized_base_url,
                    checks,
                    _failure(
                        "login_page_failed",
                        "Login page did not return HTTP 200.",
                        "Verify the Pages middleware serves the login form.",
                    ),
                )
            checks.append("login_page")

            if not password:
                return _result(
                    normalized_base_url,
                    checks,
                    _failure(
                        "password_missing",
                        "Report password was not available to the smoke command.",
                        "Set the configured password environment variable and rerun smoke.",
                    ),
                )

            login_post = client.post("/login", data={"password": password})
            if not _redirects_to(login_post, "/"):
                return _result(
                    normalized_base_url,
                    checks,
                    _failure(
                        "password_login_failed",
                        "Password login did not establish a report session.",
                        "Confirm the deployed Pages password binding matches production.",
                    ),
                )
            checks.append("password_login")

            home_response = client.get("/")
            if home_response.status_code != 200:
                return _result(
                    normalized_base_url,
                    checks,
                    _failure(
                        "authenticated_home_failed",
                        "Authenticated report page did not return HTTP 200.",
                        "Verify the session cookie and current report artifact.",
                    ),
                )
            checks.append("authenticated_home")

            content = home_response.text
            if expected_trade_date is not None:
                expected_date_text = expected_trade_date.isoformat()
                if expected_date_text not in content:
                    failures.append(
                        _failure(
                            "report_date_mismatch",
                            (
                                "Expected report date "
                                f"{expected_date_text} was not found in report content."
                            ),
                            (
                                "Deploy the artifact for the expected trade date and "
                                "rerun smoke."
                            ),
                        )
                    )
                else:
                    checks.append("report_date_matches")

            if _contains_fixture_sample_marker(content):
                failures.append(
                    _failure(
                        "fixture_sample_leak",
                        "Fixture or sample marker detected in report content.",
                        "Publish only production report artifacts and rerun smoke.",
                    )
                )
            else:
                checks.append("fixture_sample_absent")

            if _contains_sensitive_content(content):
                failures.append(
                    _failure(
                        "sensitive_content_leak",
                        "Sensitive variable name or secret-like pattern detected.",
                        "Remove credential material from report artifacts before publishing.",
                    )
                )
            else:
                checks.append("sensitive_content_absent")
    except httpx.HTTPError as exc:
        failures.append(
            _failure(
                "http_error",
                redact_secrets(str(exc)),
                "Check the report URL and network path, then rerun smoke.",
            )
        )

    return SmokeResult(
        base_url=normalized_base_url,
        passed=not failures,
        checks=tuple(checks),
        failures=tuple(failures),
    )


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("base_url is required")
    return normalized


def _redirects_to(response: httpx.Response, expected_path: str) -> bool:
    if response.status_code not in _REDIRECT_STATUSES:
        return False
    location = response.headers.get("Location")
    if not location:
        return False
    request_url = str(response.request.url)
    redirected = urlparse(urljoin(request_url, location))
    return redirected.path == expected_path


def _contains_fixture_sample_marker(content: str) -> bool:
    return any(pattern.search(content) for pattern in _FIXTURE_SAMPLE_PATTERNS)


def _contains_sensitive_content(content: str) -> bool:
    return any(pattern.search(content) for pattern in _SENSITIVE_CONTENT_PATTERNS)


def _result(
    base_url: str,
    checks: list[str],
    failure: SmokeFailure,
) -> SmokeResult:
    return SmokeResult(
        base_url=base_url,
        passed=False,
        checks=tuple(checks),
        failures=(failure,),
    )


def _failure(code: str, message: str, fix_suggestion: str) -> SmokeFailure:
    return SmokeFailure(
        code=code,
        message=redact_secrets(message),
        fix_suggestion=redact_secrets(fix_suggestion),
    )


__all__ = ["SmokeFailure", "SmokeResult", "smoke_report_site"]
