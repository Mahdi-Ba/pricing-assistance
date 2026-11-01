/**
 * Auth.js (v5) with Keycloak as a backend-for-frontend.
 *
 * The browser only ever holds Auth.js's encrypted, httpOnly session cookie. Keycloak's access
 * and refresh tokens live inside that encrypted JWT and are read only on the server (the
 * `/api/backend` proxy); the session exposed to client code contains the username, roles and
 * tenant, never a token. Access tokens are refreshed server-side shortly before they expire.
 */
import NextAuth, { type DefaultSession } from "next-auth";
import type { JWT } from "next-auth/jwt";
import Keycloak from "next-auth/providers/keycloak";

export type Role = "admin" | "expert";

export interface Viewer {
  username: string;
  roles: Role[];
  tenantId: string | null;
}

declare module "next-auth" {
  interface Session {
    viewer?: Viewer;
    error?: "RefreshFailed";
    user?: DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number; // seconds since epoch
    viewer?: Viewer;
    error?: "RefreshFailed";
  }
}

const issuer = process.env.AUTH_KEYCLOAK_ISSUER ?? "http://localhost:58080/realms/pricing-assistance";
const clientId = process.env.AUTH_KEYCLOAK_ID ?? "pricing-web";
const clientSecret = process.env.AUTH_KEYCLOAK_SECRET ?? "";
const REFRESH_MARGIN_SECONDS = 30;

function claims(accessToken: string): Record<string, unknown> {
  // Display-only decoding (roles, tenant, username). The backend verifies every token itself.
  const payload = accessToken.split(".")[1] ?? "";
  try {
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export function viewerFrom(accessToken: string): Viewer {
  const c = claims(accessToken);
  const roles = Array.isArray(c.roles)
    ? c.roles.filter((r): r is Role => r === "admin" || r === "expert")
    : [];
  return {
    username: typeof c.preferred_username === "string" ? c.preferred_username : String(c.sub ?? ""),
    roles,
    tenantId: typeof c.tenant_id === "string" ? c.tenant_id : null,
  };
}

async function refresh(token: JWT): Promise<JWT> {
  if (!token.refreshToken) return { ...token, error: "RefreshFailed" };
  try {
    const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
        client_id: clientId,
        client_secret: clientSecret,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    const body = (await response.json()) as {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
    };
    if (!response.ok || !body.access_token) return { ...token, error: "RefreshFailed" };
    return {
      ...token,
      accessToken: body.access_token,
      refreshToken: body.refresh_token ?? token.refreshToken,
      expiresAt: Math.floor(Date.now() / 1000) + (body.expires_in ?? 60),
      viewer: viewerFrom(body.access_token),
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshFailed" };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Keycloak({ clientId, clientSecret, issuer })],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  trustHost: true,
  pages: { signIn: "/signin" },
  callbacks: {
    async jwt({ token, account }) {
      if (account?.access_token) {
        return {
          sub: token.sub,
          accessToken: account.access_token,
          refreshToken: account.refresh_token,
          expiresAt: account.expires_at,
          viewer: viewerFrom(account.access_token),
        };
      }
      if (token.expiresAt && Date.now() / 1000 < token.expiresAt - REFRESH_MARGIN_SECONDS) {
        return token;
      }
      return refresh(token);
    },
    // What any caller of the session (including the browser) sees: never a token.
    async session({ session, token }) {
      return { expires: session.expires, viewer: token.viewer, error: token.error } as typeof session;
    },
  },
});

/** Server-only: the current access token from the decrypted session (never sent to the browser). */
export function accessTokenOf(session: unknown): string | null {
  // Auth.js passes the decrypted token as `user` to server-side callers of `auth()`.
  const token = (session as { user?: JWT } | null)?.user;
  if (!token || token.error || !token.accessToken) return null;
  return token.accessToken;
}
