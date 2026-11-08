import { type APIRequestContext, expect, type Page, request, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";

test.beforeEach(async ({ page }) => laterForUpdates(page));

type Target = { task: string } | { post: string } | { wikiPage: string };

// What the Dungeon Master's players said this week in Curse of Strahd. The
// seed writes no activity, and the feed shows only other people's changes.
const COMMENTS: { email: string; target: Target; content: string }[] = [
  {
    email: "user2@example.com",
    target: { task: "Destroy the shambling mound" },
    content: "Bringing fire this time. Lots of fire.",
  },
  {
    email: "user3@example.com",
    target: { post: "Which night suits everyone for the finale?" },
    content: "Friday works for me. Saturday at a push.",
  },
  {
    email: "user4@example.com",
    target: { wikiPage: "Barovia" },
    content: "The fog turned us back twice on the road out. Worth a line under Getting out.",
  },
  {
    email: "user5@example.com",
    target: { task: "Retrieve the Tome of Strahd" },
    content: "I can carry it, if the curse lets me.",
  },
];

/** Primary Community's id, as the signed-in person's list has it. */
async function primaryCommunity(page: Page) {
  const communities: { id: number; name: string }[] = await (
    await page.request.get("/api/v1/communities/")
  ).json();
  const primary = communities.find((community) => community.name === "Primary Community");
  if (!primary) throw new Error("Primary Community is not in the seed");
  return primary.id;
}

/** The comment's target as the field the API takes, looked up by name. */
async function resolve(api: APIRequestContext, base: string, target: Target) {
  if ("task" in target) {
    const conditions = JSON.stringify([{ field: "title", op: "eq", value: target.task }]);
    const { items } = await (await api.get(`${base}/tasks/`, { params: { conditions } })).json();
    return { task_id: items[0].id as number };
  }
  if ("post" in target) {
    const { items } = await (await api.get(`${base}/posts/`)).json();
    return { post_id: items.find((post: { name: string }) => post.name === target.post).id };
  }
  const { items: wikis } = await (await api.get(`${base}/wikis/`)).json();
  for (const wiki of wikis) {
    const { items } = await (await api.get(`${base}/wikis/${wiki.id}/pages`)).json();
    const page = items.find((item: { title: string }) => item.title === target.wikiPage);
    if (page) return { wiki_page_id: page.id as number };
  }
  throw new Error(`No wiki page named ${target.wikiPage}`);
}

/** Leave each comment as its author, unless they already have. Each author
 *  signs in on a request context of their own, without the run's session. */
async function leaveComments(communityId: number) {
  const base = `/api/v1/c/${communityId}`;
  const storageState = { cookies: [], origins: [] };
  for (const { email, target, content } of COMMENTS) {
    const login = await request.newContext({ storageState });
    const token = await login.post("/api/v1/auth/token", {
      form: { username: email, password: "changeme" },
    });
    const { access_token } = await token.json();
    await login.dispose();
    const api = await request.newContext({
      storageState,
      extraHTTPHeaders: { Authorization: `Bearer ${access_token}` },
    });
    try {
      const on = await resolve(api, base, target);
      const [field, id] = Object.entries(on)[0];
      const { comments } = await (
        await api.get(`${base}/comments/`, { params: { [field]: id, limit: 100 } })
      ).json();
      if (comments.some((comment: { content: string }) => comment.content === content)) continue;
      const made = await api.post(`${base}/comments/`, { data: { ...on, content } });
      expect(made.ok(), await made.text()).toBe(true);
    } finally {
      await api.dispose();
    }
  }
}

// A member who is in the community's initiatives, so the front page has
// their players' comments and what's coming up on it.
test("community front page", async ({ page }) => {
  await leaveComments(await primaryCommunity(page));
  await signInAs(page, "user1@example.com");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await expect(page.getByRole("heading", { name: "Primary Community", level: 1 })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(/^thorn-ironforge#\d+ commented$/)).toBeVisible();
  // Wide enough for the initiative cards' names, and tall enough to reach from
  // the banner to the first row of Coming up, with the floating buttons just
  // under it.
  await page.setViewportSize({ width: 1440, height: 800 });
  const firstComingUp = page
    .getByRole("listitem")
    .filter({ hasText: /^.*(Task due|Task starts|Event|Project starts|Project ends|Poll closes)/ })
    .first();
  await expect(firstComingUp).toBeAttached({ timeout: 30_000 });
  const box = await firstComingUp.boundingBox();
  if (!box) throw new Error("Coming up has nothing in it");
  await page.setViewportSize({ width: 1440, height: Math.ceil(box.y + box.height) + 96 });
  await shootHelp(page, "communities/community-front-page", page.getByRole("main"));
});
