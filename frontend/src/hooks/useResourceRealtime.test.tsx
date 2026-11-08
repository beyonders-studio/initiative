/**
 * A counter group's change signal, on the shared live socket.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { latestSocket, MockWebSocket } from "@/__tests__/helpers/mockWebSocket";
import { setAuthToken } from "@/api/client";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useToolRealtime } from "@/hooks/useResourceRealtime";

const COMMUNITY = 5;
const GROUP = 7;

const invalidate = vi.hoisted(() => vi.fn());

vi.mock("@/api/query-keys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/query-keys")>()),
  invalidate,
}));

vi.mock("@/hooks/useCommunities", () => ({
  useCommunities: () => ({ activeCommunityId: COMMUNITY }),
}));

describe("useToolRealtime", () => {
  beforeEach(() => {
    setAuthToken("test-token");
    MockWebSocket.instances = [];
    invalidate.mockClear();
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
  });

  afterEach(() => {
    setAuthToken(null);
    vi.useRealTimers();
  });

  it("authenticates in its first frame and refetches on a change", () => {
    renderHook(() => useToolRealtime(Tool.counter_group, GROUP));
    const socket = latestSocket();
    socket.open();

    expect(socket.url).toContain(`/${COMMUNITY}/counter-groups/${GROUP}/ws`);
    expect(socket.url).not.toContain("token");
    expect(socket.authPayload()).toEqual({ token: "test-token" });

    socket.receive({ type: "updated", id: GROUP, timestamp: "now" });
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("takes a beat as proof of life and nothing more", () => {
    renderHook(() => useToolRealtime(Tool.counter_group, GROUP));
    const socket = latestSocket();
    socket.open();

    socket.receive({ heartbeat: true });

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("reconnects after a drop and refetches what it may have missed", async () => {
    renderHook(() => useToolRealtime(Tool.counter_group, GROUP));
    const first = latestSocket();
    first.open();
    first.serverClose(1006);

    await vi.advanceTimersByTimeAsync(2000);
    const second = latestSocket();
    expect(second).not.toBe(first);
    second.open();

    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("closes its socket on unmount and does not come back", async () => {
    const { unmount } = renderHook(() => useToolRealtime(Tool.counter_group, GROUP));
    const socket = latestSocket();
    socket.open();

    unmount();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(socket.closed).toBe(true);
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
