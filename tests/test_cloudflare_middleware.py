import json
import os
from pathlib import Path
import subprocess
import textwrap


def test_cloudflare_middleware_uses_password_and_cookie_without_secrets_in_html():
    middleware_path = Path(__file__).resolve().parents[1] / "functions" / "_middleware.ts"

    text = middleware_path.read_text(encoding="utf-8")
    assert "REPORT_PASSWORD" in text
    assert "REPORT_SESSION_SECRET" in text
    assert "report_session" in text
    assert "crypto.subtle" in text or "HMAC" in text
    assert "report_session=ok" not in text
    assert 'cookie.includes("report_session=ok")' not in text
    assert "HttpOnly" in text
    assert "Secure" in text
    assert "SameSite=Lax" in text
    assert "Path=/" in text
    assert "Max-Age=604800" in text
    assert "timingSafeEqual(password, passwordSecret)" in text
    assert "password === passwordSecret" not in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "TUSHARE_TOKEN" not in text


def test_cloudflare_middleware_allows_valid_signed_session():
    result = _run_middleware_scenario({"name": "valid_session"})

    assert result["loginStatus"] == 302
    assert "report_session=" in result["setCookie"]
    assert result["status"] == 200
    assert result["nextCalled"] is True


def test_cloudflare_middleware_rejects_forged_session():
    result = _run_middleware_scenario({"name": "forged_session"})

    assert result["status"] == 302
    assert result["location"] == "/login"
    assert result["nextCalled"] is False


def test_cloudflare_middleware_rejects_expired_session():
    result = _run_middleware_scenario({"name": "expired_session"})

    assert result["status"] == 302
    assert result["location"] == "/login"
    assert result["nextCalled"] is False


def test_cloudflare_middleware_fails_closed_when_credentials_missing():
    for env in (
        {},
        {"REPORT_PASSWORD": "correct-password"},
        {"REPORT_SESSION_SECRET": "session-secret"},
    ):
        result = _run_middleware_scenario({"name": "missing_credentials", "env": env})

        assert result["status"] == 503
        assert result["nextCalled"] is False


def _run_middleware_scenario(scenario):
    middleware_url = (
        Path(__file__).resolve().parents[1] / "functions" / "_middleware.ts"
    ).as_uri()
    script = textwrap.dedent(
        f"""
        import {{ onRequest }} from {json.dumps(middleware_url)};

        const scenario = JSON.parse(process.env.MIDDLEWARE_SCENARIO);
        const baseEnv = {{
          REPORT_PASSWORD: "correct-password",
          REPORT_SESSION_SECRET: "session-secret",
        }};
        const maxAgeMs = 604800 * 1000;
        let nextCalled = false;

        const setNow = (value) => {{
          Date.now = () => value;
        }};

        const callMiddleware = async (request, env = baseEnv) => {{
          return await onRequest({{
            request,
            env,
            next: async () => {{
              nextCalled = true;
              return new Response("next-ok", {{ status: 200 }});
            }},
          }});
        }};

        const login = async (issuedAt) => {{
          setNow(issuedAt);
          return await callMiddleware(
            new Request("https://reports.example/login", {{
              method: "POST",
              body: new URLSearchParams({{ password: "correct-password" }}),
            }}),
          );
        }};

        const visitWithCookie = async (cookie, now, env = baseEnv) => {{
          nextCalled = false;
          setNow(now);
          const response = await callMiddleware(
            new Request("https://reports.example/", {{
              headers: {{ Cookie: cookie }},
            }}),
            env,
          );
          return {{
            status: response.status,
            location: response.headers.get("Location"),
            nextCalled,
          }};
        }};

        let output;
        if (scenario.name === "valid_session") {{
          const issuedAt = 1783420800000;
          const loginResponse = await login(issuedAt);
          const setCookie = loginResponse.headers.get("Set-Cookie");
          output = {{
            loginStatus: loginResponse.status,
            setCookie,
            ...(await visitWithCookie(setCookie, issuedAt + 1000)),
          }};
        }} else if (scenario.name === "forged_session") {{
          output = await visitWithCookie(
            "report_session=1783420800000.forged-signature",
            1783420801000,
          );
        }} else if (scenario.name === "expired_session") {{
          const issuedAt = 1783420800000;
          const loginResponse = await login(issuedAt);
          output = await visitWithCookie(
            loginResponse.headers.get("Set-Cookie"),
            issuedAt + maxAgeMs + 1,
          );
        }} else if (scenario.name === "missing_credentials") {{
          output = await visitWithCookie("", 1783420800000, scenario.env);
        }} else {{
          throw new Error(`Unknown scenario: ${{scenario.name}}`);
        }}

        console.log(JSON.stringify(output));
        """
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "MIDDLEWARE_SCENARIO": json.dumps(scenario)},
    )
    return json.loads(completed.stdout)
