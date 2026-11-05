/**
 * What every connections mutation does when it fails.
 *
 * These are ordinary conflicts, not bugs — accepting a request that was
 * withdrawn a moment ago, removing a connection somebody else already removed.
 * The lists refresh either way, so with nothing said the row just changes under
 * the reader. There is no global mutation error handler, so this is the only
 * thing standing between a failed action and silence.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  readPermissions: vi.fn(),
}));

vi.mock("@/lib/mascotToast", () => ({
  toast: { error: mocks.error, success: mocks.success },
}));

const failing = { response: { status: 409, data: { detail: "CONTACT_GRANT_CANNOT_REACH" } } };

vi.mock("@/api/generated/direct-messages/direct-messages", () => {
  const make = (options?: { mutation?: { onError?: (e: unknown) => void } }) => ({
    mutate: () => options?.mutation?.onError?.(failing),
    isPending: false,
  });
  return {
    useAcceptConnection: make,
    useAcceptMessageRequest: make,
    useIgnoreAccount: make,
    useRemoveConnection: make,
    useRemoveMessageRequest: make,
    useRequestConnection: make,
    useRequestMessage: make,
    useStopIgnoringAccount: make,
    useUpdateDmSettings: make,
    useListConnections: () => ({ data: undefined }),
    useListIgnoredAccounts: () => ({ data: undefined }),
    useListMessageRequests: () => ({ data: undefined }),
    useReadDmSettings: () => ({ data: undefined }),
    readDmPermissions: (body: { user_ids: number[] }) => mocks.readPermissions(body),
  };
});

import { QueryClientProvider } from "@tanstack/react-query";

import { createTestQueryClient } from "@/__tests__/helpers/render";

import {
  parseHandle,
  useAcceptConnection,
  useDmPermissions,
  useRemoveConnection,
  useRequestConnection,
  useStopIgnoring,
} from "./useDirectMessages";

describe("connections mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ["accepting a connection", useAcceptConnection],
    ["removing a connection", useRemoveConnection],
    ["stopping ignoring", useStopIgnoring],
  ])("says so when %s fails", async (_label, useMutation) => {
    const { result } = renderHook(() => useMutation());

    result.current.mutate({ userId: 1 });

    await waitFor(() => expect(mocks.error).toHaveBeenCalledTimes(1));
  });

  it("leaves the connect-by-handle field to report its own", () => {
    const { result } = renderHook(() => useRequestConnection());

    result.current.mutate({ data: { username: "nobody", discriminator: 1 } });

    // Reported next to the input instead, where the mistake usually is.
    expect(mocks.error).not.toHaveBeenCalled();
  });
});

describe("parseHandle", () => {
  it.each([
    ["ada#1234", { username: "ada", discriminator: 1234 }],
    ["@ada#1234", { username: "ada", discriminator: 1234 }],
    ["  ada#0007  ", { username: "ada", discriminator: 7 }],
  ])("reads %s", (raw, expected) => {
    expect(parseHandle(raw)).toEqual(expected);
  });

  it.each(["ada", "ada#", "#1234", "ada#12345", "ada 1234"])("refuses %s", (raw) => {
    expect(parseHandle(raw)).toBeNull();
  });
});

describe("useDmPermissions", () => {
  const withQueries = () => {
    const client = createTestQueryClient();
    return ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.readPermissions.mockImplementation(({ user_ids }: { user_ids: number[] }) =>
      Promise.resolve({
        permissions: Object.fromEntries(
          user_ids.map((id) => [String(id), { permission: "open", may_connect: true }])
        ),
      })
    );
  });

  it("asks again past the server's limit rather than answering for fewer people", async () => {
    // A control built on a missing answer reads as a refusal on one surface
    // and as consent on another, so nobody handed to this goes unanswered.
    const ids = Array.from({ length: 150 }, (_unused, at) => at + 1);

    const { result } = renderHook(() => useDmPermissions(ids), { wrapper: withQueries() });

    await waitFor(() =>
      expect(Object.keys(result.current.data?.permissions ?? {})).toHaveLength(150)
    );
    expect(mocks.readPermissions).toHaveBeenCalledTimes(2);
    expect(mocks.readPermissions.mock.calls[0][0].user_ids).toHaveLength(100);
    expect(mocks.readPermissions.mock.calls[1][0].user_ids).toHaveLength(50);
    expect(result.current.data?.permissions["150"]).toEqual({
      permission: "open",
      may_connect: true,
    });
  });

  it("publishes nothing until every batch has answered", async () => {
    // Half an answer set reads as a complete one at the call site, and the two
    // surfaces disagree about what a missing entry means.
    let answered = 0;
    mocks.readPermissions.mockImplementation(({ user_ids }: { user_ids: number[] }) => {
      answered += 1;
      // The second batch never lands.
      if (answered > 1) return new Promise(() => {});
      return Promise.resolve({
        permissions: Object.fromEntries(
          user_ids.map((id) => [String(id), { permission: "open", may_connect: true }])
        ),
      });
    });
    const ids = Array.from({ length: 150 }, (_unused, at) => at + 1);

    const { result } = renderHook(() => useDmPermissions(ids), { wrapper: withQueries() });

    await waitFor(() => expect(mocks.readPermissions).toHaveBeenCalledTimes(2));
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPending).toBe(true);
  });

  it("asks nothing about nobody", () => {
    const { result } = renderHook(() => useDmPermissions([]), { wrapper: withQueries() });

    expect(mocks.readPermissions).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();
  });
});
