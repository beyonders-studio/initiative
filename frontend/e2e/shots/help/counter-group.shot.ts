import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { openCampaign } from "./strahd";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Party Vitals holds one counter of each view mode: hit points as progress
// bars, a number and a segmented clock. The group's page lists them in its
// Counter section.
test("counter group", async ({ page }) => {
  await openCampaign(page, "Counters");
  await page.getByText("Party Vitals (Strahd)", { exact: true }).click();
  const counters = page
    .getByRole("main")
    .locator("section")
    .filter({ has: page.getByRole("button", { name: "Counter", exact: true }) });
  await expect(counters.getByRole("link", { name: "Long Rest Clock" })).toBeVisible({
    timeout: 30_000,
  });
  // Tall enough for the whole section, with the floating buttons under it.
  const box = await counters.boundingBox();
  if (!box) throw new Error("The Counter section has no box");
  await page.setViewportSize({ width: 1280, height: Math.ceil(box.y + box.height) + 96 });
  await shootHelp(page, "counters/counter-group", counters);
});
