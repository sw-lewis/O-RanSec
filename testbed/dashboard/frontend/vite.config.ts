import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, forward API and WebSocket calls to a backend reachable on :8660.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8660",
      "/ws": { target: "ws://127.0.0.1:8660", ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 2000 },
});
