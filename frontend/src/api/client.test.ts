import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});
describe("API failure boundaries", () => {
  it("sends feed filters through the supported news API", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, next_cursor: null })),
    );
    vi.stubGlobal("fetch", fetcher);
    await api.feed({ q: "버스", category: "society", mode: "balanced", diversity: 70, scenario: "normal" }, null);
    const [path, options] = fetcher.mock.calls[0];
    expect(String(path)).toContain("/api/v1/stories?");
    expect(String(path)).toContain("category=society");
    expect(String(path)).toContain("diversity=70");
    expect(options.headers).toEqual({ "X-Mock-Scenario": "normal" });
  });
  it("keeps the request ID when the server returns HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<h1>Bad gateway</h1>", {
          status: 502,
          headers: { "X-Request-ID": "req-html" },
        }),
      ),
    );
    await expect(api.story("one")).rejects.toMatchObject({
      status: 502,
      requestId: "req-html",
    });
  });
  it("explains a closed API server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(api.categories()).rejects.toBeInstanceOf(ApiError);
    await expect(api.categories()).rejects.toMatchObject({
      status: 0,
      requestId: "unavailable",
    });
  });
  it("preserves query cancellation", async () => {
    const aborted = new DOMException("Aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(aborted));
    await expect(api.categories()).rejects.toBe(aborted);
  });
  it("uses the common JSON error and request ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { message: "읽기 실패", request_id: "req-json" },
          }),
          { status: 500 },
        ),
      ),
    );
    await expect(api.story("one")).rejects.toMatchObject({
      message: "읽기 실패",
      status: 500,
      requestId: "req-json",
    });
  });
});
