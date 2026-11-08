import path from "node:path";
import { fileURLToPath } from "node:url";

import { type BrowserContext, chromium, expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signIn } from "../signedIn";
import { api } from "./request";

/**
 * Messages are read on the device that received them, so each person keeps a
 * browser profile of their own between runs: their device, and the
 * conversation on it, are still there next time and nothing is sent again.
 */
const PROFILES = fileURLToPath(new URL("../../.auth/messages/", import.meta.url));

const ADMIN = "admin1@example.com";
const DM = "user1@example.com";

/** The conversation, in order: who says it, and what. */
const LINES: { from: string; text: string }[] = [
  {
    from: DM,
    text: "Are you still all right to open up on Saturday? Half the table is coming early.",
  },
  { from: ADMIN, text: "Yes, I'll be there from six. Do you want the projector out too?" },
  {
    from: DM,
    text: "Please. And the spare dice, if you can find them. The communal bowl is just a bowl now.",
  },
  { from: ADMIN, text: "Done. I'll leave both by the door on Friday so neither of us forgets." },
];

interface Me {
  id: number;
  username: string;
  discriminator: number;
}

interface Person {
  context: BrowserContext;
  page: Page;
  me: Me;
}

/** `email`'s own browser, signed in, with Messages set up on its device. */
async function openAs(email: string): Promise<Person> {
  const use = test.info().project.use;
  const context = await chromium.launchPersistentContext(path.join(PROFILES, email), {
    baseURL: use.baseURL,
    viewport: use.viewport,
    locale: use.locale,
    timezoneId: use.timezoneId,
    colorScheme: use.colorScheme,
  });
  const page = context.pages()[0] ?? (await context.newPage());
  await laterForUpdates(page);
  await page.goto("/login");
  const signedIn = await page.evaluate(async () => (await fetch("/api/v1/me")).ok);
  if (!signedIn) await signIn(page, email);
  await page.goto("/messages");
  await expect(page.getByRole("button", { name: "Start a conversation" }).first()).toBeVisible({
    timeout: 60_000,
  });
  // The page sets the device up on its first visit.
  await expect
    .poll(async () => (await api<{ devices: unknown[] }>(page, "GET", "/me/dm/devices")).devices, {
      timeout: 60_000,
    })
    .not.toHaveLength(0);
  return { context, page, me: await api<Me>(page, "GET", "/me") };
}

const handle = (me: Me) => `${me.username}${me.discriminator}`;

/** Open `person`'s conversation with `other`, fresh from the server. */
async function openThread(person: Person, other: Me) {
  await person.page.goto(`/messages?with=${handle(other)}`);
  const composer = person.page.getByRole("textbox", { name: "Write a message" });
  await expect(composer).toBeVisible({ timeout: 60_000 });
  return composer;
}

// The community admin and the Dungeon Master connect once, then talk; the
// admin's own device shows the thread.
test("my messages", async () => {
  test.setTimeout(600_000);
  const dm = await openAs(DM);
  const admin = await openAs(ADMIN);
  try {
    const connections = await api<{
      accepted: { user_id: number }[];
      outgoing: { user_id: number }[];
    }>(admin.page, "GET", "/me/connections");
    if (!connections.accepted.some((connection) => connection.user_id === dm.me.id)) {
      if (!connections.outgoing.some((connection) => connection.user_id === dm.me.id)) {
        await api(admin.page, "POST", "/me/connections", {
          username: dm.me.username,
          discriminator: dm.me.discriminator,
        });
      }
      await api(dm.page, "POST", `/me/connections/${admin.me.id}/accept`);
    }

    // Each line not yet on the admin's device is said by whoever says it,
    // and arrives before the next.
    let composer = await openThread(admin, dm.me);
    for (const line of LINES) {
      const said = admin.page.getByText(line.text, { exact: true });
      if (await said.count()) continue;
      const speaker = line.from === ADMIN ? admin : dm;
      const field = speaker === admin ? composer : await openThread(dm, admin.me);
      await field.fill(line.text);
      await field.press("Enter");
      await expect(speaker.page.getByText(line.text, { exact: true })).toBeVisible();
      if (speaker !== admin) composer = await openThread(admin, dm.me);
      await expect(said).toBeVisible({ timeout: 30_000 });
    }

    // The notice behind the shield beside the name, opened by focus so it
    // stays while the picture is taken.
    await admin.page.getByRole("button", { name: /^End-to-end encrypted/ }).focus();
    await expect(admin.page.getByRole("tooltip")).toBeVisible();
    await shootHelp(admin.page, "guides/my-messages");
  } finally {
    await admin.context.close();
    await dm.context.close();
  }
});
