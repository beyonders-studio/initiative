import { session, WebContentsView } from "./app.mjs";
import { mainWindow } from "./desktop.mjs";

/** The session ceremonies run in: apart from the app's own, and in memory only. */
const PARTITION = "passkeys";

/** What each ceremony's page shows: a dimmed app behind the system's own
 *  passkey dialog. */
const PAGE = `<!doctype html><meta charset="utf-8"><title>Initiative</title><style>
html{height:100%;background:rgb(0 0 0/.32)}
body{margin:0;height:100%;display:grid;place-items:center}
div{width:28px;height:28px;border-radius:50%;border:3px solid rgb(255 255 255/.35);border-top-color:#fff;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(1turn)}}
@media (prefers-reduced-motion:reduce){div{animation:none}}
</style><div></div>`;

const PAGE_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
};

type Kind = "create" | "get";

/** The server's options, as the page hands them over, with the server's own
 *  address beside them. */
interface CeremonyOptions {
  origin?: string;
  rpId?: string;
  rp?: { id?: string };
  [key: string]: unknown;
}

/** A prompt that ended without a credential, under the browser's own name for
 *  how it ended; the page reads it with the Android plug-in's codes. */
const refusal = (code: string) => Object.assign(new Error(code), { code });

/** The server's address, when the relying party the options name covers it. */
export const addressFor = (origin: string | undefined, rpId: string | undefined): string | null => {
  if (!origin || !rpId) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(origin);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return null;
  }
  const host = url.hostname;
  return host === rpId || host.endsWith(`.${rpId}`) ? url.origin : null;
};

/** Run the ceremony in the page and hand back the credential's JSON, which
 *  is what the browser path sends the server too. */
const script = (kind: Kind, options: object) => {
  const parse = kind === "create" ? "parseCreationOptionsFromJSON" : "parseRequestOptionsFromJSON";
  return `(async () => {
  try {
    const publicKey = PublicKeyCredential.${parse}(${JSON.stringify(options)});
    const credential = await navigator.credentials.${kind}({ publicKey });
    return { credential: credential.toJSON() };
  } catch (error) {
    return { error: error.name };
  }
})()`;
};

const ceremony = async (kind: Kind, options: CeremonyOptions, rpId: string | undefined) => {
  const { origin, ...serverOptions } = options;
  const address = addressFor(origin, rpId);
  const window = mainWindow();
  if (!address || !window) {
    throw refusal("NotSupportedError");
  }
  const view = new WebContentsView({ webPreferences: { partition: PARTITION, sandbox: true } });
  view.setBackgroundColor("#00000000");
  const fit = () => {
    const [width, height] = window.getContentSize();
    view.setBounds({ x: 0, y: 0, width, height });
  };
  fit();
  window.on("resize", fit);
  window.contentView.addChildView(view);
  try {
    await view.webContents.loadURL(`${address}/`);
    // Chromium refuses a ceremony from a page that does not have focus.
    view.webContents.focus();
    const result: { credential?: unknown; error?: string } =
      await view.webContents.executeJavaScript(script(kind, serverOptions), true);
    if (result.credential) {
      return result.credential;
    }
    throw refusal(result.error ?? "UnknownError");
  } finally {
    window.off("resize", fit);
    window.contentView.removeChildView(view);
    view.webContents.close();
  }
};

/**
 * Passkeys in the desktop app, through the same plug-in the Android app uses,
 * so the page runs every ceremony the same way.
 *
 * A passkey belongs to the server's domain, and the app's pages are not on it.
 * Each ceremony runs instead in a view laid over the app window, in a session
 * of its own that answers every request with a local page. The page loads at
 * the server's address, so the ceremony has the server's origin, and nothing
 * is fetched from the server. Windows then shows its own passkey dialog.
 *
 * Registered on Windows only. A Mac or Linux app has no plug-in and sends the
 * person to the browser, as it did before.
 */
export class Passkeys {
  static get __capacitorElectronPlugin() {
    return process.platform === "win32"
      ? { name: "Passkeys", methods: ["createPasskey", "getPasskey", "isAvailable"] }
      : undefined;
  }

  load() {
    const passkeys = session.fromPartition(PARTITION);
    for (const scheme of ["https", "http"]) {
      passkeys.protocol.handle(scheme, () => new Response(PAGE, { headers: PAGE_HEADERS }));
    }
    // Windows' own dialog picks the account. Where Chromium asks instead, the
    // only account is the answer, and several have no picker here.
    passkeys.on("select-webauthn-account", (_event, { accounts }, callback) => {
      callback(accounts.length === 1 ? accounts[0].credentialId : undefined);
    });
  }

  async isAvailable() {
    return { available: true };
  }

  createPasskey(options: CeremonyOptions) {
    return ceremony("create", options, options.rp?.id);
  }

  getPasskey(options: CeremonyOptions) {
    return ceremony("get", options, options.rpId);
  }
}
