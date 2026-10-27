import { describe, expect, it } from "vitest";

import { buildFileSummary, buildTagSummary } from "@/__tests__/factories";
import { groupByDay, groupByTag, monthStops } from "@/lib/collections";

describe("grouping a collection's wall", () => {
  it("puts files that arrived the same day side by side and keeps the list's order", () => {
    // Ten minutes apart, so the same day in every zone.
    const a = buildFileSummary({ created_at: "2026-03-05T12:10:00.000Z" });
    const b = buildFileSummary({ created_at: "2026-03-05T12:20:00.000Z" });
    const c = buildFileSummary({ created_at: "2026-03-01T12:00:00.000Z" });
    const groups = groupByDay([a, b, c]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[a.id, b.id], [c.id]]);
  });

  it("marks on the rail each month the days fall in, with how many arrived", () => {
    const days = groupByDay([
      buildFileSummary({ created_at: "2026-03-05T12:00:00.000Z" }),
      buildFileSummary({ created_at: "2026-03-01T12:00:00.000Z" }),
      buildFileSummary({ created_at: "2026-02-20T12:00:00.000Z" }),
    ]);
    expect(monthStops(days)).toEqual([
      { period: "2026-03", count: 2 },
      { period: "2026-02", count: 1 },
    ]);
  });

  it("files a file under every tag it carries, and the untagged last", () => {
    const picked = buildTagSummary({ name: "picked" });
    const waiting = buildTagSummary({ name: "waiting" });
    const both = buildFileSummary({ tags: [picked, waiting] });
    const one = buildFileSummary({ tags: [waiting] });
    const none = buildFileSummary({ tags: [] });
    const groups = groupByTag([both, one, none]);
    expect(groups.map((g) => g.tag?.name ?? null)).toEqual(["picked", "waiting", null]);
    expect(groups[1].items.map((i) => i.id)).toEqual([both.id, one.id]);
    expect(groups[2].items.map((i) => i.id)).toEqual([none.id]);
  });
});
