import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Everything is bundled locally: no CDN, no remote fonts, no telemetry.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 6000,
    // Plotly is large; keep it in its own chunk so the rest of the app loads fast.
    rollupOptions: { output: { manualChunks: { plotly: ["plotly.js-dist-min"], osd: ["openseadragon"] } } },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "https://localhost:8443", secure: false },
      "/auth": { target: "https://localhost:8443", secure: false },
    },
  },
});
