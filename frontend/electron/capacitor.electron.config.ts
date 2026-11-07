import { defineConfig } from "@capawesome/capacitor-electron/config";
import { BrowserWindow } from "electron";

// The person connects the app to their own server, so what it may reach is
// whatever that server is, over https or plain http on a home network. The
// rest follows the policy the server gives its web app.
const policy = [
  "default-src 'self'",
  "script-src 'self' 'wasm-unsafe-eval' https://hcaptcha.com https://*.hcaptcha.com https://challenges.cloudflare.com https://www.google.com https://www.gstatic.com",
  "style-src 'self' 'unsafe-inline' https: http:",
  "font-src 'self' data: https: http:",
  "img-src 'self' data: blob: https: http:",
  "media-src 'self' blob: https: http:",
  "connect-src 'self' data: blob: https: http: wss: ws:",
  "frame-src 'self' https: http:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

export default defineConfig({
  // The phone app's origin, which every server already accepts.
  scheme: "capacitor",
  hostname: "studio.beyonders.initiative",
  // Where sign-in in the system browser hands back to the app.
  deepLinks: { scheme: "initiative" },
  csp: { policy },
  window: {
    // Opened by the computer at sign-in, the app waits in the tray.
    showOnLaunch: !process.argv.includes("--hidden"),
    width: 1280,
    height: 860,
    minWidth: 360,
    minHeight: 560,
  },
  splashScreen: {
    width: 320,
    height: 320,
  },
  hooks: {
    // The window keeps its title bar but hides the menu bar under it until
    // Alt is pressed; its shortcuts (zoom, reload, full screen) still work.
    windowFactory: (options) => new BrowserWindow({ ...options, autoHideMenuBar: true }),
  },
});
