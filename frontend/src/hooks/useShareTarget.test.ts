import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getPendingShare, receivedShare, setPendingShare } from "@/lib/share/pendingShare";

const navigate = vi.fn();
let pathname = "/";
vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate }),
  useLocation: ({ select }: { select: (location: { pathname: string }) => string }) =>
    select({ pathname }),
}));

let native = true;
vi.mock("@/hooks/useServer", () => ({
  useServer: () => ({ isNativePlatform: native }),
}));

type Listener = (event: { title: string; texts: string[]; files: [] }) => void;
let listener: Listener | null = null;
const remove = vi.fn();
vi.mock("@capgo/capacitor-share-target", () => ({
  CapacitorShareTarget: {
    addListener: vi.fn(async (_event: string, callback: Listener) => {
      listener = callback;
      return { remove };
    }),
  },
}));

import { Capacitor } from "@capacitor/core";

import { useResumePendingShare, useShareTarget } from "./useShareTarget";

beforeEach(() => {
  native = true;
  pathname = "/";
  listener = null;
  navigate.mockClear();
});

afterEach(() => setPendingShare(null));

describe("useShareTarget", () => {
  it("holds what was shared and opens the share page", async () => {
    renderHook(() => useShareTarget());
    await vi.waitFor(() => expect(listener).not.toBeNull());

    act(() => listener?.({ title: "", texts: ["https://example.com"], files: [] }));

    expect(getPendingShare()?.texts).toEqual(["https://example.com"]);
    expect(navigate).toHaveBeenCalledWith({ to: "/share" });
  });

  it("ignores a share with nothing in it", async () => {
    renderHook(() => useShareTarget());
    await vi.waitFor(() => expect(listener).not.toBeNull());

    act(() => listener?.({ title: "", texts: [""], files: [] }));

    expect(getPendingShare()).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("stops listening when unmounted", async () => {
    const { unmount } = renderHook(() => useShareTarget());
    await vi.waitFor(() => expect(listener).not.toBeNull());
    unmount();
    await vi.waitFor(() => expect(remove).toHaveBeenCalled());
  });

  it("does not listen in a browser, nor in the desktop app", () => {
    native = false;
    const browser = renderHook(() => useShareTarget());
    expect(listener).toBeNull();
    browser.unmount();

    native = true;
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("electron");
    renderHook(() => useShareTarget());
    expect(listener).toBeNull();
  });
});

describe("useResumePendingShare", () => {
  it.each([
    ["leads back to a share the page has not shown", "/", false, true],
    ["leaves somebody alone once the page has shown it", "/", true, false],
    ["does nothing on the share page itself", "/share", false, false],
  ])("%s", (_case, at, opened, leads) => {
    pathname = at;
    setPendingShare({ ...receivedShare({ texts: ["hello"] })!, opened });
    renderHook(() => useResumePendingShare());
    if (leads) expect(navigate).toHaveBeenCalledWith({ to: "/share" });
    else expect(navigate).not.toHaveBeenCalled();
  });
});
