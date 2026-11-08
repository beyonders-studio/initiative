/**
 * A member's API access is a switch on the roster, so a saved answer has to be
 * what the roster pages already loaded read, not only what their refetch will.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildPage, buildUserCommunityMember, buildUserSummary } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import type { UserCommunityMemberListResponse } from "@/api/generated/initiativeAPI.schemas";
import { getListUsersQueryKey } from "@/api/generated/users/users";
import { useSearchMembers, useSetMemberApiAccess } from "@/hooks/useUsers";

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 1 }));

vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  setMemberApiAccess: vi.fn().mockResolvedValue(undefined),
}));

const page = (
  ...items: ReturnType<typeof buildUserCommunityMember>[]
): UserCommunityMemberListResponse => ({
  items,
  total_count: items.length,
  page: 1,
  page_size: 20,
  has_next: false,
  has_prev: false,
});

describe("useSetMemberApiAccess", () => {
  it("writes the saved answer into every roster page already loaded", async () => {
    const client = new QueryClient();
    const member = buildUserCommunityMember({ api_keys_allowed: true });
    const keys = [
      getListUsersQueryKey(1, { page: 1, page_size: 20 }),
      getListUsersQueryKey(1, { search: member.username, page: 1, page_size: 20 }),
    ];
    for (const key of keys) client.setQueryData(key, page(member));

    const { result } = renderHook(() => useSetMemberApiAccess(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    await act(() =>
      result.current.mutateAsync({ communityId: 1, userId: member.id, allowed: false })
    );

    for (const key of keys) {
      expect(
        client.getQueryData<UserCommunityMemberListResponse>(key)?.items[0].api_keys_allowed
      ).toBe(false);
    }
  });
});

describe("useSearchMembers", () => {
  const searchMembers = () =>
    renderHook(() => useSearchMembers(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
      ),
    }).result.current;

  /** Answers `path` with Ada, keeping what it was asked. */
  const answerWithAda = (path: string) => {
    const asked: { params?: URLSearchParams } = {};
    server.use(
      communityHttp.get(path, ({ request }) => {
        asked.params = new URL(request.url).searchParams;
        return HttpResponse.json(
          buildPage([buildUserSummary({ id: 7, display_name: "Ada Lovelace" })])
        );
      })
    );
    return asked;
  };

  it("searches an initiative's members and draws each as a picker does", async () => {
    const asked = answerWithAda("/initiatives/:initiativeId/members/search");

    const found = await searchMembers()({ type: "initiative", initiativeId: 1 }, { search: "ada" });

    expect(found).toEqual([{ id: 7, name: "Ada Lovelace", picture: undefined, initials: "AL" }]);
    expect(asked.params?.get("search")).toBe("ada");
  });

  it("looks people up across the community, with no row to open", async () => {
    const asked = answerWithAda("/users/search");

    const found = await searchMembers()({ type: "community" }, { ids: [7] });

    expect(found.map((member) => member.name)).toEqual(["Ada Lovelace"]);
    expect(asked.params?.getAll("user_id")).toEqual(["7"]);
    expect(asked.params?.has("resource_id")).toBe(false);
  });
});
