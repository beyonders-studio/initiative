import { expect, request, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { openCampaign } from "./strahd";

test.beforeEach(async ({ page }) => laterForUpdates(page));

const PREP = { name: "Prep Nights", color: "#0D9488" };
// Days from today, at 7pm UTC.
const PREP_EVENTS: [string, number][] = [
  ["Paint the Strahd miniature", 3],
  ["Print the Amber Temple maps", 5],
  ["Snack run for the finale", 10],
];

/** A second calendar in the campaign, beside its Default Calendar, so the
 *  month shows two calendars' colors. Made by the Dungeon Master once. */
async function addPrepCalendar() {
  const storageState = { cookies: [], origins: [] };
  const login = await request.newContext({ storageState });
  const token = await login.post("/api/v1/auth/token", {
    form: { username: "user1@example.com", password: "changeme" },
  });
  const { access_token } = await token.json();
  await login.dispose();
  const api = await request.newContext({
    storageState,
    extraHTTPHeaders: { Authorization: `Bearer ${access_token}` },
  });
  try {
    const communities: { id: number; name: string }[] = await (
      await api.get("/api/v1/communities/")
    ).json();
    const community = communities.find((c) => c.name === "Primary Community");
    const base = `/api/v1/c/${community?.id}`;
    const initiatives: { id: number; name: string }[] = await (
      await api.get(`${base}/initiatives/`)
    ).json();
    const campaign = initiatives.find((i) => i.name === "Campaign: Curse of Strahd");
    const { items } = await (
      await api.get(`${base}/calendars/`, { params: { initiative_id: campaign?.id ?? 0 } })
    ).json();
    if (items.some((calendar: { name: string }) => calendar.name === PREP.name)) return;
    const made = await api.post(`${base}/calendars/`, {
      data: { ...PREP, initiative_id: campaign?.id },
    });
    expect(made.ok(), await made.text()).toBe(true);
    const calendar = await made.json();
    for (const [title, days] of PREP_EVENTS) {
      const start = new Date();
      start.setUTCDate(start.getUTCDate() + days);
      start.setUTCHours(19, 0, 0, 0);
      const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);
      const event = await api.post(`${base}/calendar-events/`, {
        data: {
          title,
          calendar_id: calendar.id,
          start_at: start.toISOString(),
          end_at: end.toISOString(),
        },
      });
      expect(event.ok(), await event.text()).toBe(true);
    }
  } finally {
    await api.dispose();
  }
}

test("calendar", async ({ page }) => {
  await addPrepCalendar();
  await openCampaign(page, "Calendar");
  await expect(page.getByRole("button", { name: /All calendars/ })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Paint the Strahd miniature").first()).toBeVisible();
  await shootHelp(page, "tools/calendar");
});
