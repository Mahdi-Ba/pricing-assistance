/**
 * Optimistic gate: send visitors without a session cookie to sign-in before rendering a
 * workspace page. Real authorization happens on the server (layouts, the API proxy and the API).
 */
import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIES = ["authjs.session-token", "__Secure-authjs.session-token"];

export function proxy(request: NextRequest) {
  const hasSession = request.cookies
    .getAll()
    .some((c) => SESSION_COOKIES.some((name) => c.name === name || c.name.startsWith(`${name}.`)));
  if (hasSession) return NextResponse.next();
  const signIn = new URL("/signin", request.url);
  signIn.searchParams.set("callbackUrl", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(signIn);
}

export const config = {
  matcher: ["/queue/:path*", "/matches/:path*", "/reports/:path*", "/catalog/:path*", "/rules/:path*", "/sources/:path*", "/help/:path*", "/settings/:path*"],
};
