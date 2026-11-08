import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia, showTasks, taskSection } from "./barovia";
import { shoot } from "./shoot";

// Wide enough for the board's three columns side by side.
test.use({ viewport: { width: 1600, height: 1100 } });

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("subtasks on the board, banded by parent", async ({ page }) => {
  await openBarovia(page);
  await showTasks(page, "Board", "Parent task");
  await expect(page.getByRole("link", { name: "Destroy the shambling mound" })).toBeVisible();
  // The Death House's band alone: the tasks part of nothing fold away.
  await page.getByRole("button", { name: "Not part of a task" }).click();
  await shoot(page, "subtasks-board", await taskSection(page));
});
