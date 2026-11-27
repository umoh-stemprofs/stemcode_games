/**
 * Next.js configuration (P0-T06, P0-T03b).
 *
 * The browser must only ever see ONE origin (D-19), so in development a rewrite
 * forwards `/api/*` to the FastAPI process. The browser keeps talking to
 * http://localhost:3000, which is exactly what the production proxy does.
 *
 * Next rewrites do not upgrade WebSockets. `/ws/*` therefore connects to the
 * API port directly in dev; that is safe because the WS ticket is an ordinary
 * REST call and cookies still work.
 *
 * @type {import('next').NextConfig}
 */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  // `next build` and `next dev` must never write into the same directory. When
  // they shared `.next`, a build replaced the dev server's chunks underneath it
  // and every page died with "Cannot find module './NNN.js'". `next start` also
  // runs with NODE_ENV=production, so it reads the directory the build wrote.
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",

  // The floating dev indicator only exists under `next dev`; this hides it so
  // screenshots and demos show the product, not Next's overlay. It has no
  // effect on a production build.
  devIndicators: false,

  async rewrites() {
    // Production is fronted by the reverse proxy, which already routes /api.
    if (process.env.NODE_ENV === "production") return [];
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },

  async headers() {
    const baseline = [
      // Invite links carry a token in their first request (D-31).
      { key: "Referrer-Policy", value: "no-referrer" },
      // Answers are HTML/JS, and a browser that guesses a type from bytes can
      // be talked into running something that is not script (P11-T01).
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      // Only the framing directive: scripts and styles are left as Next emits
      // them, so a strict CSP cannot silently break a game screen.
      { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
    ];

    // HSTS is a promise about TLS. Only make it where the proxy terminates TLS.
    if (process.env.NODE_ENV === "production") {
      baseline.push({
        key: "Strict-Transport-Security",
        value: "max-age=31536000; includeSubDomains",
      });
    }

    return [{ source: "/:path*", headers: baseline }];
  },
};

export default nextConfig;
