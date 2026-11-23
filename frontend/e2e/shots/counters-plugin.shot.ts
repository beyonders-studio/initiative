import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openCampaign } from "./help/strahd";
import { shoot } from "./shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// One card is small: taken at twice the pixels, so it reads at the dialog's
// width.
test.use({ deviceScaleFactor: 2 });

// The Counters plug-in in Campaign: Curse of Strahd, as its Dungeon Master
// sees it: Party Vitals' card, with a counter in each look (bars, a number and
// a segmented clock). On a big desktop, where the card is wide enough to set
// each counter's name on one line.
test("counters plugin", async ({ page }) => {
  await page.setViewportSize({ width: 1700, height: 900 });
  await openCampaign(page, "Counters");
  const card = page
    .getByRole("tabpanel", { name: "Counters" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "Party Vitals (Strahd)", exact: true }) });
  await expect(card.getByRole("link", { name: "Long Rest Clock" })).toBeVisible({
    timeout: 30_000,
  });
  await shoot(page, "counters-plugin", card);
});
