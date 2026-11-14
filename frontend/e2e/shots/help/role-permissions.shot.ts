import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Lost Mine of Phandelver's roles, as the community admin sees them.
test("role permissions", async ({ page }) => {
  await page.goto("/");
  const directory = await api<{ id: number; name: string }[]>(
    page,
    "GET",
    "/c/1/initiatives/directory"
  );
  const lmop = directory.find((initiative) => initiative.name.includes("Lost Mine"));
  if (!lmop) throw new Error("No Lost Mine of Phandelver initiative");

  // Tall enough to reach Add custom role under the cards.
  await page.setViewportSize({ width: 1280, height: 960 });
  await page.goto(`/c/1/i/${lmop.id}/settings/roles`);
  await expect(page.getByRole("button", { name: "Add custom role" })).toBeVisible();
  await shootHelp(page, "sharing/role-permissions");
});
