import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia } from "./barovia";
import { shoot } from "./shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("title details", async ({ page }) => {
  // On for every account unless switched off; a dev database migrated before
  // that default may have it off.
  await page.goto("/profile/interface");
  const reads = page.getByRole("switch", { name: "Read details from the title" });
  await expect(reads).toBeVisible();
  if ((await reads.getAttribute("aria-checked")) !== "true") await reads.click();
  await expect(reads).toHaveAttribute("aria-checked", "true");

  await openBarovia(page);
  await page.getByRole("main").getByRole("button", { name: "Add task" }).click();
  const dialog = page.getByRole("dialog", { name: "Create task" });
  const title = dialog.getByRole("textbox", { name: "Task" });
  await title.pressSequentially(
    "Restock the healing potions every third tuesday at 3pm !high #quest @arch"
  );
  // Picked from the list under `@`: one of the seed's party.
  await dialog.getByRole("button", { name: /archivist-okoro/ }).click();
  const read = dialog.getByRole("list", { name: "Read from the title" });
  await expect(read).toContainText("High priority");
  await expect(read).toContainText("quest");
  await expect(dialog.getByRole("combobox", { name: "Priority" })).toHaveText("High");
  await shoot(page, "title-details", dialog);
});
