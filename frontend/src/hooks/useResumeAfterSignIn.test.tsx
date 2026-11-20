/**
 * Where a finished sign-in lands.
 *
 * The login page and the SSO callback both finish a sign-in, and both read the
 * interrupted page back from `next` through this one hook: only a path in this
 * app is kept, and a path inside a community only when the account now signed
 * in can reach that community.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import type { CommunityEntry } from "@/hooks/useCommunities";

import { useResumeAfterSignIn } from "./useResumeAfterSignIn";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  refreshCommunities: vi.fn(),
  user: null as unknown,
}));

vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useRouter: () => ({ navigate: mocks.navigate }),
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ user: mocks.user }),
}));

vi.mock("@/hooks/useCommunities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunities")>()),
  useCommunities: () => ({ refreshCommunities: mocks.refreshCommunities }),
}));

const communityEntry = (id: number): CommunityEntry =>
  ({ ...buildCommunity({ id }), accessType: "member" }) as CommunityEntry;

/** Where the hook sent them. */
const landedOn = (): unknown => mocks.navigate.mock.calls.at(-1)?.[0];

beforeEach(() => {
  mocks.navigate.mockReset();
  mocks.refreshCommunities.mockReset().mockResolvedValue([communityEntry(5)]);
  mocks.user = buildUser();
});

describe("resuming after sign-in", () => {
  it("returns to a page in this app outside any community without asking the list", async () => {
    const { result } = renderHook(() => useResumeAfterSignIn());

    await act(() => result.current("/profile/security?tab=passkeys"));

    expect(landedOn()).toEqual({ to: "/profile/security?tab=passkeys", replace: true });
    expect(mocks.refreshCommunities).not.toHaveBeenCalled();
  });

  it("starts at home with no page to return to, or anything that is not a path in this app", async () => {
    const { result } = renderHook(() => useResumeAfterSignIn());

    for (const next of [
      undefined,
      "//example.test/x",
      "/\\example.test/x",
      "https://example.test/x",
    ]) {
      await act(() => result.current(next));
      expect(landedOn()).toEqual({ to: "/", replace: true });
    }
  });

  it("returns to a community page when the account can reach that community", async () => {
    const { result } = renderHook(() => useResumeAfterSignIn());

    await act(() => result.current("/c/5/projects/47"));

    expect(mocks.refreshCommunities).toHaveBeenCalledTimes(1);
    expect(landedOn()).toEqual({ to: "/c/5/projects/47", replace: true });
  });

  it("starts at home when the community is not one the account can reach", async () => {
    const { result } = renderHook(() => useResumeAfterSignIn());

    await act(() => result.current("/c/9/projects/47"));

    expect(landedOn()).toEqual({ to: "/", replace: true });

    // Except its billing forwarder, which the server answers for itself.
    await act(() => result.current("/c/9/billing?page=upgrade"));

    expect(landedOn()).toEqual({ to: "/c/9/billing?page=upgrade", replace: true });
  });

  it("waits for the account to arrive before asking which communities it has", async () => {
    mocks.user = null;
    const { result, rerender } = renderHook(() => useResumeAfterSignIn());

    let finished = false;
    const resuming = result.current("/c/5").then(() => {
      finished = true;
    });
    await Promise.resolve();
    expect(mocks.refreshCommunities).not.toHaveBeenCalled();
    expect(finished).toBe(false);

    mocks.user = buildUser();
    rerender();
    await act(() => resuming);

    await waitFor(() => expect(landedOn()).toEqual({ to: "/c/5", replace: true }));
    expect(mocks.refreshCommunities).toHaveBeenCalledTimes(1);
  });
});
