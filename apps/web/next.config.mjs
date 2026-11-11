const api = process.env.NEXT_PUBLIC_API_URL ?? "";
const supabase = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const dev = process.env.NODE_ENV !== "production";

// R2 pre-signed URLs live on <account>.r2.cloudflarestorage.com. NEXT_PUBLIC_STORAGE_ORIGIN adds one more storage origin: a custom
// domain in front of R2, or the local S3 double of the dev stack (python -m aro_cloud.dev.stack).
const r2 = ["https://*.r2.cloudflarestorage.com", process.env.NEXT_PUBLIC_STORAGE_ORIGIN ?? ""].join(" ").trim();
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${r2}`,
  `connect-src 'self' ${api} ${supabase} ${r2} blob: data:${dev ? " ws:" : ""}`,
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
