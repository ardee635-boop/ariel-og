import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // During local dev, proxy API calls to the bot's Node server so the
    // session cookie plays nicely under one origin instead of fighting
    // CORS/cookie rules locally. In production (Vercel), the site and
    // API are genuinely cross-origin — see index.js's cookie config
    // (secure + sameSite: 'none') for that case.
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:3000",
        changeOrigin: true,
      },
    },
  },
});
