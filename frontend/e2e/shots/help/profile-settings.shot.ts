import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

interface Packs {
  items: { uid: string; public_id: string; installed: boolean }[];
}

// The core set has one trophy, so the shot takes the Books pack first (once),
// then picks a look without saving it: the card shows it all the same.
test("profile settings", async ({ page }) => {
  // Tall enough for the card and every picker at once.
  await page.setViewportSize({ width: 1280, height: 1290 });
  await page.goto("/profile");
  const packs = await api<Packs>(page, "GET", "/me/decoration-packs");
  const books = packs.items.find((pack) => pack.public_id === "core.books");
  if (books && !books.installed) {
    await api(page, "POST", `/me/decoration-packs/${books.uid}`);
    await page.reload();
  }

  await expect(page.getByText("Your look", { exact: true })).toBeVisible();
  for (const name of ["Aurora", "Gilded", "Number one fan", "Stack", "Quill and ink"]) {
    await page.getByLabel(name, { exact: true }).click({ force: true });
  }
  await expect(page.getByRole("button", { name: "Save look" })).toBeEnabled();
  await page.locator(":focus").blur();
  await shootHelp(page, "account/profile-settings");
});
