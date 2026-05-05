/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output keeps the production image small (Phase 4 deploy target).
  output: "standalone",
  reactStrictMode: true,
  // The backend lives on a separate origin in production. CORS is locked down
  // server-side; here we just ensure no accidental same-origin assumptions.
  poweredByHeader: false,
};

export default nextConfig;
