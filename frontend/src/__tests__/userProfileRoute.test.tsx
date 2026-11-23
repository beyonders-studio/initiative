/**
 * The way to a person's profile, through the router the app ships.
 *
 * A profile is only useful if it is reachable: the generated route tree has to
 * serve `/u/{userId}` — outside the community tree, because a profile is public
 * and belongs to no community — and load the page from its own chunk. A test
 * that mounts the page component directly proves neither, so this one goes
 * through the tree and preloads the route's own component.
 */
import { createRouter } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Presence } from "@/api/generated/initiativeAPI.schemas";
import { getUrlHandle } from "@/lib/userDisplay";
import { routeTree } from "@/routeTree.gen";

import { buildUserProfile } from "./factories";
import { buildRouterContext, renderPage } from "./helpers/render";

const PROFILE_ROUTE_ID = "/_serverRequired/_authenticated/u/$handle";

const mocks = vi.hoisted(() => ({
  profile: vi.fn(),
  communities: vi.fn(),
  dmPermission: vi.fn(),
  connections: vi.fn(),
  messageRequests: vi.fn(),
  requestMessage: vi.fn(),
}));

// What one person may do about another is the server's answer, not the page's,
// so it is the seam that decides which buttons the profile offers.
vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDmPermission: () => mocks.dmPermission(),
  useConnections: () => mocks.connections(),
  useMessageRequests: () => mocks.messageRequests(),
  useRequestMessage: () => ({ mutate: mocks.requestMessage, isPending: false }),
}));
vi.mock("@/hooks/useUsers", () => ({
  useUserProfile: (handle: string | null) => mocks.profile(handle),
  // The status bubble is a control on your own profile, so it holds a mutation
  // whether or not this one is yours.
  useUpdateCurrentUser: () => ({ mutate: vi.fn(), isPending: false }),
  // What the tray holds is its own read, and the page waits on nothing for it.
  useUserCommunities: (handle: string | null) => mocks.communities(handle),
}));

const community = (overrides: Record<string, unknown> = {}) => ({
  id: 7,
  name: "Kobold Press",
  description: "Where the traps are drawn first.",
  icon_url: null,
  categories: [],
  member_count: 12,
  online_count: 3,
  already_member: true,
  banner: { image_url: null, color: "", text_color: "#fff", text_align: "center", fade: "none" },
  ...overrides,
});

const router = createRouter({ routeTree, context: buildRouterContext() });

