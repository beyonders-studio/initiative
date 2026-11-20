import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { createTestQueryClient } from "@/__tests__/helpers/render";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));
const read = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/communities/communities")>()),
  readCommunityBillingSummary: read,
}));

import { useCommunityBillingSummary } from "./useCommunityBillingSummary";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
);

// The summary route is the seat's, and there is nothing to ask without a
// billing portal — so the hook asks in exactly that case.
describe("useCommunityBillingSummary", () => {
  beforeEach(() => {
    state.billing = { url: "https://billing.example.com" };
    read.mockReset();
    read.mockResolvedValue({ available: true, payment_failed: false });
  });

  const seatGrant = (configure: boolean) => ({
    ...buildCommunity({
      id: 42,
      role: "superadmin",
      can: communityCan("superadmin", { configure }),
    }),
    accessType: "grant" as const,
    grantSettingsLevel: "superadmin" as const,
  });

  it.each([
    ["the seat of a hosted install", () => buildCommunity({ id: 42, role: "superadmin" }), true],
    ["support holding the seat with write access", () => seatGrant(true), true],
    ["an ordinary admin", () => buildCommunity({ id: 42, role: "admin" }), false],
    ["support whose grant only reads", () => seatGrant(false), false],
  ])("for %s, asks: %s", async (_who, community, asks) => {
    const { result } = renderHook(() => useCommunityBillingSummary(community()), { wrapper });
    if (asks) {
      await waitFor(() => expect(result.current.data?.available).toBe(true));
      expect(read).toHaveBeenCalledWith(42);
    } else {
      expect(read).not.toHaveBeenCalled();
    }
  });

  it("never asks on a self-hosted install", () => {
    state.billing = null;
    const community = buildCommunity({ id: 42, role: "superadmin" });
    renderHook(() => useCommunityBillingSummary(community), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });
});
