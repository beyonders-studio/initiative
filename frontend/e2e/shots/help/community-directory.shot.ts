import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("community directory", async ({ page }) => {
  await page.goto("/communities");
  await expect(page.getByRole("button", { name: "Near me" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Realm of Tides" })).toBeVisible();
  // The cards below the fold load their pictures too, so none is left waiting.
  await page.evaluate(() => {
    for (const image of document.images) image.loading = "eager";
  });
  await shootHelp(page, "communities/community-directory");
});
