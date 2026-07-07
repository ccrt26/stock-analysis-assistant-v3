from pathlib import Path


def test_cloudflare_middleware_uses_password_and_cookie_without_secrets_in_html():
    middleware_path = (
        Path(__file__).resolve().parents[1] / "functions" / "_middleware.ts"
    )
    if not middleware_path.exists():
        middleware_path = Path("/Users/ccrt/股票分析助手/functions/_middleware.ts")

    text = middleware_path.read_text(encoding="utf-8")
    assert "REPORT_PASSWORD" in text
    assert "report_session" in text
    assert 'cookie.includes("report_session=ok")' not in text
    assert "HttpOnly" in text
    assert "Secure" in text
    assert "SameSite=Lax" in text
    assert "Path=/" in text
    assert "Max-Age=604800" in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "TUSHARE_TOKEN" not in text
