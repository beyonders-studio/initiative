/**
 * Where the project's own public pages live — the help center, the source,
 * the releases. One place, so the address is not copied into every surface
 * that points somebody at a guide.
 */

import type { DesktopOs } from "./platform";

export const REPO_URL = "https://github.com/beyonders-studio/initiative";
export const RELEASES_URL = `${REPO_URL}/releases`;
export const CHANGELOG_URL = `${REPO_URL}/blob/main/CHANGELOG.md`;

/** The docs site's root: `docs/` as GitHub Pages publishes it on `main`. */
export const DOCS_SITE_URL = "https://beyonders-studio.github.io/initiative/";

/** The English help center. Built from `docs/en/` and published on `main`. */
export const DOCS_URL = `${DOCS_SITE_URL}en/`;

/** A page of the help center by its path under `docs/en/`, with or without a
 *  leading slash; a fragment carries through untouched. */
export const docsUrl = (path = ""): string => `${DOCS_URL}${path.replace(/^\//, "")}`;

/** What a deployment keeps in a visitor's browser, what each category covers,
 *  and who else is involved. Where the cookie chooser sends a reader who wants
 *  more than the four lines it has room for. */
export const COOKIE_DOCS_URL = docsUrl(
  "security/data-and-compliance/#what-is-kept-in-your-browser"
);

/**
 * The Android app attached to one release. CI names the file after the
 * version and attaches it only to a release whose native shell changed, which
 * is exactly the release `MIN_NATIVE_VERSION` names — so the server's own
 * floor is the newest app there is for it.
 */
export const androidApkUrl = (version: string): string =>
  `${RELEASES_URL}/download/v${version}/initiative-${version}.apk`;

const DESKTOP_INSTALLER = {
  windows: "-setup.exe",
  mac: ".dmg",
  linux: ".deb",
} as const;

/** The desktop installer for one computer, attached to the same release as
 *  the APK and named the same way (see `desktop-app.yml`). */
/** The app's Google Play listing. */
export const PLAY_STORE_URL =
  "https://play.google.com/store/apps/details?id=studio.beyonders.initiative";

export const desktopInstallerUrl = (version: string, os: DesktopOs): string =>
  `${RELEASES_URL}/download/v${version}/initiative-${version}${DESKTOP_INSTALLER[os]}`;

/** Adds the repo to Obtainium, which then keeps the Android app updated from
 *  its releases. The same link the install guide carries. */
export const OBTAINIUM_URL =
  "https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2Fbeyonders-studio%2Finitiative";
