import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Searched for "barovia" from inside a community, by somebody in the campaign
// that the word fills.
test("search", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await expect(page.getByRole("heading", { name: "Primary Community", level: 1 })).toBeVisible({
    timeout: 30_000,
  });
  await page.keyboard.press("Control+k");
  const search = page.getByPlaceholder("Search in Primary Community...");
  await search.fill("barovia");
  const palette = page.getByRole("dialog");
  await expect(palette.getByText(/^See all results for/)).toBeVisible();
  await expect(palette.getByRole("option", { name: "Barovia Arc" })).toBeVisible();
  await shootHelp(page, "getting-started/search", palette);
});
