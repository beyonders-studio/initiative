import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// The Dungeon Master runs the campaign, so the whole window has their rail,
// their open tabs and the campaign's page.
test("tour overview", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await page.getByRole("link", { name: "Campaign: Curse of Strahd", exact: true }).first().click();
  await expect(
    page.getByRole("heading", { name: "Campaign: Curse of Strahd", level: 1 })
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("main").getByText("Barovia Arc", { exact: true })).toBeVisible();
  await shootHelp(page, "getting-started/tour-overview");
});
