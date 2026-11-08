import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia, showTasks, taskSection } from "./barovia";
import { shoot } from "./shoot";

// As wide as the board's picture beside it, so the table shows its dates.
test.use({ viewport: { width: 1600, height: 1100 } });

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("subtasks in the table", async ({ page }) => {
  await openBarovia(page);
  await showTasks(page, "Table");
  await expect(
    page.getByRole("button", { name: "Hide the subtasks of Survive the Death House" })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Destroy the shambling mound" })).toBeVisible();
  await shoot(page, "subtasks-table", await taskSection(page));
});
