import { describe, it, expect } from "vitest";
import {
  dateKey,
  validDay,
  moveDay,
  visibleItems,
  groupTimeline,
  weekDays,
  selectStoryReel,
} from "./timeline";
import { stories } from "../mocks/policy";
import type { FeedItem } from "../api/types";

function item(id: string, updated: string): FeedItem {
  return {
    story: { ...stories[0], id, updated_at: updated },
    reason: { code: "latest", label: "latest" },
  };
}
const rows = [
  item("a", "2026-10-20T16:00:00Z"),
  item("b", "2026-10-20T05:00:00Z"),
  item("c", "2026-10-19T21:00:00Z"),
];

describe("timeline dates use Korea time, not the browser timezone", () => {
  it("opens the selected news rather than the first news on the same date", () => {
    const reel = selectStoryReel(rows, "c");
    expect(reel.stories.map((s) => s.id)).toEqual(["b", "c"]);
    expect(reel.stories[reel.initial].id).toBe("c");
  });
  it("keeps edition navigation scoped to the event date", () => {
    const reel = selectStoryReel(rows, "a", { a: "2026-10-20" });
    expect(reel.stories.map((s) => s.id)).toEqual(["a", "b", "c"]);
    expect(reel.initial).toBe(0);
  });
  it("does not open stale or unselected story IDs", () => {
    expect(selectStoryReel(rows, "removed").stories).toEqual([]);
    expect(selectStoryReel(rows, null).stories).toEqual([]);
  });
  it("uses the v2 event date instead of the last article update date", () => {
    expect(groupTimeline([rows[0]], { a: "2026-10-19" })[0].day).toBe(
      "2026-10-19",
    );
  });
  it("groups UTC midnight crossings into the correct Korean day", () => {
    expect(dateKey("2026-10-20T16:00:00Z")).toBe("2026-10-21");
    expect(
      groupTimeline(rows).map((g) => [g.day, g.items.map((i) => i.story.id)]),
    ).toEqual([
      ["2026-10-21", ["a"]],
      ["2026-10-20", ["b", "c"]],
    ]);
  });
  it("filters a single day and inclusive date ranges without inventing entries", () => {
    expect(
      visibleItems(rows, "2026-10-20", "", "").map((i) => i.story.id),
    ).toEqual(["b", "c"]);
    expect(visibleItems(rows, "", "2026-10-20", "2026-10-21")).toHaveLength(3);
    expect(visibleItems(rows, "2026-10-18", "", "")).toEqual([]);
  });
  it("rejects malformed and impossible dates", () => {
    expect(validDay("2026-02-30")).toBe(false);
    expect(validDay("2026-13-01")).toBe(false);
    expect(validDay("2026-2-01")).toBe(false);
    expect(validDay("2024-02-29")).toBe(true);
  });
  it("builds date strips across month and year boundaries", () => {
    expect(moveDay("2026-01-01", -1)).toBe("2025-12-31");
    expect(weekDays("2026-01-03", 0)).toEqual([
      "2025-12-28",
      "2025-12-29",
      "2025-12-30",
      "2025-12-31",
      "2026-01-01",
      "2026-01-02",
      "2026-01-03",
    ]);
    expect(weekDays("2026-01-03", -1)[6]).toBe("2025-12-27");
  });
});
