import { Capacitor } from "@capacitor/core";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  resetStoreSelling,
  SELLING_COUNTRIES,
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
  it("passes two letters through and maps known alpha-3 codes", () => {
    expect(toAlpha2("US")).toBe("US");
    expect(toAlpha2("gb")).toBe("GB");
    expect(toAlpha2("USA")).toBe("US");
    expect(toAlpha2("DEU")).toBe("DE");
    expect(toAlpha2("NOR")).toBe("NO");
    expect(toAlpha2("JPN")).toBe("JP");
  });

  it("treats anything else as unknown", () => {
    expect(toAlpha2(undefined)).toBeUndefined();
    expect(toAlpha2("")).toBeUndefined();
    expect(toAlpha2("BRA")).toBeUndefined();
    expect(toAlpha2("U")).toBeUndefined();
    expect(toAlpha2("USAA")).toBeUndefined();
  });

  it("maps every allowed country's alpha-3 code", () => {
    const mapped = ["USA", "GBR", "AUS", "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK"]
      .concat(["EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU"])
      .concat(["LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"])
      .concat(["ISL", "LIE", "NOR"])
      .map(toAlpha2);
    expect(new Set(mapped)).toEqual(new Set(SELLING_COUNTRIES.android));
  });
});

describe("sellsWith", () => {
  it("always sells on the web and the desktop app", () => {
    expect(sellsWith({ platform: "web" })).toBe(true);
    expect(sellsWith({ platform: "electron" })).toBe(true);
  });

  it("sells on iOS on the US storefront only", () => {
    expect(sellsWith({ platform: "ios", country: "USA" })).toBe(true);
    expect(sellsWith({ platform: "ios", country: "US" })).toBe(true);
    expect(sellsWith({ platform: "ios", country: "GBR" })).toBe(false);
    expect(sellsWith({ platform: "ios", country: "CAN" })).toBe(false);
    expect(sellsWith({ platform: "ios" })).toBe(false);
  });

  it("sells on a Play install in Google's allowed countries", () => {
    for (const country of ["US", "GB", "AU", "DE", "FR", "IE", "IS", "LI", "NO"]) {
      expect(sellsWith({ platform: "android", installer: PLAY, country })).toBe(true);
    }
    for (const country of ["CA", "BR", "IN", "CH", "JP", "KR"]) {
      expect(sellsWith({ platform: "android", installer: PLAY, country })).toBe(false);
    }
    expect(sellsWith({ platform: "android", installer: PLAY })).toBe(false);
  });

  it("sells on an Android install from anywhere but Play, wherever it is", () => {
    expect(sellsWith({ platform: "android" })).toBe(true);
    expect(sellsWith({ platform: "android", installer: "org.fdroid.fdroid" })).toBe(true);
    expect(sellsWith({ platform: "android", installer: "com.example", country: "BR" })).toBe(true);
  });
});

describe("sellsOnThisDevice", () => {
  it("sells on the web without asking the store", async () => {
    expect(await sellsOnThisDevice()).toBe(true);
    expect(storeSellingNow()).toBe(true);
    expect(environment.storeCountry).not.toHaveBeenCalled();
  });

  it("sells on the desktop app without asking the store", async () => {
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
  });

  it("does not sell on a native build without the method", async () => {
    onPlatform("ios");
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

  it("does not sell on Android when no installer is reported", async () => {
    // A Play install whose installer Android does not name must not sell
    // without Play's country.
    onPlatform("android");
    environment.get.mockResolvedValue({});
    expect(await sellsOnThisDevice()).toBe(false);
  });

  it("does not sell on Android when the installer cannot be read", async () => {
    onPlatform("android");
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
