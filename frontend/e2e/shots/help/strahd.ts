import { expect, type Page } from "@playwright/test";

import { signInAs } from "../signedIn";

/**
 * Campaign: Curse of Strahd, the seed's fullest initiative
 * (scripts/seed/initiatives.py), as the Dungeon Master who runs it, open on
 * the tool tab `tab` ("Counters", "Calendar", …) or on its projects.
 */
export async function openCampaign(page: Page, tab?: string) {
  await signInAs(page, "user1@example.com");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await page.getByRole("link", { name: "Campaign: Curse of Strahd", exact: true }).first().click();
  const main = page.getByRole("main");
  await expect(
    main.getByRole("heading", { name: "Campaign: Curse of Strahd", level: 1 })
  ).toBeVisible({ timeout: 30_000 });
  if (tab) {
    await main
      .getByRole("tab", { name: tab, exact: true })
      .or(main.getByRole("link", { name: tab, exact: true }))
      .click();
  }
}
