from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs

import httpx
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.ops.smoke import SmokeFailure, SmokeResult, smoke_report_site


def test_smoke_report_site_validates_login_flow_without_echoing_password(capsys):
    password = _test_password()
    transport = _report_site_transport(password=password)

    result = smoke_report_site(
        "https://reports.example",
        password,
        transport=transport,
    )

    captured = capsys.readouterr()
    assert result.passed is True
    assert result.failures == ()
    assert transport.requests == [
        ("GET", "/"),
        ("GET", "/login"),
        ("POST", "/login"),
        ("GET", "/"),
    ]
    assert password not in captured.out
    assert password not in captured.err
    assert password not in repr(result)


def test_smoke_report_site_fails_when_root_does_not_redirect_to_login():
    transport = _report_site_transport(
        password=_test_password(),
        root_redirect=False,
    )

    result = smoke_report_site(
        "https://reports.example",
        _test_password(),
        transport=transport,
    )

    assert result.passed is False
    assert _failure_codes(result) == ["redirect_to_login_failed"]
    assert result.fix_suggestion


def test_smoke_report_site_requires_password_for_authenticated_report():
    result = smoke_report_site(
        "https://reports.example",
        None,
        transport=_report_site_transport(password=_test_password()),
    )

    assert result.passed is False
    assert "password_missing" in _failure_codes(result)


def test_smoke_report_site_fails_when_fixture_or_sample_content_appears():
    transport = _report_site_transport(
        password=_test_password(),
        home_html="<html>Fixture/sample report generated from local sample data</html>",
    )

    result = smoke_report_site(
        "https://reports.example",
        _test_password(),
        transport=transport,
    )

    assert result.passed is False
    assert "fixture_sample_leak" in _failure_codes(result)
    assert "Fixture/sample" not in repr(result)


def test_smoke_report_site_fails_when_expected_trade_date_is_missing():
    transport = _report_site_transport(
        password=_test_password(),
        home_html="<html>生产报告 2026-07-08</html>",
    )

    result = smoke_report_site(
        "https://reports.example",
        _test_password(),
        expected_trade_date=date(2026, 7, 9),
        transport=transport,
    )

    assert result.passed is False
    assert "report_date_mismatch" in _failure_codes(result)
    assert "2026-07-09" in result.failures[0].message


def test_smoke_report_site_fails_on_sensitive_variable_names_and_fake_secret_patterns():
    sensitive_variable_name = "_".join(("SUPABASE", "SERVICE", "ROLE", "KEY"))
    fake_key = "-".join(("fake", "service", "role", "key"))
    fake_bearer = "-".join(("fake", "bearer", "token"))
    transport = _report_site_transport(
        password=_test_password(),
        home_html=(
            f"<html>{sensitive_variable_name}={fake_key} "
            f"Authorization: Bearer {fake_bearer}</html>"
        ),
    )

    result = smoke_report_site(
        "https://reports.example",
        _test_password(),
        transport=transport,
    )

    assert result.passed is False
    assert "sensitive_content_leak" in _failure_codes(result)
    assert fake_key not in repr(result)
    assert fake_bearer not in repr(result)


def test_ops_smoke_report_site_cli_reads_password_env_without_printing_it(monkeypatch):
    password = "-".join(("do", "not", "print", "this", "report", "password"))
    captured_passwords: list[str | None] = []

    def fake_smoke_report_site(url, password_arg, *, expected_trade_date=None):
        captured_passwords.append(password_arg)
        assert expected_trade_date is None
        return SmokeResult(
            base_url=url,
            passed=False,
            checks=("redirect_to_login",),
            failures=(
                SmokeFailure(
                    code="fixture_sample_leak",
                    message="Fixture marker detected.",
                    fix_suggestion="Publish only production report artifacts.",
                ),
            ),
        )

    password_env_name = "_".join(("REPORT", "PASSWORD"))
    monkeypatch.setenv(password_env_name, password)
    monkeypatch.setattr("stock_analyzer.cli.smoke_report_site", fake_smoke_report_site)

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "smoke-report-site",
            "--url",
            "https://reports.example",
            "--password-env",
            password_env_name,
        ],
    )

    assert result.exit_code == 2
    assert captured_passwords == [password]
    assert "fixture_sample_leak" in result.output
    assert password not in result.output


def test_ops_smoke_report_site_cli_passes_expected_trade_date(monkeypatch):
    captured_expected_dates: list[date | None] = []

    def fake_smoke_report_site(url, password_arg, *, expected_trade_date=None):
        captured_expected_dates.append(expected_trade_date)
        return SmokeResult(
            base_url=url,
            passed=True,
            checks=("report_date_matches",),
            failures=(),
        )

    password_env_name = "_".join(("REPORT", "PASSWORD"))
    monkeypatch.setenv(password_env_name, _test_password())
    monkeypatch.setattr("stock_analyzer.cli.smoke_report_site", fake_smoke_report_site)

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "smoke-report-site",
            "--url",
            "https://reports.example",
            "--password-env",
            password_env_name,
            "--expected-trade-date",
            "2026-07-09",
        ],
    )

    assert result.exit_code == 0
    assert captured_expected_dates == [date(2026, 7, 9)]


class _ReportSiteTransport(httpx.MockTransport):
    def __init__(
        self,
        *,
        password: str,
        root_redirect: bool = True,
        home_html: str = "<html>生产报告 2026-07-09</html>",
    ) -> None:
        self.password = password
        self.root_redirect = root_redirect
        self.home_html = home_html
        self.requests: list[tuple[str, str]] = []
        super().__init__(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.path == "/" and request.method == "GET":
            if request.headers.get("Cookie") == "report_session=ok":
                return httpx.Response(200, text=self.home_html)
            if self.root_redirect:
                return httpx.Response(302, headers={"Location": "/login"})
            return httpx.Response(200, text="<html>public report</html>")

        if request.url.path == "/login" and request.method == "GET":
            return httpx.Response(
                200,
                text=(
                    "<form method='post'>"
                    "<input name='password' type='password'>"
                    "</form>"
                ),
            )

        if request.url.path == "/login" and request.method == "POST":
            body = request.read().decode("utf-8")
            submitted_password = parse_qs(body).get("password", [""])[0]
            if submitted_password == self.password:
                return httpx.Response(
                    302,
                    headers={
                        "Location": "/",
                        "Set-Cookie": (
                            "report_session=ok; HttpOnly; Secure; "
                            "SameSite=Lax; Path=/"
                        ),
                    },
                )
            return httpx.Response(401, text="invalid")

        return httpx.Response(404, text="not found")


def _report_site_transport(**kwargs) -> _ReportSiteTransport:
    return _ReportSiteTransport(**kwargs)


def _test_password() -> str:
    return "-".join(("correct", "report", "password"))


def _failure_codes(result: SmokeResult) -> list[str]:
    return [failure.code for failure in result.failures]
