import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { shoot } from "./shoot";

// A community that asks people to ask: its card in the directory, then the
// note a person writes to its admins. Founders' Roundtable is seeded that way
// (scripts/seed/directory.py), and the account taking the shots is not in it.
// Searched for, so its card is the only one drawn: the directory loads the
// other cards' pictures only as they scroll into view. The request is shot,
// never sent.

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("ask to join", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Join a community" }).click();
  await page.getByRole("textbox", { name: "Search communities" }).fill("Founders");
  await expect(page.getByText("1 community", { exact: true })).toBeVisible();

  const ask = page.getByRole("button", { name: "Ask to join" });
  const card = page
    .getByRole("main")
    .locator("div")
    .filter({ has: page.getByRole("heading", { name: "Founders' Roundtable" }) })
    .filter({ has: ask })
    .last();
  await expect(card).toBeVisible();
  await shoot(page, "ask-to-join-card", card);

  await ask.click();
  const dialog = page.getByRole("dialog", { name: "Ask to join Founders' Roundtable" });
  await dialog
    .getByRole("textbox")
    .fill(
      "I run a four-person map studio and we're about to hire our first contractor. I'd like to compare notes."
    );
  await shoot(page, "ask-to-join-note", dialog);
});
