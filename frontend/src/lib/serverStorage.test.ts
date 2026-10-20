import { describe, expect, it } from "vitest";

import {
  adoptStoredServerUrl,
  CLOUD_SERVER_URL,
  getStoredServerUrl,
  setStoredServerUrl,
} from "./serverStorage";

describe("adoptStoredServerUrl", () => {
  it("starts a fresh install on Initiative Cloud, and keeps it", () => {
    expect(getStoredServerUrl()).toBeNull();

    expect(adoptStoredServerUrl()).toBe(CLOUD_SERVER_URL);
    expect(getStoredServerUrl()).toBe(CLOUD_SERVER_URL);
  });

  it("keeps the server the app was given", () => {
    setStoredServerUrl("https://home.example.com/api/v1");

    expect(adoptStoredServerUrl()).toBe("https://home.example.com/api/v1");
  });
});
