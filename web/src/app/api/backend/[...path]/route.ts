/**
 * Backend-for-frontend proxy: same-origin browser calls → pricing API with the user's token.
 *
 * - Only `/api/v1/...` paths are forwarded, to the configured backend origin.
 * - The bearer token is taken from the encrypted server-side session; the browser never sees it.
 * - State-changing requests must come from this origin (CSRF protection on top of the
 *   SameSite=Lax session cookie).
 * - Only the headers the API needs are forwarded, in both directions.
 */
import type { NextRequest } from "next/server";
import { accessTokenOf, auth } from "@/auth";

const BACKEND = process.env.BACKEND_API_URL ?? "http://localhost:8000";
const SAFE_SEGMENT = /^[A-Za-z0-9._~-]+$/;
const REQUEST_HEADERS = ["accept", "content-type", "idempotency-key", "x-correlation-id"];
const RESPONSE_HEADERS = ["content-type", "content-disposition", "x-correlation-id", "retry-after"];
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const TIMEOUT_MS = 60_000;

function problem(status: number, code: string, messageFa: string): Response {
  return Response.json(
    { type: `urn:tunoo:pricing:problem:${code}`, title: code, status, message_fa: messageFa },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin) return origin === request.nextUrl.origin;
  return request.headers.get("sec-fetch-site") === "same-origin";
}

async function forward(
  request: NextRequest & { auth?: unknown },
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const token = accessTokenOf(request.auth);
  if (!token) return problem(401, "authentication_required", "نشست شما پایان یافته است؛ دوباره وارد شوید.");
  if (UNSAFE_METHODS.has(request.method) && !sameOrigin(request)) {
    return problem(403, "cross_origin_request", "درخواست از مبدأ نامعتبر رد شد.");
  }
  const { path } = await context.params;
  if (path[0] !== "api" || path[1] !== "v1" || !path.every((s) => SAFE_SEGMENT.test(s) && s !== "..")) {
    return problem(404, "not_found", "مسیر یافت نشد.");
  }
  const target = new URL(`/${path.join("/")}`, BACKEND);
  target.search = request.nextUrl.search;

  const headers = new Headers({ authorization: `Bearer ${token}` });
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: UNSAFE_METHODS.has(request.method) ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return problem(502, "backend_unavailable", "ارتباط با سرور برقرار نشد؛ دوباره تلاش کنید.");
  }
  const out = new Headers({ "cache-control": "no-store" });
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: out,
  });
}

const handler = auth(forward as never) as unknown as (
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) => Promise<Response>;

export { handler as DELETE, handler as GET, handler as PATCH, handler as POST, handler as PUT };
