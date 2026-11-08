import { afterEach, describe, expect, it, vi } from "vitest";

import { CLOUD_SERVER_URL } from "./cloud";
import { adoptStoredServerUrl, getStoredServerUrl, setStoredServerUrl } from "./serverStorage";

const cloud = vi.hoisted(() => ({ open: false }));

vi.mock("./cloud", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./cloud")>()),
  get CLOUD_OPEN() {
    return cloud.open;
  },
}));

describe("adoptStoredServerUrl", () => {
  afterEach(() => {
    cloud.open = false;
  });

  it("leaves a fresh install with no server until Initiative Cloud opens", () => {
    expect(adoptStoredServerUrl()).toBeNull();
    expect(getStoredServerUrl()).toBeNull();
  });

  it("starts a fresh install on Initiative Cloud once it is open, and keeps it", () => {
    cloud.open = true;

    expect(adoptStoredServerUrl()).toBe(CLOUD_SERVER_URL);
    expect(getStoredServerUrl()).toBe(CLOUD_SERVER_URL);
  });

  it("keeps the server the app was given", () => {
    setStoredServerUrl("https://home.example.com/api/v1");

    expect(adoptStoredServerUrl()).toBe("https://home.example.com/api/v1");
  });
});
