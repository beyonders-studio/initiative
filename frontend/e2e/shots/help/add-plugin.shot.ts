import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

const LISTING = "core.guild-calendar";

// Adding a plug-in is the seat's job. The dialog is opened and closed again;
// nothing is added.
test("add plug-in", async ({ page }) => {
  await signInAs(page, "superadmin@example.com");
  const installed = await api<{ items: { listing_uid: string }[] }>(page, "GET", "/c/1/plugins/");
  const listing = await api<{ uid: string }>(page, "GET", `/c/1/marketplace/listings/${LISTING}`);
  if (installed.items.some((plugin) => plugin.listing_uid === listing.uid)) {
    throw new Error("Community calendar is already added to Primary Community");
  }

  await page.goto(`/c/1/marketplace/${LISTING}`);
  await page.getByRole("button", { name: "Add to community" }).click();
  const dialog = page.getByRole("dialog", { name: "Add Community calendar" });
  await expect(dialog.getByLabel("Name")).toHaveValue("Community calendar");
  await page.locator(":focus").blur();
  await shootHelp(page, "marketplace/add-plugin", dialog);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  const after = await api<{ items: unknown[] }>(page, "GET", "/c/1/plugins/");
  expect(after.items).toHaveLength(installed.items.length);
});
