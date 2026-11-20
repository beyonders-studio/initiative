import { Capacitor } from "@capacitor/core";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  resetStoreSelling,
  sellsOnThisDevice,
  sellsWith,
  storeSellingNow,
  toAlpha2,
  useStoreSellingAnswer,
} from "./storeSelling";

const environment = vi.hoisted(() => ({
  get: vi.fn(async (): Promise<{ installer?: string }> => ({})),
  storeCountry: vi.fn(async (): Promise<{ country?: string }> => ({})),
}));

vi.mock("@/plugins/appEnvironment", () => ({
  default: environment,
  PLAY_STORE_INSTALLER: "com.android.vending",
}));

const PLAY = "com.android.vending";

const onPlatform = (platform: string) =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

beforeEach(() => {
  resetStoreSelling();
  environment.get.mockResolvedValue({});
  environment.storeCountry.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe("toAlpha2", () => {
  it.each([
    ["US", "US"],
    ["gb", "GB"],
    ["USA", "US"],
    ["DEU", "DE"],
    ["NOR", "NO"],
    ["JPN", "JP"],
    [undefined, undefined],
    ["", undefined],
    ["BRA", undefined],
    ["U", undefined],
    ["USAA", undefined],
  ])("reads %j as %j", (code, expected) => {
    expect(toAlpha2(code)).toBe(expected);
  });
});

describe("sellsWith", () => {
  it("sells on iOS on the US storefront only, and on Play in Google's allowed countries", () => {
    expect(sellsWith({ platform: "ios", country: "US" })).toBe(true);
    expect(sellsWith({ platform: "ios", country: "GBR" })).toBe(false);
    expect(sellsWith({ platform: "ios", country: "CAN" })).toBe(false);
    for (const country of ["US", "GB", "AU", "DE", "FR", "IE", "IS", "LI", "NO"]) {
      expect(sellsWith({ platform: "android", installer: PLAY, country })).toBe(true);
    }
    for (const country of ["CA", "BR", "IN", "CH", "JP", "KR"]) {
      expect(sellsWith({ platform: "android", installer: PLAY, country })).toBe(false);
    }
    expect(sellsWith({ platform: "android", installer: "com.example", country: "BR" })).toBe(true);
  });
});

describe("sellsOnThisDevice", () => {
  it("sells on the web and the desktop app without asking the store", async () => {
    expect(await sellsOnThisDevice()).toBe(true);
    expect(storeSellingNow()).toBe(true);
    expect(environment.storeCountry).not.toHaveBeenCalled();

    resetStoreSelling();
    onPlatform("electron");
    expect(await sellsOnThisDevice()).toBe(true);
    expect(environment.get).not.toHaveBeenCalled();
  });

  it("asks the App Store storefront on iOS", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "USA" });
    expect(storeSellingNow()).toBeUndefined();
    expect(await sellsOnThisDevice()).toBe(true);
    expect(storeSellingNow()).toBe(true);
  });

  it("does not sell on another storefront, or with none", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "FRA" });
    expect(await sellsOnThisDevice()).toBe(false);

    resetStoreSelling();
    environment.storeCountry.mockResolvedValue({});
    expect(await sellsOnThisDevice()).toBe(false);

    // A native build without the method.
    resetStoreSelling();
    environment.storeCountry.mockRejectedValue(new Error("not implemented"));
    expect(await sellsOnThisDevice()).toBe(false);
  });

  it("does not sell when the store never answers", async () => {
    vi.useFakeTimers();
    onPlatform("ios");
    environment.storeCountry.mockReturnValue(new Promise(() => {}));
    const answer = sellsOnThisDevice();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(await answer).toBe(false);
  });

  it("asks Play for its billing country on a Play install", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: PLAY });
    environment.storeCountry.mockResolvedValue({ country: "DE" });
    expect(await sellsOnThisDevice()).toBe(true);

    resetStoreSelling();
    environment.storeCountry.mockResolvedValue({ country: "BR" });
    expect(await sellsOnThisDevice()).toBe(false);

    resetStoreSelling();
    environment.storeCountry.mockRejectedValue(new Error("not implemented"));
    expect(await sellsOnThisDevice()).toBe(false);
  });

  it("sells on an Android install from outside Play without asking Play", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "dev.imranr.obtainium" });
    expect(await sellsOnThisDevice()).toBe(true);
    expect(environment.storeCountry).not.toHaveBeenCalled();
  });

  it("does not sell on Android when no installer is reported, or it cannot be read", async () => {
    // A Play install whose installer Android does not name must not sell
    // without Play's country.
    onPlatform("android");
    environment.get.mockResolvedValue({});
    expect(await sellsOnThisDevice()).toBe(false);

    resetStoreSelling();
    environment.get.mockRejectedValue(new Error("unavailable"));
    expect(await sellsOnThisDevice()).toBe(false);
  });

  it("asks once per app run", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "USA" });
    await Promise.all([sellsOnThisDevice(), sellsOnThisDevice()]);
    await sellsOnThisDevice();
    expect(environment.storeCountry).toHaveBeenCalledTimes(1);
  });
});

describe("useStoreSellingAnswer", () => {
  it("is true at once on the web", () => {
    const { result } = renderHook(() => useStoreSellingAnswer());
    expect(result.current).toBe(true);
  });

  it("is undefined on a phone until the store answers", async () => {
    onPlatform("ios");
    let answer: (value: { country?: string }) => void = () => {};
    environment.storeCountry.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const { result } = renderHook(() => useStoreSellingAnswer());
    expect(result.current).toBeUndefined();
    await act(async () => answer({ country: "USA" }));
    await waitFor(() => expect(result.current).toBe(true));
  });
});
