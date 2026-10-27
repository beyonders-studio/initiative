import { describe, expect, it } from "vitest";

import { buildLibraryItem, buildTagSummary } from "@/__tests__/factories";
import {
  aspectRatio,
  groupByDay,
  groupByTag,
  imageLabel,
  imagePeriod,
  refuseFile,
  thumbSrc,
} from "@/lib/libraries";

const file = (type: string, size: number) => ({ type, size, name: "x" }) as unknown as File;

describe("what a picture may be", () => {
  it("takes the raster formats the server recognizes and nothing else", () => {
    expect(refuseFile(file("image/png", 10))).toBeNull();
    expect(refuseFile(file("image/webp", 10))).toBeNull();
    expect(refuseFile(file("image/svg+xml", 10))).toBe("type");
    expect(refuseFile(file("application/pdf", 10))).toBe("type");
  });

  it("refuses a file over the server's ceiling before uploading it", () => {
    expect(refuseFile(file("image/jpeg", 25 * 1024 * 1024 + 1))).toBe("size");
  });
});

describe("naming and drawing a picture", () => {
  it("falls back to the uploaded filename when nobody titled it", () => {
    expect(imageLabel(buildLibraryItem({ title: "Hero", original_filename: "a.png" }))).toBe(
      "Hero"
    );
    expect(imageLabel(buildLibraryItem({ title: null, original_filename: "a.png" }))).toBe("a.png");
    expect(imageLabel(buildLibraryItem({ title: "  ", original_filename: "a.png" }))).toBe("a.png");
  });

  it("draws the thumbnail where one was made and the picture itself where not", () => {
    expect(thumbSrc(buildLibraryItem({ thumbnail_url: "/uploads/1/t.webp" }))).toBe(
      "/uploads/1/t.webp"
    );
    expect(thumbSrc(buildLibraryItem({ thumbnail_url: null, file_url: "/uploads/1/f.png" }))).toBe(
      "/uploads/1/f.png"
    );
  });

  it("knows a picture's shape before its bytes arrive", () => {
    expect(aspectRatio(buildLibraryItem({ width: 1600, height: 800 }))).toBe(2);
    expect(aspectRatio(buildLibraryItem({ width: null, height: null }))).toBeNull();
  });
});

describe("grouping a wall", () => {
  it("files an item under the month of its date, not of when it was added", () => {
    const image = buildLibraryItem({
      occurred_on: "2026-03-05",
      created_at: "2026-05-01T12:00:00.000Z",
    });
    expect(imagePeriod(image)).toBe("2026-03");
  });

  it("puts items dated the same day side by side and keeps the list's order", () => {
    const a = buildLibraryItem({ occurred_on: "2026-03-05" });
    const b = buildLibraryItem({ occurred_on: "2026-03-05" });
    const c = buildLibraryItem({ occurred_on: "2026-03-01" });
    const groups = groupByDay([a, b, c]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[a.id, b.id], [c.id]]);
  });

  it("files a picture under every tag it carries, and the untagged last", () => {
    const picked = buildTagSummary({ name: "picked" });
    const waiting = buildTagSummary({ name: "waiting" });
    const both = buildLibraryItem({ tags: [picked, waiting] });
    const one = buildLibraryItem({ tags: [waiting] });
    const none = buildLibraryItem({ tags: [] });
    const groups = groupByTag([both, one, none]);
    expect(groups.map((g) => g.tag?.name ?? null)).toEqual(["picked", "waiting", null]);
    expect(groups[1].items.map((i) => i.id)).toEqual([both.id, one.id]);
    expect(groups[2].items.map((i) => i.id)).toEqual([none.id]);
  });
});
