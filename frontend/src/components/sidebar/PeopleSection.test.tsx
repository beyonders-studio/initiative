/**
 * The sidebar's people roster.
 *
 * The server decides who is listed and in what order; this draws the groups it
 * sends, counts each from the totals rather than the loaded page, and tells a
 * reader whose direct messages are private why they are missing from it.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityRosterMember,
  CommunityRosterResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/sidebar/sidebar";

import { PeopleSection } from "./PeopleSection";

const mocks = vi.hoisted(() => ({
  roster: vi.fn(),
  dmPolicy: "community" as string,
  communities: [] as { community_id: number; enabled: boolean }[],
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 7 }));

vi.mock("@/hooks/useUsers", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useCommunityRoster: () => mocks.roster(),
}));
vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDirectMessagesEnabled: () => true,
  useDmSettings: () => ({
    data: { dm_policy: mocks.dmPolicy, communities: mocks.communities },
  }),
}));

const member = (overrides: Partial<CommunityRosterMember>): CommunityRosterMember => ({
  id: 1,
  username: "someone",
  discriminator: 1234,
  display_name: null,
  avatar_url: null,
  status: "active",
  community_role: "member",
  profile_decorations: null,
  presence: "offline",
  custom_status: { emoji: null, text: null },
  ...overrides,
});

const page = (
  items: CommunityRosterMember[],
  presence_counts: CommunityRosterResponse["presence_counts"],
  has_next = false
) =>
  mocks.roster.mockReturnValue({
    data: {
      pages: [
        {
          items,
          presence_counts,
          total_count: items.length,
          page: 1,
          page_size: 50,
          has_next,
          has_prev: false,
        },
      ],
    },
    isLoading: false,
    hasNextPage: has_next,
  });

const render = () =>
  renderPage(() => (
    <SidebarProvider>
      <PeopleSection />
    </SidebarProvider>
  ));

beforeEach(() => {
  mocks.dmPolicy = "community";
  mocks.communities = [];
});

describe("PeopleSection", () => {
  it("groups people by presence and counts each group from the totals", async () => {
    page(
      [
        member({ id: 1, username: "ada", presence: "online" }),
        member({
          id: 2,
          username: "bram",
          presence: "busy",
          community_role: "admin",
          custom_status: { emoji: "🎧", text: "Heads down" },
        }),
        member({ id: 3, username: "cleo" }),
      ],
      { online: 1, idle: 0, busy: 1, offline: 40 },
      true
    );

    render();

    expect(await screen.findByText("Online — 1")).toBeInTheDocument();
    expect(screen.getByText("Busy — 1")).toBeInTheDocument();
    expect(screen.getByText("Offline — 40")).toBeInTheDocument();
    expect(screen.queryByText(/Idle/)).not.toBeInTheDocument();
    expect(screen.getByText("Heads down")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
  });

  it("tells a reader with private direct messages why they are not listed", async () => {
    mocks.dmPolicy = "private";
    page([member({ id: 1, username: "ada", presence: "online" })], {
      online: 1,
      idle: 0,
      busy: 0,
      offline: 0,
    });

    render();

    expect(await screen.findByText(/people here can.t message you/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change it" })).toHaveAttribute(
      "href",
      "/profile/privacy"
    );
  });

  it("tells a reader who switched this community off why they are not listed", async () => {
    mocks.communities = [
      { community_id: 7, enabled: false },
      { community_id: 8, enabled: true },
    ];
    page([], { online: 0, idle: 0, busy: 0, offline: 0 });

    render();

    expect(await screen.findByText(/people here can.t message you/)).toBeInTheDocument();
  });

  it("does not tell a reader this community can message", async () => {
    mocks.communities = [{ community_id: 8, enabled: false }];
    page([], { online: 0, idle: 0, busy: 0, offline: 0 });

    render();

    await screen.findByText(/Nobody is listed here yet/);
    expect(screen.queryByText(/people here can.t message you/)).not.toBeInTheDocument();
  });

  it("lists somebody once when their presence moved them onto the next page", async () => {
    const ada = member({ id: 1, username: "ada", presence: "online" });
    const counts = { online: 1, idle: 0, busy: 0, offline: 1 };
    const meta = { total_count: 2, page_size: 1, has_prev: false, presence_counts: counts };
    mocks.roster.mockReturnValue({
      data: {
        pages: [
          { ...meta, items: [ada], page: 1, has_next: true },
          { ...meta, items: [{ ...ada, presence: "offline" }], page: 2, has_next: false },
        ],
      },
      isLoading: false,
      hasNextPage: false,
    });

    render();

    expect(await screen.findAllByText(/^ada/)).toHaveLength(1);
  });

  it("says when the list could not be loaded, rather than that it is empty", async () => {
    mocks.roster.mockReturnValue({ data: undefined, isLoading: false, isError: true });

    render();

    expect(await screen.findByText("The people list couldn't be loaded.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText(/Nobody is listed here yet/)).not.toBeInTheDocument();
  });

  it("says so when nobody is listed", async () => {
    page([], { online: 0, idle: 0, busy: 0, offline: 0 });

    render();

    expect(await screen.findByText(/Nobody is listed here yet/)).toBeInTheDocument();
  });
});
