/** @type {import('next').NextConfig} */
// All browser calls go to /api/* on the Next.js server, which proxies them to the FastAPI backend.
// This avoids CORS entirely and lets the frontend work from any host/port.
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  experimental: { proxyTimeout: 300000 },   // long-running requests (e.g. the 6-test security suite)
};

export default nextConfig;
