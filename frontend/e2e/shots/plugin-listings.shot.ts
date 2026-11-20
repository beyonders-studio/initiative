import { expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openCampaign } from "./help/strahd";
import { shootMarketplace } from "./shoot";
import { signInAs } from "./signedIn";

// The pictures on the marketplace listings of the built-in plug-ins, of what
// each puts in a community: the seed installs them in Primary Community
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

// Counters, in Campaign: Curse of Strahd (scripts/seed/initiatives.py), as
// user1 sees it. At a laptop's width and twice the pixels, so the pictures are
// sharp in the listing's lightbox.
test.describe("counters", () => {
  test.use({ deviceScaleFactor: 2 });

  test("counters groups", async ({ page }) => {
    await openCampaign(page, "Counters");
    const card = page
      .getByRole("main")
      .getByRole("listitem")
      .filter({ has: page.getByRole("link", { name: "Party Vitals (Strahd)", exact: true }) });
    await expect(card.getByRole("link", { name: "Long Rest Clock" })).toBeVisible({
      timeout: 30_000,
    });
    // The tab's own panel: the initiative's header above it holds its
    // manager's settings button.
    await shootMarketplace(
      page,
      "counters-groups",
      page.getByRole("tabpanel", { name: "Counters" })
    );
  });

  test("counters group", async ({ page }) => {
    await openCampaign(page, "Counters");
    await page.getByText("Party Vitals (Strahd)", { exact: true }).click();
    // The group's Counter section, with a counter in each look: hit points as
    // progress bars, a number and a segmented clock.
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
    await shootMarketplace(page, "counters-group", counters);
  });

  test("counters full screen", async ({ page }) => {
    await openCampaign(page, "Counters");
    await page.getByText("Party Vitals (Strahd)", { exact: true }).click();
    await page.getByRole("main").getByRole("link", { name: "Thorn HP" }).click();
    await page.getByRole("button", { name: "Open Count full screen" }).click();
    await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
    await shootMarketplace(page, "counters-full-screen");
  });
});
