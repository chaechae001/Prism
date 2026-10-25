import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Keep the API on loopback; browsers on other devices use the Vite proxy.
export default defineConfig({
  plugins: [react(), {
    name: "prism-lan-read-only",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = (request.url || "").split("?")[0];
        if ((path === "/api" || path.startsWith("/api/")) &&
            !["GET", "HEAD"].includes(request.method || "GET")) {
          response.statusCode = 403;
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.end(JSON.stringify({ error: {
            code: "LAN_READ_ONLY",
            message: "내부망 미리보기는 읽기 전용입니다. AI 대화는 개발 PC의 로컬 화면에서 이용해주세요.",
          } }));
          return;
        }
        next();
      });
    },
  }],
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
