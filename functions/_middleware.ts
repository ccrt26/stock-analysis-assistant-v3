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

type Env = {
  REPORT_PASSWORD?: string;
  REPORT_SESSION_SECRET?: string;
};

const SESSION_MAX_AGE_SECONDS = 604800;
const SESSION_MAX_AGE_MS = SESSION_MAX_AGE_SECONDS * 1000;
const SESSION_COOKIE_MAX_AGE = "Max-Age=604800";

const base64UrlEncode = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
};

const timingSafeEqual = (left: string, right: string): boolean => {
  if (left.length !== right.length) {
    return false;
  }
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
};

const signIssuedAt = async (issuedAt: string, secret: string): Promise<string> => {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(issuedAt));
  return base64UrlEncode(signature);
};

const createSessionValue = async (secret: string): Promise<string> => {
  const issuedAt = Date.now().toString();
  const signature = await signIssuedAt(issuedAt, secret);
  return `${issuedAt}.${signature}`;
};

const isValidSession = async (session: string | null, secret: string): Promise<boolean> => {
  if (!session) {
    return false;
  }

  const [issuedAt, signature, extra] = session.split(".");
  if (!issuedAt || !signature || extra !== undefined) {
    return false;
  }

  const issuedAtMs = Number(issuedAt);
  if (!Number.isFinite(issuedAtMs)) {
    return false;
  }

  const now = Date.now();
  if (issuedAtMs > now || now - issuedAtMs > SESSION_MAX_AGE_MS) {
    return false;
  }

  const expectedSignature = await signIssuedAt(issuedAt, secret);
  return timingSafeEqual(signature, expectedSignature);
};

export const onRequest: PagesFunction<Env> = async (context) => {
  const request = context.request;
  const url = new URL(request.url);
  const passwordSecret = context.env.REPORT_PASSWORD;
  const sessionSecret = context.env.REPORT_SESSION_SECRET;

  if (!passwordSecret || !sessionSecret) {
    return new Response("", { status: 503 });
  }

  const cookie = request.headers.get("Cookie") || "";
  const session = getCookieValue(cookie, "report_session");

  if (await isValidSession(session, sessionSecret)) {
    return context.next();
  }

  if (url.pathname === "/login" && request.method === "POST") {
    const form = await request.formData();
    const password = String(form.get("password") || "");
    if (password === passwordSecret) {
      const sessionValue = await createSessionValue(sessionSecret);
      return new Response("", {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie":
            `report_session=${sessionValue}; HttpOnly; Secure; SameSite=Lax; Path=/; ${SESSION_COOKIE_MAX_AGE}`,
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
