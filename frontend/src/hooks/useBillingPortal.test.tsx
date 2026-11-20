import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBillingPortal } from "./useBillingPortal";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing, isLoading: false }),
}));

vi.mock("@/api/generated/communities/communities", () => ({
  createCommunityBillingHandoff: vi.fn(async () => ({ handoff_token: "TOK" })),
}));

const environment = vi.hoisted(() => ({
  get: vi.fn(async (): Promise<{ installer?: string }> => ({})),
  storeCountry: vi.fn(async (): Promise<{ country?: string }> => ({})),
}));
vi.mock("@/plugins/appEnvironment", () => ({
  default: environment,
  PLAY_STORE_INSTALLER: "com.android.vending",
}));

const PORTAL = "https://billing.example.com";
const onPlatform = (platform: string) =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

beforeEach(() => {
  state.billing = { url: PORTAL };
  environment.get.mockResolvedValue({});
  environment.storeCountry.mockResolvedValue({});
});

const canSellOn = async () => {
  const { result } = renderHook(() => useBillingPortal());
  // Let a phone's store answer before reading.
  await act(async () => {});
  return result;
};

describe("useBillingPortal canSell", () => {
  it.each([
    ["the web", "web", {}, {}, true],
    ["the desktop app", "electron", {}, {}, true],
    ["iOS on the US storefront", "ios", {}, { country: "USA" }, true],
    ["iOS elsewhere", "ios", {}, { country: "CAN" }, false],
    [
      "a Play install in an allowed country",
      "android",
      { installer: "com.android.vending" },
      { country: "NL" },
      true,
    ],
    [
      "a Play install outside them",
      "android",
      { installer: "com.android.vending" },
      { country: "IN" },
      false,
    ],
    [
      "an Android install from outside Play",
      "android",
      { installer: "dev.imranr.obtainium" },
      {},
      true,
    ],
  ])("on %s, sells: %s", async (_where, platform, installer, country, sells) => {
    onPlatform(platform);
    environment.get.mockResolvedValue(installer);
    environment.storeCountry.mockResolvedValue(country);
    const result = await canSellOn();
    await waitFor(() => expect(result.current.canSell).toBe(sells));
    if (!sells) expect(result.current.reserveTab()).toBeNull();
  });

  it("never sells without a portal", async () => {
    state.billing = null;
    expect((await canSellOn()).current.canSell).toBe(false);
  });
});

describe("useBillingPortal openPortal", () => {
  it("opens the portal in the browser sheet on a phone that may sell", async () => {
    onPlatform("ios");
    environment.storeCountry.mockResolvedValue({ country: "USA" });
    const open = vi.spyOn(window, "open");
    const result = await canSellOn();
    await waitFor(() => expect(result.current.canSell).toBe(true));

    expect(result.current.reserveTab()).toBeNull();
    await act(() => result.current.openPortal(42, "upgrade"));

    expect(Browser.open).toHaveBeenCalledWith({
      url: `${PORTAL}/upgrade?lang=en#handoff=TOK`,
    });
    expect(open).not.toHaveBeenCalled();
  });

  it("opens a tab on the web, not the browser sheet", async () => {
    const tab = { location: { href: "" }, opener: {} } as unknown as Window;
    const open = vi.spyOn(window, "open").mockReturnValue(tab);
    const result = await canSellOn();

    await act(() => result.current.openPortal(42, "manage"));

    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(tab.location.href).toBe(`${PORTAL}/manage?lang=en#handoff=TOK`);
    expect(Browser.open).not.toHaveBeenCalled();
  });

  it("opens nothing on a phone that may not sell", async () => {
    onPlatform("android");
    environment.get.mockResolvedValue({ installer: "com.android.vending" });
    const open = vi.spyOn(window, "open");
    const result = await canSellOn();

    await act(() => result.current.openPortal(42, "upgrade"));

    expect(Browser.open).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });
});
