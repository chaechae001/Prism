import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
const origin = process.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const url = new URL(origin);
if (
  !["http:", "https:"].includes(url.protocol) ||
  url.username ||
  url.password ||
  url.pathname !== "/" ||
  url.search ||
  url.hash
) {
  throw new Error(
    "VITE_API_BASE_URL must be an HTTP(S) origin without a path or credentials.",
  );
}
const vite = fileURLToPath(
  new URL("../node_modules/vite/bin/vite.js", import.meta.url),
);
const child = spawn(
  process.execPath,
  [vite, "--host", "127.0.0.1", ...process.argv.slice(2)],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      VITE_API_MODE: "http",
      VITE_API_BASE_URL: url.origin,
    },
  },
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 0;
});
