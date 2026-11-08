/** Which download the visitor most likely wants, read off the browser. */
export type VisitorPlatform = "android" | "ios" | "desktop";

export function detectPlatform(
  nav: Pick<Navigator, "userAgent" | "maxTouchPoints"> = navigator
): VisitorPlatform {
  const ua = nav.userAgent;
  if (/android/i.test(ua)) return "android";
  if (/iphone|ipad|ipod/i.test(ua)) return "ios";
  // iPadOS Safari presents itself as a Mac; the touch points give it away.
  if (/macintosh/i.test(ua) && nav.maxTouchPoints > 1) return "ios";
  return "desktop";
}

/** Which computer the visitor is on, for naming the download button. Null
 *  when the browser doesn't say. */
export type DesktopOs = "windows" | "mac" | "linux";

export function detectDesktopOs(nav: Pick<Navigator, "userAgent"> = navigator): DesktopOs | null {
  const ua = nav.userAgent;
  if (/windows/i.test(ua)) return "windows";
  if (/macintosh|mac os x/i.test(ua)) return "mac";
  if (/linux|cros/i.test(ua)) return "linux";
  return null;
}
