import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { shoot } from "./shoot";

// Time out a member: the dialog a community admin opens from a member's row
// on the Members page, with its lengths open. The whole window, since the list
// of lengths opens outside the dialog. Shot open, never sent, so nobody is
// timed out.

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("time out a member", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await page.getByRole("link", { name: /^\d+ members$/ }).click();
  await expect(page.getByRole("row", { name: /vex-shadowstep/ })).toBeVisible();

  await page.getByRole("button", { name: "Actions for vex-shadowstep" }).click();
  await page.getByRole("menuitem", { name: "Time out…" }).click();
  const dialog = page.getByRole("alertdialog", { name: /^Time out / });
  await dialog.getByRole("combobox", { name: "For" }).click();
  await expect(page.getByRole("option", { name: "Until a date" })).toBeVisible();
  await shoot(page, "time-out-member");
});
