import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

type Preferences = { items: Record<string, unknown> };

/** The person's home views and layouts, as stored. */
const homePreferences = async (page: Parameters<typeof api>[0]) => {
  const { items } = await api<Preferences>(page, "GET", "/user-view-preferences");
  return Object.fromEntries(Object.entries(items).filter(([key]) => key.startsWith("home:")));
};

// The Dungeon Master's Home while customizing, their Focus list full of the
// campaign's tasks. Customizing saves nothing until a widget moves, so the
// shot presses Done untouched and checks Home is stored as it was.
test("home customize", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await signInAs(page, "user1@example.com");
  const before = await homePreferences(page);
  const customize = page.getByRole("button", { name: "Customize" });
  await expect(customize).toBeEnabled({ timeout: 30_000 });
  await customize.click();
  const done = page.getByRole("button", { name: "Done" });
  await expect(done).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove My tasks" })).toBeVisible();

  // A clear frame over the page marks the crop: from under the shell's bar of
  // open tabs, which change with whatever was opened last, to the top of the
  // third widget.
  await page
    .locator("[data-home-tile-handle]")
    .nth(2)
    .evaluate((third) => {
      const area = third.closest("main")?.parentElement;
      const bar = area?.previousElementSibling;
      if (!area || !bar) throw new Error("No shell bar above the page");
      const top = bar.getBoundingClientRect().bottom;
      const { left, width } = area.getBoundingClientRect();
      const frame = document.createElement("div");
      frame.dataset.shotFrame = "";
      Object.assign(frame.style, {
        position: "fixed",
        left: `${left}px`,
        top: `${top}px`,
        width: `${width}px`,
        height: `${third.getBoundingClientRect().top + 60 - top}px`,
        pointerEvents: "none",
      });
      document.body.append(frame);
    });
  await shootHelp(page, "your-space/home-customize", page.locator("[data-shot-frame]"));

  await done.click();
  await expect(customize).toBeVisible();
  expect(await homePreferences(page)).toEqual(before);
});
