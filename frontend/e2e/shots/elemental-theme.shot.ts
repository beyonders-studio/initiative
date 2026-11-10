import { expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { shoot } from "./shoot";

// The Elemental theme: its tile in the picker with the elements to choose
// from, then a community's Members page wearing Gold, where the sidebar, the
// borders and the buttons show the sheen. The account goes back to
// Kobold afterwards, so the shots after this one are not taken in gold.

test.beforeEach(async ({ page }) => laterForUpdates(page));

/** Choose a theme on the Interface page and wait for it to be saved. */
async function chooseTheme(page: Page, name: string) {
  await page.goto("/profile/interface");
  const picker = page.getByRole("radiogroup", { name: "Color theme" });
  const option = picker.getByRole("radio", { name, exact: true });
  await expect(option).toBeVisible();
  const saved = page.waitForResponse(
    (response) => response.request().method() === "PATCH" && response.url().endsWith("/api/v1/me")
  );
  await option.click();
  await saved;
  return picker;
}

test("elemental theme", async ({ page }) => {
  try {
    const picker = await chooseTheme(page, "Use Gold");
    const tile = picker
      .locator("div")
      .filter({ has: page.getByRole("radio", { name: "Elemental", exact: true }) })
      .last();
    await expect(tile.getByRole("radio", { name: "Use Gold" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    await shoot(page, "elemental-theme", tile);

    // From a fresh page, so the toast that confirmed the save is gone.
    await page.goto("/");
    await page.getByRole("button", { name: "Switch to Primary Community" }).click();
    await page.getByRole("link", { name: /^\d+ members$/ }).click();
    await expect(page.getByRole("row", { name: /vex-shadowstep/ })).toBeVisible();
    await shoot(page, "elemental-members");
  } finally {
    await chooseTheme(page, "Kobold");
  }
});
