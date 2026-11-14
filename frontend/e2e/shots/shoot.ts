import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { type BrowserContext, expect, type Locator, type Page, test } from "@playwright/test";

const RELEASE_IMAGES = fileURLToPath(new URL("../../../docs/images/releases/", import.meta.url));
const HELP_IMAGES = fileURLToPath(new URL("../../../docs/en/images/", import.meta.url));

/** Small enough to keep in the repository, sharp enough to read a label. */
const QUALITY = 0.85;

/**
 * Take a release picture of `target` (the whole window if none) and save it as
 * `docs/images/releases/<name>.webp`, or `<name>.dark.webp` when the project
 * running it is the dark one. The docs site publishes them; no install carries
 * them. `name` may hold a folder, such as `0.77/gantt`.
 *
 * In CHANGELOG.md, under the change it shows:
 *
 *     ![What it shows](docs/images/releases/<name>.webp)
 */
export async function shoot(page: Page, name: string, target?: Locator) {
  await capture(page, RELEASE_IMAGES, name, target);
}

/**
 * Take a help center picture the same way, saved as `docs/en/images/<name>.webp`
 * and `<name>.dark.webp`. `name` holds the page's folder, such as
 * `tags/tag-page`.
 *
 * On the page, from a folder under `docs/en/`, the site showing the one that
 * matches the reader's theme:
 *
 *     ![What it shows](../images/<name>.webp#only-light)
 *     ![What it shows](../images/<name>.dark.webp#only-dark)
 */
export async function shootHelp(page: Page, name: string, target?: Locator) {
  await capture(page, HELP_IMAGES, name, target);
}

async function capture(page: Page, folder: string, name: string, target?: Locator) {
  const dark = test.info().project.use.colorScheme === "dark";
  const file = path.join(folder, `${name}${dark ? ".dark" : ""}.webp`);
  // Nothing still arriving: no spinner, no placeholder where a list is still
  // loading, and no picture half drawn.
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 20_000 });
  await page.waitForFunction(() =>
    Array.from(document.images).every((image) => image.complete && image.naturalWidth > 0)
  );
  // No hover left behind by the last click: the pointer goes to the window's
  // bottom-right corner, where nothing sits.
  const size = page.viewportSize();
  if (size) await page.mouse.move(size.width - 1, size.height - 1);
  const options = { animations: "disabled", caret: "hide", scale: "device" } as const;
  const png = await (target ?? page).screenshot(options);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, await toWebp(page.context(), png));
}

/**
 * Playwright saves PNG or JPEG. Chromium also encodes WebP, about a third the
 * size of the PNG for a screenshot, so the conversion happens there, on a
 * blank page of the same browser, rather than through another dependency.
 */
async function toWebp(context: BrowserContext, png: Buffer): Promise<Buffer> {
  const scratch = await context.newPage();
  try {
    const webp = await scratch.evaluate(
      async ({ base64, quality }) => {
        const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
        const blob = await canvas.convertToBlob({ type: "image/webp", quality });
        // A browser that cannot encode WebP hands back a PNG instead.
        if (blob.type !== "image/webp") throw new Error(`Encoded ${blob.type}, not image/webp`);
        let binary = "";
        for (const byte of new Uint8Array(await blob.arrayBuffer())) {
          binary += String.fromCharCode(byte);
        }
        return btoa(binary);
      },
      { base64: png.toString("base64"), quality: QUALITY }
    );
    return Buffer.from(webp, "base64");
  } finally {
    await scratch.close();
  }
}
