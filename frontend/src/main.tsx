import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});
async function start() {
  const mode = import.meta.env.VITE_API_MODE || "mock";
  if (!["mock", "http"].includes(mode))
    throw new Error("VITE_API_MODE must be mock or http");
  if (mode === "mock") {
    const { worker } = await import("./mocks/browser");
    await worker.start({
      onUnhandledRequest(request, print) {
        const path = new URL(request.url).pathname;
        if (path.startsWith("/api/") && !path.startsWith("/api/social/"))
          print.error();
      },
    });
  } else if ("serviceWorker" in navigator) {
    // Stop a previous MSW registration from intercepting an HTTP-mode session.
    const registrations = await navigator.serviceWorker.getRegistrations();
    for (const registration of registrations) {
      const script =
        registration.active?.scriptURL ||
        registration.waiting?.scriptURL ||
        registration.installing?.scriptURL ||
        "";
      if (script.endsWith("/mockServiceWorker.js"))
        await registration.unregister();
    }
    if (
      navigator.serviceWorker.controller?.scriptURL.endsWith(
        "/mockServiceWorker.js",
      )
    ) {
      location.reload();
      return;
    }
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  );
}
start().catch(() => {
  const root = document.getElementById("root")!;
  root.textContent =
    "시작하지 못했습니다. localhost 접속, API 설정과 브라우저 콘솔을 확인한 후 새로고침해주세요.";
});
