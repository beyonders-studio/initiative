import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Lost Mine of Phandelver joins by request; the community admin sees the
// auto-join switch under it too.
test("join policy", async ({ page }) => {
  await page.goto("/");
  const directory = await api<{ id: number; name: string }[]>(
    page,
    "GET",
    "/c/1/initiatives/directory"
  );
  const lmop = directory.find((initiative) => initiative.name.includes("Lost Mine"));
  if (!lmop) throw new Error("No Lost Mine of Phandelver initiative");

  await page.goto(`/c/1/i/${lmop.id}/settings/members`);
  const joining = page.getByRole("radiogroup", { name: "Joining" });
  await expect(joining.getByRole("radio", { name: "By request" })).toBeChecked();
  const card = joining.locator(
    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]"
  );
  await card.evaluate((element) => element.scrollIntoView({ block: "start" }));
  await shootHelp(page, "initiatives/join-policy", card);
});
