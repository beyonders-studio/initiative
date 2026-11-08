import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api, send } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

const TASK = "Find the Sunsword in the Amber Temple";
const MAPS = ["Amber Temple, entrance", "Amber Temple, vaults"];

interface Link {
  relationship_type: string;
  other: { type: string; id: number };
}

// The Sunsword task already waits on the Death House and is mentioned on a
// wiki page; the shot attaches the Amber Temple maps to it once.
test("connections", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  const initiatives = await api<{ id: number; name: string }[]>(page, "GET", "/c/1/initiatives/");
  const strahd = initiatives.find((initiative) => initiative.name === "Campaign: Curse of Strahd");
  if (!strahd) throw new Error("No Curse of Strahd initiative");
  const projects = await api<{ items: { id: number; name: string }[] }>(
    page,
    "GET",
    `/c/1/projects/?initiative_id=${strahd.id}&page_size=100`
  );
  const barovia = projects.items.find((project) => project.name === "Barovia Arc");
  if (!barovia) throw new Error("No Barovia Arc project");
  const tasks = await api<{ items: { id: number; title: string }[] }>(
    page,
    "GET",
    `/c/1/tasks/?project_id=${barovia.id}&page_size=100`
  );
  const task = tasks.items.find((item) => item.title === TASK);
  if (!task) throw new Error(`No task "${TASK}"`);

  const files = await api<{ items: { id: number; name: string }[] }>(
    page,
    "GET",
    `/c/1/files/?initiative_id=${strahd.id}&page_size=100`
  );
  const links = await api<Link[]>(page, "GET", `/c/1/relationships/?entity=task:${task.id}`);
  for (const name of MAPS) {
    const file = files.items.find((item) => item.name === name);
    if (!file) throw new Error(`No file "${name}"`);
    const linked = links.some(
      (link) =>
        link.relationship_type === "attached" &&
        link.other.type === "file" &&
        link.other.id === file.id
    );
    if (!linked) {
      // Read back below rather than trusted: the link can be made while the
      // reply fails.
      await send(page, "POST", "/c/1/relationships/", {
        source: { type: "task", id: task.id },
        relationship_type: "attached",
        target: { type: "file", id: file.id },
      });
    }
  }
  const attached = await api<Link[]>(page, "GET", `/c/1/relationships/?entity=task:${task.id}`);
  expect(attached.filter((link) => link.relationship_type === "attached")).toHaveLength(2);

  // Tall enough for every group at once, the floating buttons below them.
  await page.setViewportSize({ width: 1280, height: 2000 });
  await page.goto(`/c/1/i/${strahd.id}/projects/${barovia.id}/tasks/${task.id}`);
  const heading = page.getByRole("heading", { name: "Connections", level: 2 });
  await expect(heading).toBeVisible();
  const section = heading.locator("xpath=ancestor::div[contains(@class, 'space-y-3')][1]");
  await section.getByRole("button", { name: "How to show these" }).click();
  await page.getByRole("menuitem", { name: "Tiles" }).click();
  await expect(section.getByText("Attached", { exact: true })).toBeVisible();
  await page.locator(":focus").blur();
  await section.evaluate((element) => element.scrollIntoView({ block: "start" }));
  await shootHelp(page, "tools/connections", section);
});
