/**
 * A plug-in connection started in the app.
 *
 * The vendor returns to a browser that holds no Initiative session, so the
 * server hands the flow back to the app instead of finishing it there
 * (`plugin_connection_flows.app_handback`): a one-time code that only the
 * verifier kept here redeems, while the app is signed in as the person who
 * started it. The desktop app opens the vendor in a window of its own and
 * catches the handback there; a phone is handed it as a link (`useDeepLinks`).
 */
import { Capacitor } from "@capacitor/core";

import { type ConnectingApp, PluginConnectionOutcome } from "@/api/generated/initiativeAPI.schemas";
import { finishPluginConnection } from "@/api/generated/plugin-platform/plugin-platform";
import { pkcePair } from "@/lib/nativeSignIn";
import { openExternal } from "@/lib/openExternal";
import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";
import Desktop from "@/plugins/desktop";
import { BLOCKED_URL, sanitizeUrl } from "@/ui/lib/safeUrl";

/** The server's handback address on its own origin (`HANDBACK_PATH` in
 *  `plugin_connection_flows.py`). */
export const HANDBACK_PATH = "/api/v1/plugin-connections/handback";

/** As long as the server's own flow state lives. */
const PENDING_TTL_MS = 10 * 60 * 1000;

interface PendingConnect {
  verifier: string;
  startedAt: number;
}

/** Which app this is, which says how a flow is handed back to it; null in a browser. */
export const connectingApp = (): ConnectingApp | null => {
  const platform = Capacitor.getPlatform();
  if (platform === "electron") return "desktop";
  if (platform === "ios" || platform === "android") return "phone";
  return null;
};

/**
 * What a connect request carries: nothing from a browser; from an app, which
 * app it is and a fresh challenge. The verifier is written before the vendor
 * opens, because a phone often closes the app while the browser is in front.
 */
export const beginConnect = async (): Promise<
  { app: ConnectingApp; code_challenge: string } | undefined
> => {
  const app = connectingApp();
  if (!app) return undefined;
  const { verifier, challenge } = await pkcePair();
  const pending: PendingConnect = { verifier, startedAt: Date.now() };
  await setItem(CREDENTIAL_KEYS.pendingConnect, JSON.stringify(pending));
  return { app, code_challenge: challenge };
};

/** Whether `url` is a connection handed back to the app: the server's own
 *  handback address, or `initiative://plugins/connected` (`APP_HANDBACK_URI`). */
export const isConnectHandback = (url: URL): boolean =>
  (url.protocol === "initiative:" && url.host === "plugins" && url.pathname === "/connected") ||
  ((url.protocol === "https:" || url.protocol === "http:") && url.pathname === HANDBACK_PATH);

/**
 * Open a connection's vendor page. The desktop app opens it in a window of its
 * own and answers the handback that window caught, or null when the person
 * closed it. Elsewhere it opens in the browser, and answers null.
 */
export const openVendorPage = async (url: string): Promise<URL | null> => {
  if (connectingApp() !== "desktop") {
    openExternal(url);
    return null;
  }
  const safe = sanitizeUrl(url);
  if (safe === BLOCKED_URL) return null;
  const { returned } = await Desktop.openVendorPage({ url: safe, returnPath: HANDBACK_PATH });
  return returned ? new URL(returned) : null;
};

const isOutcome = (value: string | null): value is PluginConnectionOutcome =>
  Object.values<string | null>(PluginConnectionOutcome).includes(value);

/** The connection this app began, taken so it is answered once. */
const takePending = (): PendingConnect | null => {
  const raw = getItem(CREDENTIAL_KEYS.pendingConnect);
  void removeItem(CREDENTIAL_KEYS.pendingConnect);
  if (!raw) return null;
  try {
    const pending = JSON.parse(raw) as PendingConnect;
    return Date.now() - pending.startedAt < PENDING_TTL_MS ? pending : null;
  } catch {
    return null;
  }
};

/**
 * Finish a connection handed back to this app, and answer how it ended: null
 * when this app began none. A handback that carries no code is an ending the
 * server reached on its own, such as an install waiting on an owner.
 */
export const finishConnect = async (url: URL): Promise<PluginConnectionOutcome | null> => {
  const pending = takePending();
  if (!pending) return null;
  const code = url.searchParams.get("code");
  if (!code) {
    const outcome = url.searchParams.get("outcome");
    return isOutcome(outcome) ? outcome : PluginConnectionOutcome.expired;
  }
  try {
    const { outcome } = await finishPluginConnection({ code, code_verifier: pending.verifier });
    return outcome;
  } catch {
    return PluginConnectionOutcome.not_recorded;
  }
};
