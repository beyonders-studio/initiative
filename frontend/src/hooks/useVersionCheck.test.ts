import { Capacitor } from "@capacitor/core";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePendingUpdate } from "@/lib/pendingUpdate";

import { useVersionCheck } from "./useVersionCheck";

const getVersion = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/version/version", () => ({ getVersion }));

describe("useVersionCheck", () => {
  beforeEach(() => {
    getVersion.mockResolvedValue({ version: "999.0.0" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers a newer server version on the web, and still does once the prompt is closed", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(false);
    const { result } = renderHook(() => useVersionCheck());
    const pending = renderHook(() => usePendingUpdate());

    await waitFor(() => expect(result.current.updateAvailable.show).toBe(true));
    expect(result.current.updateAvailable.version).toBe("999.0.0");
    act(() => result.current.closeDialog());
    expect(pending.result.current?.action).toBe("reload");
  });

  it("leaves the native app to its bundle update", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    const { result } = renderHook(() => useVersionCheck());

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(getVersion).not.toHaveBeenCalled();
    expect(result.current.updateAvailable.show).toBe(false);
  });
});
