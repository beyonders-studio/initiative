import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

/** Lost Mine of Phandelver takes requests; these two are in the community and not in it. */
const ASKING = [
  {
    email: "user4@example.com",
    message: "I run a rogue in the Barovia game and would love a second table.",
  },
  { email: "user5@example.com", message: "Happy to play the cleric if you are short one." },
];

interface Directory {
  id: number;
  name: string;
  has_pending_request: boolean;
}

// Each of them asks once; the community admin then opens the queue.
test("join request queue", async ({ page }) => {
  await page.goto("/");
  const directory = await api<Directory[]>(page, "GET", "/c/1/initiatives/directory");
  const lmop = directory.find((initiative) => initiative.name.includes("Lost Mine"));
  if (!lmop) throw new Error("No Lost Mine of Phandelver initiative");

  const waiting = await api<unknown[]>(page, "GET", `/c/1/initiatives/${lmop.id}/join-requests`);
  if (waiting.length < ASKING.length) {
    for (const { email, message } of ASKING) {
      await signInAs(page, email);
      const mine = await api<Directory[]>(page, "GET", "/c/1/initiatives/directory");
      if (!mine.find((initiative) => initiative.id === lmop.id)?.has_pending_request) {
        await api(page, "POST", `/c/1/initiatives/${lmop.id}/join-requests`, { message });
      }
    }
    await signInAs(page, "admin1@example.com");
  }

  await page.goto(`/c/1/i/${lmop.id}/settings/members`);
  await expect(page.getByText("Requests to join")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(2);
  await shootHelp(page, "initiatives/join-request-queue");
});
