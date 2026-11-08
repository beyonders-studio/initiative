import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// What you hear about, whole: every group of rows and every channel.
test("notification settings", async ({ page }) => {
  // Tall enough for the whole card.
  await page.setViewportSize({ width: 1280, height: 1800 });
  await page.goto("/profile/notifications");
  const title = page.getByText("What you hear about", { exact: true });
  await expect(title).toBeVisible();
  await expect(page.getByRole("switch", { name: "Mentions and replies on Bell" })).toBeVisible();
  const card = title.locator(
    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]"
  );
  await card.evaluate((element) => element.scrollIntoView({ block: "start" }));
  await shootHelp(page, "notifications/settings", card);
});
