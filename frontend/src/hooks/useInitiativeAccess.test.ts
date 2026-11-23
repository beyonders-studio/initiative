import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CommunityEntry } from "@/hooks/useCommunities";
import {
  communityMayAuthorTools,
  communityMayWriteContent,
  useGlobalCreateAccess,
} from "@/hooks/useInitiativeAccess";

const mockUseCommunities = vi.fn();

vi.mock("@/hooks/useCommunities", () => ({ useCommunities: () => mockUseCommunities() }));

// Minimal switcher entries for the cheap, entry-point create gates.
const memberCommunity = (over: Partial<CommunityEntry> = {}) =>
  ({ id: 1, role: "member", ...over }) as CommunityEntry;
const grantEntry = (level: "read" | "read_write") =>
  ({ id: 1, role: "member", accessType: "grant", grantAccessLevel: level }) as CommunityEntry;

describe("community create gates (cheap, switcher-only)", () => {
  it.each([
    ["keeps a member for both", memberCommunity(), true, true],
    [
      "drops a frozen community for both",
      memberCommunity({ content_read_only: true }),
      false,
      false,
    ],
    ["lets a read_write grant write but not author", grantEntry("read_write"), false, true],
    ["denies a read grant both", grantEntry("read"), false, false],
  ])("%s", (_case, community, author, write) => {
    expect(communityMayAuthorTools(community)).toBe(author);
    expect(communityMayWriteContent(community)).toBe(write);
  });
});

describe("useGlobalCreateAccess", () => {
  it.each([
    [
      "every community is frozen or read-only-granted",
      [memberCommunity({ id: 1, content_read_only: true }), grantEntry("read")],
      { tool: false, task: false },
    ],
    [
      "a read_write grant writes without authoring",
      [grantEntry("read_write")],
      { tool: false, task: true },
    ],
    ["a member community is present", [memberCommunity()], { tool: true, task: true }],
  ])("when %s", (_case, communities, expected) => {
    mockUseCommunities.mockReturnValue({ communities });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual(expected);
  });
});
