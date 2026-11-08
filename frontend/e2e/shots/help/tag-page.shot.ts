import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// The "combat" tag as the Dungeon Master sees it: three projects on the
// Projects tab, and the tagged tasks inside them below.
test("tag page", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  const tags = await api<{ id: number; name: string }[]>(page, "GET", "/c/1/tags/");
  const combat = tags.find((tag) => tag.name === "combat");
  if (!combat) throw new Error("No combat tag");

  // Tall enough for both tables.
  await page.setViewportSize({ width: 1280, height: 1200 });
  await page.goto(`/c/1/tags/${combat.id}`);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "combat", level: 1 })).toBeVisible({
    timeout: 30_000,
  });
  await expect(main.getByRole("tab", { name: /^Projects/, selected: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: /^Tasks/, level: 2 })).toBeVisible();
  await shootHelp(page, "tags/tag-page");
});
