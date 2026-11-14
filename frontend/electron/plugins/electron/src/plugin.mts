export { Desktop } from "./desktop.mjs";
export { DesktopUpdater } from "./desktopUpdater.mjs";
export { Passkeys } from "./passkeys.mjs";
export { SplashScreen } from "./splashScreen.mjs";
export { CapacitorUpdater } from "./updater.mjs";

import { hostname, platform, release } from "node:os";

/** What `@capacitor/device` reports for a computer, as Android and iOS report a phone. */
export class Device {
  static __capacitorElectronPlugin = { name: "Device", methods: ["getInfo"] };

  async getInfo() {
    const name = hostname();
    const system = platform();
    return {
      // A Mac names itself "Lees-MacBook-Pro.local" on the network.
      name: name.endsWith(".local") ? name.slice(0, -".local".length) : name,
      model: system,
      platform: "electron",
      operatingSystem: system === "darwin" ? "mac" : system === "win32" ? "windows" : "unknown",
      osVersion: release(),
      manufacturer: "",
      isVirtual: false,
      webViewVersion: process.versions.chrome,
    };
  }
}
