import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { openCampaign } from "./strahd";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Campaign Overview holds two stats, a chart, a progress bar and a Gantt.
test("dashboard", async ({ page }) => {
  // Tall enough for the Gantt along the bottom.
  await page.setViewportSize({ width: 1280, height: 1100 });
  await openCampaign(page, "Dashboards");
  await page.getByRole("link", { name: "Campaign Overview" }).first().click();
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Campaign Overview", level: 1 })).toBeVisible({
    timeout: 30_000,
  });
  for (const title of ["Open threads", "Work by status", "Arc completion", "Session schedule"]) {
    await expect(main.getByText(title, { exact: true })).toBeVisible({ timeout: 30_000 });
  }
  // Every widget has read its rows: each says how many under its title.
  await expect(main.getByText(/ \d+ rows?$/)).toHaveCount(5, { timeout: 30_000 });
  await shootHelp(page, "dashboards/dashboard");
});
