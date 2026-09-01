import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Keep generated optimizer/config artifacts out of the dependency volume so
  // an existing root-owned Docker volume can still be read by the non-root UI.
  cacheDir: "/tmp/cambodia-rice-dss-vite",
  server: {
    host: "0.0.0.0",
    port: 3001,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
