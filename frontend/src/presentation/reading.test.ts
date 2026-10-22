import { describe, expect, it } from "vitest";
import { stories } from "../mocks/policy";
import { addRead, emptyReader, readingStats, restoreReader } from "./reading";

describe("local reading activity", () => {
  it("counts a story once per Korean day, including across detail tabs", () => {
    const initial = addRead(emptyReader(), stories[0], "2026-10-21T01:00:00Z");
    expect(addRead(initial, stories[0], "2026-10-21T03:00:00Z")).toBe(initial);
    expect(
      addRead(initial, stories[0], "2026-10-21T16:00:00Z").events,
    ).toHaveLength(2);
  });
  it("does not record when tracking is paused", () => {
    const state = { ...emptyReader(), trackingEnabled: false };
    expect(addRead(state, stories[0], "2026-10-21T01:00:00Z")).toBe(state);
  });
  it("builds a seven-day series, excludes old/future reads, and deduplicates publisher IDs", () => {
    let state = emptyReader();
    state = addRead(state, stories[0], "2026-10-14T00:00:00Z");
    state = addRead(state, stories[0], "2026-10-15T00:00:00Z");
    state = addRead(state, stories[0], "2026-10-21T00:00:00Z");
    state = addRead(state, stories[1], "2026-10-21T01:00:00Z");
    state = addRead(state, stories[0], "2026-10-22T00:00:00Z");
    const stats = readingStats(state.events, "2026-10-21");
    expect(stats.total).toBe(3);
    expect(stats.days.map((day) => day.count)).toEqual([1, 0, 0, 0, 0, 0, 2]);
    expect(
      stats.topics.find((topic) => topic.category === "technology")?.count,
    ).toBe(2);
    expect(stats.publisherCount).toBe(5);
    expect(stats.demoCount).toBe(3);
  });
  it("recovers from corrupt storage without trusting malformed activity", () => {
    expect(restoreReader("{broken")).toEqual(emptyReader());
    const state = restoreReader(
      JSON.stringify({
        version: 1,
        displayName: "  민지  ",
        trackingEnabled: false,
        events: [{ readAt: "bad" }],
      }),
    );
    expect(state.displayName).toBe("민지");
    expect(state.events).toEqual([]);
    expect(state.trackingEnabled).toBe(false);
  });
});
