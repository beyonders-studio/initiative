import { expect, type Page, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { showTasks } from "./barovia";
import { openCampaign } from "./help/strahd";
import { shootSite } from "./shoot";

// The Download page's hero: the app on a computer and on a phone, framed by
// the page. Sharp enough for a high-density screen at the size it is shown.
test.use({ deviceScaleFactor: 2 });

/** Barovia Arc's board as the Dungeon Master sees it, a member of its
 *  campaign, with the toolbar at the top of the window. */
async function openBoard(page: Page) {
  await openCampaign(page);
  await page.getByRole("main").getByText("Barovia Arc", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Barovia Arc", level: 1 })).toBeVisible();
  await showTasks(page, "Board");
}

async function boardOnTop(page: Page) {
  await page
    .getByRole("heading", { name: "Project tasks" })
    .evaluate((element) => element.scrollIntoView({ block: "start" }));
}

/**
 * Draw the desktop app's own title bar, which the page draws wherever the
 * window reports one (`DesktopTitleBar`), at the app's height
 * (`capacitor.electron.config.ts`). The computer's window buttons are the
 * computer's, so the picture has none.
 */
async function asDesktopApp(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "windowControlsOverlay", {
      value: {
        visible: true,
        getTitlebarAreaRect: () => new DOMRect(0, 0, window.innerWidth, 36),
        addEventListener() {},
        removeEventListener() {},
      },
    });
  });
}

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("download computer", async ({ page }) => {
  await asDesktopApp(page);
  await openBoard(page);
  await boardOnTop(page);
  await shootSite(page, "download-computer");
});

test("download phone", async ({ page }) => {
  await openBoard(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await boardOnTop(page);
  await shootSite(page, "download-phone");
});
