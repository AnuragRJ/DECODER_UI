import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    host: "0.0.0.0",
    port: 3001,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8001",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  optimizeDeps: {
    // The ArcGIS SDK ships tree-shakeable ESM but is far too large for
    // esbuild pre-bundling (the optimizer service crashes on it). Serve
    // it as native ESM in dev; the production build still bundles it.
    exclude: ["@arcgis/core"],
  },
});
