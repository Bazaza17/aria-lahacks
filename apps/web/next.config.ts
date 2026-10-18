import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";

const nextConfig: NextConfig = {
  // Mapbox GL has unstable behavior under React 19 strict mode's
  // double-mount cycle: the destroyed map's tile worker conflicts with the
  // remounted instance and tiles never request. Off until upstream fixes.
  reactStrictMode: false,
};

// Org, project and auth token come from SENTRY_ORG, SENTRY_PROJECT and
// SENTRY_AUTH_TOKEN; without a token the build skips source map upload.
export default withSentryConfig(nextConfig, {
  // Only print Sentry build logs in CI.
  silent: !process.env.CI,
});
