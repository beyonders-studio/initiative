import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient } from "@/__tests__/helpers/render";
import type { NotificationPlace } from "@/api/generated/initiativeAPI.schemas";

import { useUnreadTree } from "./useUnreadTree";

const places = (...rows: Array<Partial<NotificationPlace>>) =>
  server.use(http.get("/api/v1/notifications/unread", () => HttpResponse.json({ places: rows })));

const wrapper = () => {
  const client = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

const tree = async () => {
  const { result } = renderHook(() => useUnreadTree(), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.hasAny).toBe(true));
  return result;
};

describe("useUnreadTree", () => {
  it("lights every level a place names, and nothing else", async () => {
    places({ community_id: 7, initiative_id: 9, tool: "project" });
    const result = await tree();

    expect(result.current.hasCommunity(7)).toBe(true);
    expect(result.current.hasInitiative(7, 9)).toBe(true);
    expect(result.current.hasTool(7, 9, "project")).toBe(true);
    // And nothing it does not name.
    expect(result.current.hasCommunity(8)).toBe(false);
    expect(result.current.hasInitiative(7, 10)).toBe(false);
    expect(result.current.hasTool(7, 9, "file")).toBe(false);
    // The same tool in a different initiative is a different row.
    expect(result.current.hasTool(7, 10, "project")).toBe(false);
  });

  it("lights a community for something belonging to nothing inside it", async () => {
    // A membership notice: it has a community and no initiative, so the
    // community lights and nothing below it does.
    places({ community_id: 7, initiative_id: null, tool: null });
    const result = await tree();

    expect(result.current.hasCommunity(7)).toBe(true);
    expect(result.current.hasInitiative(7, 9)).toBe(false);
  });

  it("counts a place naming nowhere as unread all the same", async () => {
    // A direct message names no community at all, which is why "is anything
    // unread" is the set being non-empty rather than a separate question.
    places({ community_id: null, initiative_id: null, tool: null });
    const result = await tree();

    expect(result.current.hasAny).toBe(true);
    expect(result.current.hasCommunity(7)).toBe(false);
  });

  it("lights nothing at all when there is nothing unread", async () => {
    places();
    const { result } = renderHook(() => useUnreadTree(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.hasAny).toBe(false));
    expect(result.current.hasCommunity(7)).toBe(false);
  });
});
