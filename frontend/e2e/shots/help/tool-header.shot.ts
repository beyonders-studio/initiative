import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { openCampaign } from "./strahd";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Barovia Arc as the Dungeon Master sees it: the band in the campaign's colour,
// the breadcrumb and Settings, the name with its bookmark and bell, and the
// strip under it. Wide enough for the whole strip to fit without scrolling.
test("tool header", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCampaign(page);
  await page.getByRole("main").getByText("Barovia Arc", { exact: true }).first().click();
  const title = page.getByRole("heading", { name: "Barovia Arc", level: 1 });
  await expect(title).toBeVisible({ timeout: 30_000 });
  const header = page.locator("header").filter({ has: title });
  await expect(header.getByRole("link", { name: "Settings" })).toBeVisible();
  await expect(header.getByText("Metadata", { exact: true })).toBeVisible();

  // The header runs up behind the shell's bar of open tabs, which change with
  // whatever was opened last. A clear frame over the page marks the crop: from
  // under that bar to just below the strip.
  await header.evaluate((element) => {
    const area = element.closest("main")?.parentElement;
    const bar = area?.previousElementSibling;
    if (!area || !bar) throw new Error("No shell bar above the page");
    const top = bar.getBoundingClientRect().bottom;
    const { left, width } = area.getBoundingClientRect();
    const frame = document.createElement("div");
    frame.dataset.shotFrame = "";
    Object.assign(frame.style, {
      position: "fixed",
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${element.getBoundingClientRect().bottom + 16 - top}px`,
      pointerEvents: "none",
    });
    document.body.append(frame);
  });
  await shootHelp(page, "tools/tool-header", page.locator("[data-shot-frame]"));
});
