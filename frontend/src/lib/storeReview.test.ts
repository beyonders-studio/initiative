import { Capacitor } from "@capacitor/core";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PLAY_STORE_URL } from "@/lib/links";
import { getItem, removeItem } from "@/lib/storage";

import {
  askForStoreReview,
  dueForReview,
  noteDayOfUse,
  resetStoreReview,
  useStoreListing,
} from "./storeReview";

const environment = vi.hoisted(() => ({
  get: vi.fn(async (): Promise<{ installer?: string }> => ({})),
  requestReview: vi.fn(async () => {}),
}));

vi.mock("@/plugins/appEnvironment", () => ({ default: environment }));

const PLAY = "com.android.vending";
const DAY = 24 * 60 * 60 * 1000;
const NOW = new Date(2026, 10, 8, 12).getTime();

const onPlatform = (platform: string) =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

const useOnDays = (count: number) => {
  for (let day = count - 1; day >= 0; day--) noteDayOfUse(new Date(NOW - day * DAY));
};

const record = () => JSON.parse(getItem("initiative-store-review") ?? "null");

beforeEach(async () => {
  resetStoreReview();
  await removeItem("initiative-store-review");
  environment.get.mockResolvedValue({});
  environment.requestReview.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("dueForReview", () => {
  it("waits for three days of use, then asks once", () => {
    expect(dueForReview({ days: 2, lastDay: "2026-11-08", asked: false })).toBe(false);
    expect(dueForReview({ days: 3, lastDay: "2026-11-08", asked: false })).toBe(true);
    expect(dueForReview({ days: 3, lastDay: "2026-11-08", asked: true })).toBe(false);
  });
});

describe("noteDayOfUse", () => {
  it("counts a day once, on a phone only", () => {
    onPlatform("web");
    useOnDays(3);
    expect(record()).toBeNull();

    onPlatform("ios");
    noteDayOfUse(new Date(NOW));
    noteDayOfUse(new Date(NOW + 60_000));
    expect(record().days).toBe(1);
  });
});

describe("askForStoreReview", () => {
  it("asks an App Store install on its third day, once", async () => {
    onPlatform("ios");
    useOnDays(3);

    askForStoreReview();
    await waitFor(() => expect(environment.requestReview).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });
    await waitFor(() => expect(record().asked).toBe(true));

    askForStoreReview();
    expect(environment.requestReview).toHaveBeenCalledTimes(1);
  });

  it("never asks before the third day", () => {
    onPlatform("ios");
    useOnDays(2);
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    askForStoreReview();
    expect(record().days).toBe(2);
    expect(environment.requestReview).not.toHaveBeenCalled();
  });

  it("never asks an Android app that Google Play did not install", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "com.android.packageinstaller" });
    useOnDays(3);

    askForStoreReview();
    await waitFor(() => expect(environment.get).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(environment.requestReview).not.toHaveBeenCalled();
  });

  it("records nothing when the app cannot ask", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: PLAY });
    environment.requestReview.mockRejectedValue(new Error("not implemented"));
    useOnDays(3);

    askForStoreReview();
    await waitFor(() => expect(environment.requestReview).toHaveBeenCalled(), { timeout: 3000 });
    expect(record().asked).toBe(false);
  });
});

describe("useStoreListing", () => {
  it("offers Google Play's page to a Play install", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: PLAY });
    const { result } = renderHook(() => useStoreListing());
    await waitFor(() => expect(result.current).toBe(PLAY_STORE_URL));
  });

  it("offers nothing to any other install", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({});
    const { result } = renderHook(() => useStoreListing());
    await waitFor(() => expect(environment.get).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});
