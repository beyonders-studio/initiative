import { describe, expect, it } from "vitest";

import { buildCatalogItem, buildTagSummary } from "@/__tests__/factories";
import {
  aspectRatio,
  groupByDay,
  groupByTag,
  imageDay,
  imageLabel,
  imagePeriod,
  refuseFile,
  thumbSrc,
} from "@/lib/catalogs";

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
    expect(imageLabel(buildCatalogItem({ title: "Hero", original_filename: "a.png" }))).toBe(
      "Hero"
    );
    expect(imageLabel(buildCatalogItem({ title: null, original_filename: "a.png" }))).toBe("a.png");
    expect(imageLabel(buildCatalogItem({ title: "  ", original_filename: "a.png" }))).toBe("a.png");
  });

  it("draws the thumbnail where one was made and the picture itself where not", () => {
    expect(thumbSrc(buildCatalogItem({ thumbnail_url: "/uploads/1/t.webp" }))).toBe(
      "/uploads/1/t.webp"
    );
    expect(thumbSrc(buildCatalogItem({ thumbnail_url: null, file_url: "/uploads/1/f.png" }))).toBe(
      "/uploads/1/f.png"
    );
  });

  it("knows a picture's shape before its bytes arrive", () => {
    expect(aspectRatio(buildCatalogItem({ width: 1600, height: 800 }))).toBe(2);
    expect(aspectRatio(buildCatalogItem({ width: null, height: null }))).toBeNull();
  });
});

describe("grouping a wall", () => {
  it("cuts days and months in the reader's own zone", () => {
    const image = buildCatalogItem({ created_at: "2026-03-05T12:00:00.000Z" });
    const local = new Date(image.created_at);
    expect(imageDay(image)).toBe(
      `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, "0")}-${String(local.getDate()).padStart(2, "0")}`
    );
    expect(imagePeriod(image)).toBe(
      `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, "0")}`
    );
  });

  it("puts pictures from the same day side by side and keeps the list's order", () => {
    const a = buildCatalogItem({ created_at: "2026-03-05T18:00:00.000Z" });
    const b = buildCatalogItem({ created_at: "2026-03-05T17:00:00.000Z" });
    const c = buildCatalogItem({ created_at: "2026-03-01T17:00:00.000Z" });
    const groups = groupByDay([a, b, c]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[a.id, b.id], [c.id]]);
  });

  it("files a picture under every tag it carries, and the untagged last", () => {
    const picked = buildTagSummary({ name: "picked" });
    const waiting = buildTagSummary({ name: "waiting" });
    const both = buildCatalogItem({ tags: [picked, waiting] });
    const one = buildCatalogItem({ tags: [waiting] });
    const none = buildCatalogItem({ tags: [] });
    const groups = groupByTag([both, one, none]);
    expect(groups.map((g) => g.tag?.name ?? null)).toEqual(["picked", "waiting", null]);
    expect(groups[1].items.map((i) => i.id)).toEqual([both.id, one.id]);
    expect(groups[2].items.map((i) => i.id)).toEqual([none.id]);
  });
});
