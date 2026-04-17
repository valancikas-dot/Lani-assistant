import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Tauri expects a fixed dev server port
  server: {
    port: 1420,
    strictPort: true,
  },
  // prevent vite from obscuring Tauri errors
  clearScreen: false,
  // Tauri's environment variables
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    // Tauri uses Chromium on macOS/Linux and WebKit on iOS/Android
    target: ["es2021", "chrome105", "safari15"],
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
  // @ts-expect-error vitest config not in vite types
  test: {
    environment: "node",
  },
});
