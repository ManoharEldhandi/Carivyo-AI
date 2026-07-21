import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": "http://127.0.0.1:8420",
  "/health": "http://127.0.0.1:8420"
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: apiProxy
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    proxy: apiProxy
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true
  }
});
