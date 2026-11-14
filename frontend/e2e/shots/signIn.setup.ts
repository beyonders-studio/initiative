import { test as setup } from "@playwright/test";

import { laterForUpdates } from "../support";
import { SIGNED_IN, signIn } from "./signedIn";

// The shots are taken as one of the seeded community admins
// (scripts/seed_dev_data.py), so the pictures show a community with
// something in it. SHOTS_EMAIL / SHOTS_PASSWORD pick somebody else.
setup("sign in", async ({ page }) => {
  await laterForUpdates(page);
  await signIn(page, process.env.SHOTS_EMAIL ?? "admin1@example.com", process.env.SHOTS_PASSWORD);
  await page.context().storageState({ path: SIGNED_IN });
});
