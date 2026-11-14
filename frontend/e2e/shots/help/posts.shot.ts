import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Curse of Strahd's board as its Dungeon Master sees it: the pinned notices,
// then the poll on the finale.
test("posts", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  const initiatives = await api<{ id: number; name: string }[]>(page, "GET", "/c/1/initiatives/");
  const strahd = initiatives.find((initiative) => initiative.name === "Campaign: Curse of Strahd");
  if (!strahd) throw new Error("No Curse of Strahd initiative");

  await page.setViewportSize({ width: 1280, height: 2400 });
  await page.goto(`/c/1/i/${strahd.id}/posts`);
  await expect(page.getByText(/^Pinned until /)).toBeVisible();
  await expect(page.getByText("Which night?")).toBeVisible();
  // The window ends with the poll's notice, the floating buttons over the
  // empty end of its reactions row.
  const poll = page
    .getByText("Which night suits everyone for the finale?")
    .locator(
      "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]"
    );
  await expect(poll.getByText(/^Read by /)).toBeVisible();
  await page.waitForLoadState("networkidle");
  const box = await poll.boundingBox();
  if (!box) throw new Error("The poll's notice is not on the board");
  await page.setViewportSize({ width: 1280, height: Math.ceil(box.y + box.height + 12) });
  await shootHelp(page, "tools/posts");
});
