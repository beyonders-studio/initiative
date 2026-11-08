import { beforeEach, describe, expect, it } from "vitest";

import { getItem, removeItem } from "@/lib/storage";

import { takeVersionChange } from "./UpdatedNotice";

const KEY = "initiative-last-run-version";

describe("takeVersionChange", () => {
  beforeEach(() => removeItem(KEY));

  it("says nothing on a first run, and remembers the version", () => {
    expect(takeVersionChange("1.0.0")).toBe(false);
    expect(getItem(KEY)).toBe("1.0.0");
  });

  it("says so once after moving to a newer version", () => {
    takeVersionChange("1.0.0");
    expect(takeVersionChange("1.1.0")).toBe(true);
    expect(takeVersionChange("1.1.0")).toBe(false);
  });

  it("says nothing after moving back to an older version", () => {
    takeVersionChange("1.1.0");
    expect(takeVersionChange("1.0.0")).toBe(false);
    expect(getItem(KEY)).toBe("1.0.0");
  });
});
