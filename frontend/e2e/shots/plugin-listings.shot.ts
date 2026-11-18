import { expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { shootMarketplace } from "./shoot";
import { signInAs } from "./signedIn";

// The pictures on the marketplace listings of the built-in plug-ins, of what
// each puts in a community: the seed installs both in Primary Community
// (scripts/seed/plugins.py). Taken as user1, a member, who sees them as
// everyone in the community does: the page alone, so the listing's small
// pictures stay legible.

test.beforeEach(async ({ page }) => laterForUpdates(page));

async function openCommunity(page: Page) {
  await signInAs(page, "user1@example.com");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
}

test("community calendar", async ({ page }) => {
  await openCommunity(page);
  await page.getByRole("link", { name: "Community calendar", exact: true }).first().click();
  // The list, not the month: the seed dates its events from today, so a month
  // could hold one of them.
  await page.getByRole("tab", { name: "List", exact: true }).click();
  await expect(page.getByText("Community meetup").first()).toBeVisible({ timeout: 30_000 });
  await shootMarketplace(page, "community-calendar", page.getByRole("main"));
});

test("community contacts", async ({ page }) => {
  await openCommunity(page);
  await page.getByRole("link", { name: "Community contacts", exact: true }).first().click();
  await expect(page.getByText("Tessa Ravenwood").first()).toBeVisible({ timeout: 30_000 });
  await shootMarketplace(page, "community-contacts", page.getByRole("main"));
});
