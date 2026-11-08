import { expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../../support";
import { shootHelp } from "../shoot";
import { signInAs } from "../signedIn";
import { api } from "./request";

test.beforeEach(async ({ page }) => laterForUpdates(page));

const NAME = "Barovia festival poster";

interface Listed<T> {
  items: T[];
}

/**
 * Send a small Photoshop file, `version` changing its pixels, as `path`'s
 * `file`. The answer is not checked: the caller reads back what arrived.
 */
async function sendPoster(page: Page, path: string, version: number, fields = {}) {
  await page.evaluate(
    async ({ path, version, fields }) => {
      // A 400 by 600 RGB poster: the header, three empty sections, raw pixels.
      const [width, height] = [400, 600];
      const header = new DataView(new ArrayBuffer(26 + 12 + 2));
      header.setUint32(0, 0x38425053); // "8BPS"
      header.setUint16(4, 1);
      header.setUint16(12, 3);
      header.setUint32(14, height);
      header.setUint32(18, width);
      header.setUint16(22, 8);
      header.setUint16(24, 3);
      const pixels = new Uint8Array(3 * width * height);
      for (let i = 0; i < pixels.length; i++) pixels[i] = (i * version) % 251;
      const form = new FormData();
      for (const [key, value] of Object.entries(fields)) form.append(key, String(value));
      const blob = new Blob([header.buffer, pixels], { type: "image/vnd.adobe.photoshop" });
      form.append("file", blob, `festival-poster-v${version}.psd`);
      const response = await fetch(`/api/v1${path}`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      return response.status;
    },
    { path, version, fields }
  );
}

// The Dungeon Master's poster for Curse of Strahd, uploaded once and given
// three versions.
test("uploaded file", async ({ page }) => {
  await signInAs(page, "user1@example.com");
  const initiatives = await api<{ id: number; name: string }[]>(page, "GET", "/c/1/initiatives/");
  const strahd = initiatives.find((initiative) => initiative.name === "Campaign: Curse of Strahd");
  if (!strahd) throw new Error("No Curse of Strahd initiative");

  const find = async () => {
    const found = await api<Listed<{ id: number; name: string }>>(
      page,
      "GET",
      `/c/1/files/?initiative_id=${strahd.id}&search=${encodeURIComponent(NAME)}`
    );
    return found.items.find((file) => file.name === NAME);
  };
  let poster = await find();
  if (!poster) {
    await sendPoster(page, "/c/1/files/upload", 1, { name: NAME, initiative_id: strahd.id });
    poster = await find();
  }
  if (!poster) throw new Error("The poster did not upload");
  const versions = () => api<unknown[]>(page, "GET", `/c/1/files/${poster.id}/versions`);
  for (let version = (await versions()).length + 1; version <= 3; version++) {
    await sendPoster(page, `/c/1/files/${poster.id}/versions`, version);
  }
  expect(await versions()).toHaveLength(3);

  await page.goto(`/c/1/i/${strahd.id}/files/${poster.id}`);
  await expect(page.getByRole("heading", { name: NAME, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Version history" }).click();
  await expect(page.getByText("Version 1 ·")).toBeVisible();
  await shootHelp(page, "files/uploaded-file");
});
