import { describe, expect, it } from "vitest";

import { buildFileSummary, buildTagSummary } from "@/__tests__/factories";
import { FILE_TILE_RATIO, fileRatio, groupByDay, groupByTag } from "@/lib/collections";

describe("grouping a collection's wall", () => {
  it("puts files added the same day side by side and keeps the list's order", () => {
    // Ten minutes apart, so the same day in every zone.
    const added = (added_at: string) => ({ ...buildFileSummary(), added_at });
    const a = added("2026-03-05T12:10:00.000Z");
    const b = added("2026-03-05T12:20:00.000Z");
    const c = added("2026-03-01T12:00:00.000Z");
    const groups = groupByDay([a, b, c]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[a.id, b.id], [c.id]]);
  });

  it("stands a picture at its own shape, and a file of no known size at the wall's", () => {
    expect(fileRatio(buildFileSummary({ width: 900, height: 1600 }))).toBe(900 / 1600);
    expect(fileRatio(buildFileSummary())).toBe(FILE_TILE_RATIO);
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
