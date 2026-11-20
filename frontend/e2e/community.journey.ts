import { randomBytes } from "node:crypto";

import { type Browser, expect, type Page, test } from "@playwright/test";

import { giveBirthdate, laterForUpdates } from "./support";

// A fresh install, as somebody meets it: the first person to register owns it
// and gets a community, builds an initiative, a project and a task, and finds
// them again after signing back in. Then they invite somebody, who joins and
// sees only what they have been let into.

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => laterForUpdates(page));

// Strong and fresh each run: registration refuses a password a breach list
// already holds.
const password = () => `${randomBytes(12).toString("base64url")}-9a`;

const owner = {
  username: "olive",
  email: "olive@example.com",
  password: password(),
};
const member = {
  username: "maya",
  email: "maya@example.com",
  password: password(),
};
const community = "Olive's Community";

/** Where the first journey left things, for the second to look for. */
const made = { communityPath: "", initiativePath: "", projectId: "" };

const next = (page: Page) => page.getByRole("button", { name: "Continue" }).click();

/** The start flow from "About you" on: a handle and a birthday, then the account. */
async function register(page: Page, person: typeof owner, between?: () => Promise<void>) {
  await page.getByLabel("Username").fill(person.username);
  await giveBirthdate(page);
  // Continue opens once the handle has been checked.
  await next(page);
  await between?.();
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(person.password);
  await page.getByLabel("Confirm password").fill(person.password);
  await page.getByRole("button", { name: "Sign up" }).click();
}

async function signIn(page: Page, person: typeof owner) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(person.email);
  await page.getByLabel("Password").fill(person.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Home", level: 1 })).toBeVisible();
}

async function newInitiative(page: Page, name: string, joining?: string) {
  const dialog = page.getByRole("dialog", { name: "New initiative" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: /^Next: Tools/ }).click();
  await dialog.getByRole("button", { name: /^Next: Membership/ }).click();
  if (joining) await dialog.getByRole("radio", { name: joining }).click();
  await dialog.getByRole("button", { name: /^Next: Permissions/ }).click();
  await dialog.getByRole("button", { name: "Create initiative" }).click();
  await expect(dialog).toBeHidden();
}

async function freshPage(browser: Browser) {
  const page = await (await browser.newContext()).newPage();
  await laterForUpdates(page);
  return page;
}

async function signedInAs(browser: Browser, person: typeof owner) {
  const page = await freshPage(browser);
  await signIn(page, person);
  return page;
}

test("the first owner builds a community and finds it again", async ({ page }) => {
  // Signing up for a group makes the community, and its first initiative, with
  // the account.
  await page.goto("/register");
  await page.getByRole("radio", { name: /^For a group/ }).click();
  await next(page);
  await register(page, owner, async () => {
    await page.getByLabel("Community name").fill(community);
    await page.getByLabel("First initiative").fill("Spring Fete");
    await next(page);
  });
  await page.getByRole("button", { name: `Go to ${community}` }).click();
  await expect(page.getByRole("heading", { name: community, level: 1 })).toBeVisible();
  made.communityPath = new URL(page.url()).pathname;

  await page.getByRole("main").getByRole("link", { name: "Spring Fete" }).click();
  await expect(page.getByRole("heading", { name: "Spring Fete", level: 1 })).toBeVisible();
  made.initiativePath = new URL(page.url()).pathname;

  await page.getByRole("main").getByRole("button", { name: "Add Project" }).click();
  const project = page.getByRole("dialog", { name: "Create project" });
  await project.getByLabel("Name").fill("Cake stall");
  await project.getByRole("button", { name: "Create project" }).click();
  // Made, and opened.
  await expect(page.getByRole("heading", { name: "Cake stall", level: 1 })).toBeVisible();
  made.projectId = page.url().split("/projects/")[1];

  await page.getByRole("main").getByRole("button", { name: "Add task" }).click();
  const task = page.getByRole("dialog", { name: "Create task" });
  await task.getByRole("textbox", { name: "Task", exact: true }).fill("Order the flour");
  await task.getByRole("button", { name: "Create task" }).click();
  await expect(page.getByRole("main").getByText("Order the flour")).toBeVisible();

  // Named by the avatar's initials, then the handle.
  await page.getByRole("button", { name: new RegExp(`${owner.username}#\\d{4}$`) }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/(login|welcome)/);

  // Back in, the way they would come back: the community lists its
  // initiatives, and the initiative its projects.
  await signIn(page, owner);
  await page.getByRole("button", { name: `Switch to ${community}` }).click();
  await page.getByRole("main").getByRole("link", { name: "Spring Fete" }).click();
  await page
    .getByRole("main")
    .getByRole("link", { name: /^Cake stall/ })
    .click();
  await expect(page.getByRole("main").getByText("Order the flour")).toBeVisible();
});

test("an invited member sees only what they are let into", async ({ browser }) => {
  const ownerPage = await signedInAs(browser, owner);
  // An initiative anyone in the community may join, beside the invite-only one.
  await ownerPage.goto(made.communityPath);
  await ownerPage.getByRole("button", { name: "New initiative" }).click();
  await newInitiative(ownerPage, "Open day", "Anyone can join");

  await ownerPage.goto(`${made.communityPath}/settings/users`);
  await ownerPage.getByRole("button", { name: "Generate invite" }).click();
  // A link is shown once, as it is made; the list keeps none to show again.
  const link = ownerPage.getByText(/\/invite\//);
  await expect(link).toHaveCount(1);
  const invite = await link.textContent();
  expect(invite).toBeTruthy();

  const page = await freshPage(browser);
  await page.goto(new URL(invite ?? "").pathname);
  await page.getByRole("link", { name: "Register using this invite" }).click();
  await expect(page.getByText(`You're joining ${community}.`)).toBeVisible();
  await next(page);
  await register(page, member);
  await expect(page).not.toHaveURL(/\/start/);

  await page.goto(made.communityPath);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: community, level: 1 })).toBeVisible();
  // What they may join is offered; what they are not in is not there at all.
  await expect(main.getByText("Open day")).toBeVisible();
  await expect(main.getByRole("button", { name: "Join" })).toBeVisible();
  await expect(page.getByText("Spring Fete")).toHaveCount(0);

  // Its address shows them nothing of it, and the API does not have it.
  await page.goto(`${made.initiativePath}/projects/${made.projectId}`);
  await expect(page.getByRole("heading", { name: "Cake stall" })).toHaveCount(0);
  const communityId = made.communityPath.split("/")[2];
  const response = await page.request.get(`/api/v1/c/${communityId}/projects/${made.projectId}`);
  expect(response.status()).toBe(404);
});
