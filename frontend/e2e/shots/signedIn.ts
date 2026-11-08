import { fileURLToPath } from "node:url";

import { expect, type Page } from "@playwright/test";

import { giveBirthdate } from "../support";

/** Where the sign-in step leaves its session for the shots to start from. */
export const SIGNED_IN = fileURLToPath(new URL("../.auth/shots.json", import.meta.url));

/**
 * Sign `page` in as one of the seeded people (scripts/seed/accounts.py), on the
 * seed's password, and land on Home. The seed gives nobody a date of birth, so
 * the first sign-in answers that too.
 */
export async function signIn(page: Page, email: string, password = "changeme") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const home = page.getByRole("heading", { name: "Home", level: 1 });
  const askAge = page.getByText("How old are you?");
  // A busy dev server can take a while to answer the first sign-in.
  await expect(home.or(askAge)).toBeVisible({ timeout: 30_000 });
  if (await askAge.isVisible()) {
    await giveBirthdate(page);
    await page.getByRole("button", { name: "Continue" }).click();
  }
  await expect(home).toBeVisible({ timeout: 30_000 });
}

/**
 * Take a shot as somebody other than the account the run signed in as, for a
 * screen only they see the way the picture needs: a member's own initiatives,
 * say. Drops the run's session first, and what the page kept of it.
 */
export async function signInAs(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.evaluate(() => localStorage.clear());
  await signIn(page, email);
}
