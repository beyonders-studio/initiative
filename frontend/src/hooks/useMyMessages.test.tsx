/**
 * The two questions this hook file asks about a browser's device.
 *
 * *Is there one* is asked app-wide, so mail is collected wherever you are.
 * *Make sure there is one* is asked by My Messages. They have different
 * answers, and the app asks the first one first — so what matters is that one
 * cannot decide the other, and that registering turns collection on without
 * waiting for a reload.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTestQueryClient } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  // One object, as the store keeps: a snapshot that changes identity on every
  // read is a store that never settles.
  idle: { phase: "idle" },
  ensureDevice: vi.fn(),
  registeredDevice: vi.fn(),
  collect: vi.fn(),
  markRead: vi.fn(),
  reportThreadRead: vi.fn(),
  dmEnabled: vi.fn(() => true),
}));

vi.mock("@/crypto/messaging", () => ({
  ensureDevice: () => mocks.ensureDevice(),
  registeredDevice: () => mocks.registeredDevice(),
  collect: () => mocks.collect(),
  markRead: (...args: unknown[]) => mocks.markRead(...args),
  unreadIn: vi.fn(),
  sendText: vi.fn(),
  messageLog: { get: vi.fn() },
  collectVerification: () => Promise.resolve(),
  subscribeVerification: () => () => undefined,
  verificationView: () => mocks.idle,
}));

vi.mock("@/api/generated/direct-messages/direct-messages", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  markConversationRead: (...args: unknown[]) => mocks.reportThreadRead(...args),
}));

vi.mock("@/hooks/useDirectMessages", () => ({
  useDmSettings: () => ({ data: { send_receipts: true }, isSuccess: true }),
  usePendingConnectionRequests: () => ({ data: [] }),
  // The deployment's switch, which every hook here is behind. On unless a test
  // says otherwise, which is what a deployment offering messaging looks like.
  useDirectMessagesEnabled: () => mocks.dmEnabled(),
}));

import { useCollectMessagesWhereRegistered, useDmDevice, useMarkThreadRead } from "./useMyMessages";

const wrapper = (client = createTestQueryClient()) => {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

beforeEach(() => {
  vi.clearAllMocks();
  // A deployment that offers messaging, which is every test but the one that
  // says otherwise. Set here so that one cannot leak into the rest.
  mocks.dmEnabled.mockReturnValue(true);
  mocks.collect.mockResolvedValue([]);
  mocks.ensureDevice.mockResolvedValue("device-1");
  mocks.markRead.mockResolvedValue(0);
  mocks.reportThreadRead.mockResolvedValue(undefined);
});

describe("this browser's device", () => {
  it("registers one even though the app already asked whether there was one", async () => {
    // A browser that has never opened Messages. Both hooks under one cache, in
    // the order the app mounts them.
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    const { result } = renderHook(
      () => {
        useCollectMessagesWhereRegistered();
        return useDmDevice();
      },
      { wrapper: Wrapper }
    );

    await waitFor(() => expect(result.current.data).toBe("device-1"));
    expect(mocks.ensureDevice).toHaveBeenCalled();
  });

  it("starts collecting as soon as one is registered", async () => {
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    renderHook(
      () => {
        useCollectMessagesWhereRegistered();
        useDmDevice();
      },
      { wrapper: Wrapper }
    );

    await waitFor(() => expect(mocks.collect).toHaveBeenCalled());
  });

  it("collects on a browser that was already set up, without registering", async () => {
    mocks.registeredDevice.mockResolvedValue("device-1");
    const Wrapper = wrapper();

    renderHook(() => useCollectMessagesWhereRegistered(), { wrapper: Wrapper });

    await waitFor(() => expect(mocks.collect).toHaveBeenCalled());
    expect(mocks.ensureDevice).not.toHaveBeenCalled();
  });

  it("collects nothing on a browser that has never been set up", async () => {
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    renderHook(() => useCollectMessagesWhereRegistered(), { wrapper: Wrapper });

    await waitFor(() => expect(mocks.registeredDevice).toHaveBeenCalled());
    expect(mocks.collect).not.toHaveBeenCalled();
  });

  it("neither registers nor collects where the deployment offers no messaging", async () => {
    // A browser that would otherwise do both: already set up, so the only
    // thing holding it back is the switch.
    mocks.dmEnabled.mockReturnValue(false);
    mocks.registeredDevice.mockResolvedValue("device-1");
    const Wrapper = wrapper();

    renderHook(
      () => {
        useCollectMessagesWhereRegistered();
        useDmDevice();
      },
      { wrapper: Wrapper }
    );

    await waitFor(() => expect(mocks.registeredDevice).toHaveBeenCalled());
    expect(mocks.collect).not.toHaveBeenCalled();
    expect(mocks.ensureDevice).not.toHaveBeenCalled();
  });
});

describe("telling the server a thread was read", () => {
  it("reports a look that actually read something", async () => {
    mocks.markRead.mockResolvedValue(2);

    renderHook(() => useMarkThreadRead("conv-1", 2, [7]), { wrapper: wrapper() });

    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalledWith("conv-1"));
    // The roster goes down to the crypto layer, which is what a receipt is
    // encrypted for.
    expect(mocks.markRead).toHaveBeenCalledWith(
      "conv-1",
      expect.objectContaining({ memberIds: [7] })
    );
  });

  it("stays quiet about a thread that was already current", async () => {
    // Nothing was read, so there is no bell line to close and nothing to say.
    mocks.markRead.mockResolvedValue(0);

    renderHook(() => useMarkThreadRead("conv-1", 2, [7]), { wrapper: wrapper() });

    await waitFor(() => expect(mocks.markRead).toHaveBeenCalled());
    expect(mocks.reportThreadRead).not.toHaveBeenCalled();
  });

  it("retries a report that did not land", async () => {
    // The local marker has already advanced, so a second look reads nothing and
    // would otherwise never mention the messages the failed report covered.
    mocks.markRead.mockResolvedValueOnce(2).mockResolvedValue(0);
    mocks.reportThreadRead.mockRejectedValueOnce(new Error("offline"));

    const { rerender } = renderHook(
      ({ count }: { count: number }) => useMarkThreadRead("conv-1", count, [7]),
      { wrapper: wrapper(), initialProps: { count: 2 } }
    );
    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalledTimes(1));

    rerender({ count: 3 });

    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalledTimes(2));
  });

  it("stops retrying once one lands", async () => {
    mocks.markRead.mockResolvedValueOnce(2).mockResolvedValue(0);
    mocks.reportThreadRead.mockRejectedValueOnce(new Error("offline"));

    const { rerender } = renderHook(
      ({ count }: { count: number }) => useMarkThreadRead("conv-1", count, [7]),
      { wrapper: wrapper(), initialProps: { count: 2 } }
    );
    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalledTimes(1));
    rerender({ count: 3 });
    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalledTimes(2));

    rerender({ count: 4 });

    await waitFor(() => expect(mocks.markRead).toHaveBeenCalledTimes(3));
    expect(mocks.reportThreadRead).toHaveBeenCalledTimes(2);
  });

  it("does not surface a failed report to the thread", async () => {
    mocks.markRead.mockResolvedValue(1);
    mocks.reportThreadRead.mockRejectedValue(new Error("offline"));

    expect(() =>
      renderHook(() => useMarkThreadRead("conv-1", 1, [7]), { wrapper: wrapper() })
    ).not.toThrow();

    await waitFor(() => expect(mocks.reportThreadRead).toHaveBeenCalled());
  });
});
