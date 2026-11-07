import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";

import { BLOCKED_URL, sanitizeUrl } from "@/ui/lib/safeUrl";

/** The phone apps open another site in the system's browser sheet. */
const opensInBrowserSheet = (): boolean => {
  const platform = Capacitor.getPlatform();
  return platform === "ios" || platform === "android";
};

/**
 * A tab opened now, inside the click, with no opener, to send somewhere once
 * the address is known (a handoff minted after the click). Null on a phone,
 * whose browser sheet opens when the address does.
 */
export function reserveTab(): Window | null {
  if (opensInBrowserSheet()) return null;
  const tab = window.open("about:blank", "_blank");
  if (tab) tab.opener = null;
  return tab;
}

/**
 * Opens another site: in `reserved` when given, otherwise in a new tab with no
 * opener or referrer, or on a phone in the browser sheet. The address goes
 * through {@link sanitizeUrl}; one it blocks opens nothing.
 */
export function openExternal(url: string, reserved?: Window | null): void {
  const safe = sanitizeUrl(url);
  if (safe === BLOCKED_URL) {
    reserved?.close();
    return;
  }
  if (reserved) {
    reserved.location.href = safe;
  } else if (opensInBrowserSheet()) {
    Browser.open({ url: safe }).catch(() => window.open(safe, "_blank", "noopener,noreferrer"));
  } else {
    window.open(safe, "_blank", "noopener,noreferrer");
  }
}