const profilePage = async () => {
  const route = router.routesById[PROFILE_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderProfile = async () => {
  const Page = await profilePage();
  return renderPage(Page, {
    initialRoute: "/u/$handle",
    routeParams: { handle: "tinker0042" },
  });
};

const answerWith = (profile: unknown) =>
  mocks.profile.mockReturnValue({ data: profile, isLoading: false });

/** What the server says one person may do about another. */
const permits = (permission: string, may_connect = true) =>
  mocks.dmPermission.mockReturnValue({ data: { permission, may_connect } });

beforeEach(() => {
  vi.clearAllMocks();
  answerWith(buildUserProfile());
  mocks.communities.mockReturnValue({ data: [] });
  permits("denied");
  mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.messageRequests.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
});

describe("a member's profile", () => {
  it("is an address the shipped route tree serves, keyed by handle", () => {
    const matches = router.matchRoutes("/u/tinker0042", {});
    expect(String(matches.at(-1)?.routeId)).toBe(PROFILE_ROUTE_ID);
  });

  it("asks for the handle in the address, not an id", async () => {
    await renderProfile();
    await screen.findByRole("heading");

    expect(mocks.profile).toHaveBeenCalledWith("tinker0042");
  });

  it("leads with the handle, and shows the line they wrote", async () => {
    // The handle is the name in this product — a profile carries no real name
    // at all, so it is the heading rather than a subtitle under one.
    answerWith(
      buildUserProfile({
        username: "tinker",
        discriminator: 42,
        custom_status: { emoji: "🎲", text: "rolling for initiative", clear_at: null },
      })
    );
    await renderProfile();

    expect(await screen.findByRole("heading", { name: /tinker/ })).toBeInTheDocument();
    expect(screen.getByTitle("tinker#0042")).toBeInTheDocument();
    expect(screen.getByText("rolling for initiative")).toBeInTheDocument();
  });

  // The badge is on the picture, and says its state in words rather than in
  // colour alone — so it is found by the name it carries.
  it.each([
    ["says on the picture itself when someone has Initiative open", Presence.online, "Online"],
    ["says which state someone is in, not just that they are here", Presence.busy, "Busy"],
    ["shows someone who stepped away from the keyboard as idle", Presence.idle, "Idle"],
  ])("%s", async (_label, presence, badge) => {
    answerWith(buildUserProfile({ presence }));
    await renderProfile();

    expect(await screen.findByRole("img", { name: badge })).toBeInTheDocument();
  });

  it("badges nobody as offline — an empty corner already says it", async () => {
    answerWith(buildUserProfile({ presence: "offline" }));
    await renderProfile();

    await screen.findByRole("heading");
    expect(screen.queryByRole("img", { name: "Offline" })).not.toBeInTheDocument();
  });

  it("offers the conversation as a button where the channel is already open", async () => {
    // A profile is where somebody lands after clicking a person, so what they
    // came to do is a button on it rather than an item behind a menu.
    const them = buildUserProfile();
    answerWith(them);
    permits("open");
    await renderProfile();

    // Addressed by their handle, which is how My Messages resolves a person.
    const message = await screen.findByRole("link", { name: /message/i });
    expect(message).toHaveAttribute("href", `/messages?with=${getUrlHandle(them)}`);
  });

  it("offers to ask, where there is no channel yet", async () => {
    const them = buildUserProfile();
    answerWith(them);
    permits("may_request");
    await renderProfile();

    await userEvent.click(await screen.findByRole("button", { name: /ask to message/i }));
    expect(mocks.requestMessage.mock.calls[0][0]).toEqual({ data: { user_id: them.id } });
  });

  it("offers to accept a connection they asked for, not a spent button", async () => {
    // Rolled together with the ones you sent, an ask *they* sent reads back as
    // one you sent: a disabled "Request sent" where the answer belongs.
    const them = buildUserProfile();
    answerWith(them);
    mocks.connections.mockReturnValue({
      data: { accepted: [], incoming: [{ user_id: them.id }], outgoing: [] },
    });
    await renderProfile();

    expect(await screen.findByRole("button", { name: /accept connection/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /request sent/i })).toBeNull();
  });

  it("does not offer a connection the server would refuse", async () => {
    // Connecting and messaging are separate rules, so a person who takes no
    // connection requests must not be shown a button that answers with an
    // error. The server says which, and the profile asks.
    permits("open", false);
    await renderProfile();

    expect(await screen.findByRole("link", { name: /message/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^connect$/i })).toBeNull();
  });

  it("offers neither where the server says no", async () => {
    await renderProfile();
    await screen.findByRole("heading");

    expect(screen.queryByRole("link", { name: /message/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ask to message/i })).not.toBeInTheDocument();
  });

  it("shelves the communities they are in where a community shelves its tools", async () => {
    // The directory's own card, whole — so the reader meets a community here
    // the way they would meet it there, and gets the same way in.
    mocks.communities.mockReturnValue({ data: [community()] });
    await renderProfile();

    expect(await screen.findByRole("heading", { name: "Kobold Press" })).toBeInTheDocument();
    expect(screen.getByText("Where the traps are drawn first.")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
  });

  it("offers a stranger the way in rather than a door they cannot open", async () => {
    mocks.communities.mockReturnValue({ data: [community({ already_member: false })] });
    await renderProfile();

    expect(await screen.findByRole("button", { name: "Join" })).toBeInTheDocument();
  });

  it("leaves the rail closed for someone in no communities at all", async () => {
    answerWith(
      buildUserProfile({
        profile_decorations: {
          banner: null,
          frame: null,
          frame_tint: [],
          trophies: ["ttrpg.d20"],
          grad_year: null,
        },
      })
    );
    await renderProfile();

    await screen.findByRole("list", { name: "Trophies" });
    expect(screen.queryByRole("heading", { name: "Communities" })).not.toBeInTheDocument();
  });

  it("wears the decorations it can draw, and ignores the ones it cannot", async () => {
    answerWith(
      buildUserProfile({
        profile_decorations: {
          banner: "core.aurora",
          frame: "spooky.web",
          frame_tint: [],
          trophies: ["ttrpg.d20", "thirdparty.unknown"],
          grad_year: null,
        },
      })
    );
    const { container } = await renderProfile();

    // The rail prints each trophy's name under it, so the picture itself says
    // nothing and is found by its source.
    const rail = await screen.findByRole("list", { name: "Trophies" });
    expect(within(rail).getByText("d20")).toBeInTheDocument();
    expect(rail.querySelector('img[src="/decorations/trophies/ttrpg-d20.svg"]')).not.toBeNull();
    // The frame is worn over the picture and says nothing, so it is hidden
    // from assistive technology and found by its source instead.
    expect(container.querySelector('img[src="/decorations/frames/spooky-web.svg"]')).not.toBeNull();
    // The banner runs the width of the content area now, the way a
    // community's front page does, so it is a picture rather than a fill.
    expect(
      container.querySelector('img[src="/decorations/banners/core-aurora.svg"]')
    ).not.toBeNull();
  });

  it("says so when there is nobody behind the address", async () => {
    answerWith(undefined);
    await renderProfile();

    expect(await screen.findByText("No profile here")).toBeInTheDocument();
  });
});
