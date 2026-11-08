import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api, send } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

const NAME = "Amber Temple maps";

interface Member {
  user: { id: number; username: string };
}

// The Dungeon Master's own project in Curse of Strahd, made once and kept to
// two players and the Project Manager role.
test("access settings", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  const initiatives = await api<{ id: number; name: string }[]>(page, "GET", "/c/1/initiatives/");
  const strahd = initiatives.find((initiative) => initiative.name === "Campaign: Curse of Strahd");
  if (!strahd) throw new Error("No Curse of Strahd initiative");

  const find = async () => {
    const found = await api<{ items: { id: number; name: string }[] }>(
      page,
      "GET",
      `/c/1/projects/?initiative_id=${strahd.id}&search=${encodeURIComponent(NAME)}`
    );
    return found.items.find((project) => project.name === NAME);
  };
  let project = await find();
  if (!project) {
    const { items: members } = await api<{ items: Member[] }>(
      page,
      "GET",
      `/c/1/initiatives/${strahd.id}/members`
    );
    const roles = await api<{ id: number; name: string }[]>(
      page,
      "GET",
      `/c/1/initiatives/${strahd.id}/roles`
    );
    const person = (username: string) => {
      const member = members.find((m) => m.user.username === username);
      if (!member) throw new Error(`${username} is not in Curse of Strahd`);
      return member.user.id;
    };
    const managers = roles.find((role) => role.name === "project_manager");
    // The answer is read back rather than trusted: the project can be made
    // while the reply fails.
    await send(page, "POST", "/c/1/projects/", {
      name: NAME,
      icon: "🗺️",
      description: "Floor plans for the Amber Temple, one level at a time.",
      initiative_id: strahd.id,
      grants: [
        { level: "read", user_id: person("thorn-ironforge") },
        { level: "write", user_id: person("elara-moonwhisper") },
        { level: "write", role_id: managers?.id },
      ],
    });
    project = await find();
  }
  if (!project) throw new Error("The project was not made");

  // Tall enough for the whole card, clear of the buttons floating in the corner.
  await page.setViewportSize({ width: 1280, height: 1100 });
  await page.goto(`/c/1/i/${strahd.id}/projects/${project.id}/settings/access`);
  await expect(page.getByText("Restricted", { exact: true })).toBeVisible();
  await expect(page.getByText("elara-moonwhisper")).toBeVisible();
  const card = page
    .getByText("Choose who can view and edit this.")
    .locator(
      "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' bg-card ')][1]"
    );
  await shootHelp(page, "sharing/access-settings", card);
});
