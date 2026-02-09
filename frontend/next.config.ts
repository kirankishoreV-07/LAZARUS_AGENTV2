import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy API requests to the Python backend — prevents CORS issues
  // and provides a fallback if localhost:8000 is used in fetch calls
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ];
  },
};

export default nextConfig;
