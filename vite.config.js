import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy: forwards /api/* to the live Render backend so
// `npm run dev` can actually hit real auth/player endpoints locally.
// This block has no effect on the Vercel production build — on
// Vercel, /api routing is handled separately (vercel.json rewrite
// or same-origin API routes).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "https://ariel-bot-38kh.onrender.com",
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
