import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { openCampaign } from "./strahd";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Party Vitals holds one counter of each view mode: hit points as progress
// bars, a number and a segmented clock.
test("counter group", async ({ page }) => {
  await openCampaign(page, "Counters");
  await page.getByText("Party Vitals (Strahd)", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Reset All" })).toBeVisible({ timeout: 30_000 });
  const last = page.getByText("Long Rest Clock");
  await expect(last).toBeVisible();
  // Tall enough for the last counter whole, with the floating buttons under it.
  const box = await last.locator("xpath=../..").boundingBox();
  if (!box) throw new Error("Long Rest Clock has no box");
  await page.setViewportSize({ width: 1280, height: Math.ceil(box.y + box.height) + 96 });
  await shootHelp(page, "counters/counter-group", page.getByRole("main"));
});
