import { describe, expect, it } from "vitest";

import { SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import { SMART_CHIP_MENU } from "@/components/editor/initiative/plugins/smart-chip-menu";

describe("the insert menu", () => {
  it("offers every chip the server answers", () => {
    // The pairs are generated from the server's registry, so adding one there
    // fails here until it is offered rather than being quietly unreachable.
    expect(Object.keys(SMART_CHIP_MENU).sort()).toEqual(Object.values(SmartChipKind).sort());
  });

  it("gives each one a name and something to search it by", () => {
    for (const entry of Object.values(SMART_CHIP_MENU)) {
      expect(entry.labelKey).toMatch(/^smartChips\./);
      expect(entry.keywords.length).toBeGreaterThan(0);
    }
  });
});
