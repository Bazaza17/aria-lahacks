import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Mapbox GL has unstable behavior under React 19 strict mode's
  // double-mount cycle: the destroyed map's tile worker conflicts with the
  // remounted instance and tiles never request. Off until upstream fixes.
  reactStrictMode: false,
};

export default nextConfig;
