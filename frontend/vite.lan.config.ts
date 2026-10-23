import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Keep the API on loopback; browsers on other devices use the Vite proxy.
export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_API_MODE": JSON.stringify("http"),
    "import.meta.env.VITE_API_BASE_URL": JSON.stringify("/"),
  },
  server: {
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.PRISM_LAN_API_TARGET || "http://127.0.0.1:8005",
        changeOrigin: true,
      },
    },
  },
});
