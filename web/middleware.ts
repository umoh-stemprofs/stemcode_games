/**
 * Route guard (P1-T07).
 *
 * A cheap first line only: it checks that a session cookie **exists**, because
 * the real check has to happen on the server that can verify the signature.
 * Anything this middleware lets through is still verified by the API, which
 * answers 401 and the page falls back to the sign-in screen.
 *
 * Presence-only is deliberate: it avoids a redirect flash for a signed-in
 * person whose access cookie is mid-rotation. The refresh cookie keeps them
 * in.
 */

import { NextResponse, type NextRequest } from "next/server";

const ACCESS_COOKIE = "stem_access";
const REFRESH_COOKIE = "stem_refresh";
const PUBLIC_PATHS = ["/login"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

const INVITE_COOKIE = "invite_token";

/**
 * Links carry a token once, then never again (P7-T02).
 *
 * `/games/join?t=…` is turned into a 10-minute httpOnly cookie and a redirect
 * to the clean URL *before* anything else looks at the request — including the
 * sign-in redirect, which would otherwise put the token in `?next=` and then in
 * a `Referer` header. The join page reads the cookie back through the API, so
 * the token never travels in a URL a browser logs or shares.
 */
function holdInviteToken(request: NextRequest): NextResponse | null {
  const { pathname, searchParams, clone } = request.nextUrl;
  const token = pathname === "/games/join" ? searchParams.get("t") : null;
  if (!token) return null;

  const url = clone();
  url.search = "";
  const response = NextResponse.redirect(url);
  response.cookies.set(INVITE_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 600,
    secure: process.env.NODE_ENV === "production",
  });
  return response;
}

export function middleware(request: NextRequest) {
  const held = holdInviteToken(request);
  if (held) return held;

  const { pathname, search } = request.nextUrl;
  const signedInHint =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);

  if (!signedInHint && !isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(`${pathname}${search}`)}`;
    return NextResponse.redirect(url);
  }

  if (signedInHint && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Everything except the API (the rewrite must pass through untouched),
  // Next's own assets, and files with an extension.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
