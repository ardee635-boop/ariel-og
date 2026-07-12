import { defineConfig } from "vite";

// Dev-only proxy: forwards /api/* to the live Render backend so
// `npm run dev` can actually hit real auth/player endpoints locally.
// This block has no effect on the Vercel production build — on
// Vercel, /api routing is handled separately (vercel.json rewrite
// or same-origin API routes).
//
// No React plugin here anymore — the site is plain index.html/CSS/JS,
// Vite just serves and bundles it directly. If src/ and the old React
// app ever come back, re-add @vitejs/plugin-react to plugins: [].
export default defineConfig({
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
