import { defineConfig } from "@capawesome/capacitor-electron/config";

import { contentPolicy } from "./content-policy";

export default defineConfig({
  // The phone app's origin, which every server already accepts.
  scheme: "capacitor",
  hostname: "studio.beyonders.initiative",
  // Where sign-in in the system browser hands back to the app.
  deepLinks: { scheme: "initiative" },
  csp: { policy: contentPolicy },
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
});
