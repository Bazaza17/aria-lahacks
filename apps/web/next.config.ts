import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Mapbox GL has unstable behavior under React 19 strict mode's
  // double-mount cycle: the destroyed map's tile worker conflicts with the
  // remounted instance and tiles never request. Off until upstream fixes.
  reactStrictMode: false,
  // Next's gzip holds back the console's live event stream (/live/stream) until it closes.
  // Vercel compresses at its edge anyway, so this only affects dev and `next start`.
  compress: false,
  // The live dispatch console (apps/api/app/creao/view.html) and every /live/* call it makes
  // go through this app, so the whole demo is one address (localhost:3000/live/view).
  // The building engine runs in the API too (/engine/viewer?start=…).
  async rewrites() {
    return [
      { source: "/live/:path*", destination: `${API_ORIGIN}/live/:path*` },
      { source: "/engine/:path*", destination: `${API_ORIGIN}/engine/:path*` },
    ];
  },
};

// Org, project and auth token come from SENTRY_ORG, SENTRY_PROJECT and
// SENTRY_AUTH_TOKEN; without a token the build skips source map upload.
export default withSentryConfig(nextConfig, {
  // Only print Sentry build logs in CI.
  silent: !process.env.CI,
  // Send browser events, replays and traces through our own origin so ad
  // blockers don't drop them. A fixed path (not `true`) so a future proxy.ts
  // matcher can exclude it; there's no proxy/middleware today.
  tunnelRoute: "/aria-relay",
});
