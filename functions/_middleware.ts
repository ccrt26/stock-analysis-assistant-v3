const getCookieValue = (cookieHeader: string, name: string): string | null => {
  for (const piece of cookieHeader.split(";")) {
    const [rawName, ...rawValue] = piece.trim().split("=");
    if (rawName === name) {
      const value = rawValue.join("=");
      return value.startsWith("\"") && value.endsWith("\"")
        ? value.slice(1, -1)
        : value;
    }
  }
  return null;
};

export const onRequest: PagesFunction<{ REPORT_PASSWORD: string }> = async (context) => {
  const request = context.request;
  const url = new URL(request.url);
  const cookie = request.headers.get("Cookie") || "";
  const session = getCookieValue(cookie, "report_session");

  if (session === "ok") {
    return context.next();
  }

  if (url.pathname === "/login" && request.method === "POST") {
    const form = await request.formData();
    const password = String(form.get("password") || "");
    if (password === context.env.REPORT_PASSWORD) {
      return new Response("", {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie":
            "report_session=ok; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800",
        },
      });
    }
  }

  if (url.pathname === "/login") {
    return new Response(
      "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>报告访问</title><form method=\"post\"><input name=\"password\" type=\"password\" autocomplete=\"current-password\"><button>进入报告</button></form></html>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }

  return new Response("", { status: 302, headers: { Location: "/login" } });
};
