/**
 * The roster a community's member count leads to.
 *
 * The page adds a surface rather than a source: it asks the same people
 * aggregate the new-conversation picker reads, for one community. So what is worth asserting
 * here is that it asks for the right one, pages within it, and offers each
 * person the same way in that they get anywhere else.
 */
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

// The reader, so a row can be told apart from their own.
vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useAuth: () => ({ user: { id: 99 } }),
}));

const mocks = vi.hoisted(() => ({
  members: vi.fn(),
  permission: vi.fn(),
  connections: vi.fn(),
  permissions: vi.fn(),
  ignored: vi.fn(),
  ignore: vi.fn(),
  setOwnName: vi.fn(),
}));

vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  setOwnDisplayName: mocks.setOwnName,
}));

vi.mock("@/hooks/useUsers", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useUserSearch: (options: Record<string, unknown>) => mocks.members(options),
}));
vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDmPermissions: (ids: number[]) => mocks.permissions(ids),
  useDmPermission: () => mocks.permission(),
  useConnections: () => mocks.connections(),
  useIgnoredAccounts: () => mocks.ignored(),
  useIgnoreAccount: () => ({ mutate: mocks.ignore, isPending: false }),
  useMessageRequests: () => ({ data: { accepted: [], incoming: [], outgoing: [] } }),
}));

import { CommunityMembersPage } from "./CommunityMembersPage";

const person = (id: number, username: string, overrides: Record<string, unknown> = {}) => ({
  id,
  username,
  discriminator: 1234,
  display_name: null,
  avatar_url: null,
  status: "active" as const,
  // The server answers "does this one administer the place"; a role override
  // here carries it, the way the real payload does.
  is_community_admin:
    overrides.community_role === "admin" || overrides.community_role === "superadmin",
  ...overrides,
});

const answer = (items: ReturnType<typeof person>[], total = items.length) =>
  mocks.members.mockReturnValue({
    data: { items, total_count: total, page: 1, page_size: 25, has_next: false, has_prev: false },
    isError: false,
  });

const setup = (displayName: string | null = null) =>
  renderPage(() => <CommunityMembersPage />, {
    initialRoute: "/c/$communityId/members",
    routeParams: { communityId: "7" },
    communities: { communities: [buildCommunity({ id: 7, display_name: displayName })] },
  });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.permission.mockReturnValue({ data: { permission: "denied", may_connect: false } });
  mocks.permissions.mockReturnValue({ data: { permissions: {} } });
  mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.ignored.mockReturnValue({ data: { items: [] } });
  answer([]);
});

describe("a community's members page", () => {
  it("asks the community's own roster, not the list of people it may message", async () => {
    answer([person(1, "ada")]);
    setup();

    expect(await screen.findByText("ada")).toBeInTheDocument();
    expect(mocks.members).toHaveBeenCalledWith(
      expect.objectContaining({ communityIdOverride: 7, page: 1, selfFirst: true })
    );
  });

  it("sends a row to that person", async () => {
    answer([person(1, "ada")]);
    setup();

    expect((await screen.findByText("ada")).closest("a")).toHaveAttribute("href", "/u/ada1234");
  });

  it("offers the conversation where the server says there is one", async () => {
    mocks.permissions.mockReturnValue({
      data: { permissions: { "1": { permission: "open", may_connect: true } } },
    });
    answer([person(1, "ada")]);
    setup();

    expect(await screen.findByRole("link", { name: /message/i })).toHaveAttribute(
      "href",
      "/messages?with=ada1234"
    );
  });

  it("counts everyone, not just the page on screen", async () => {
    answer([person(1, "ada")], 42);
    setup();

    expect(await screen.findByText(/42 members/i)).toBeInTheDocument();
  });

  it("lists somebody who takes no messages, with nothing to click", async () => {
    // The point of reading the roster rather than the people aggregate: a
    // members page that hid everyone unreachable would be missing members.
    answer([person(1, "ada")]);
    setup();

    expect(await screen.findByText("ada")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /message/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /ask to message/i })).toBeNull();
    // And no connect button either: the server would refuse that too, and a
    // roster is the one place a refusal is not worth offering.
    expect(screen.queryByRole("button", { name: /^connect$/i })).toBeNull();
  });

  it("answers every keystroke but waits for typing to stop", async () => {
    // The field is local; the address and the roster follow once typing
    // settles. Committing per letter re-runs the route and re-asks the server,
    // which is what made this lag behind the typing.
    answer([person(1, "ada")]);
    const { router } = setup();
    await screen.findByText("ada");
    const field = screen.getByPlaceholderText(/filter members/i);

    await userEvent.type(field, "bo");
    expect(field).toHaveValue("bo");
    expect((router.state.location.search as { q?: string }).q).toBeUndefined();

    // And a new search starts at the beginning: page 3 of the old one says
    // nothing about the new one.
    await waitFor(() => expect((router.state.location.search as { q?: string }).q).toBe("bo"));
    expect((router.state.location.search as { page?: number }).page).toBeUndefined();
  });

  it("says which of them runs the place", async () => {
    // Only the exception is worn: badging every ordinary member "member" would
    // say nothing and cost the width the actions need.
    answer([
      person(1, "ada", { community_role: "admin" }),
      person(2, "bram", { community_role: "member" }),
    ]);
    setup();

    const admin = (await screen.findByText("ada")).closest("a");
    expect(admin).toHaveTextContent("Admin");
    expect((await screen.findByText("bram")).closest("a")).not.toHaveTextContent("Admin");
  });

  it("offers everything else a person can be, behind the overflow", async () => {
    // Ignoring above all: a roster is the likeliest place to want it, and it
    // used to mean knowing somebody's exact handle and opening Settings.
    answer([person(1, "ada")]);
    setup();

    await userEvent.click(await screen.findByRole("button", { name: /actions for ada/i }));

    expect(await screen.findByRole("menuitem", { name: /^ignore$/i })).toBeInTheDocument();
  });

  it("asks about the whole page at once", async () => {
    // Asked per row, this is a request per row -- a hundred on a full page.
    answer([person(1, "ada"), person(2, "bram")]);
    setup();

    await screen.findByText("ada");
    expect(mocks.permissions).toHaveBeenCalledWith([1, 2]);
  });

  it("lets the address change under it without pushing back", async () => {
    // Back, forward, a link somebody sent: the draft catches up to the URL,
    // and the pending debounce must not overwrite it with what was being
    // typed a moment ago.
    answer([person(1, "ada")]);
    const { router } = setup();
    await screen.findByText("ada");

    await userEvent.type(screen.getByPlaceholderText(/filter members/i), "zz");
    await act(() =>
      router.navigate({
        to: "/c/$communityId/members",
        params: { communityId: "7" },
        search: { q: "ada" },
      })
    );

    await waitFor(() => expect(screen.getByPlaceholderText(/filter members/i)).toHaveValue("ada"));
    expect((router.state.location.search as { q?: string }).q).toBe("ada");
  });

  it("offers nothing to do about yourself", async () => {
    // Ignoring and every way in are refused for your own account,
    // so a row for it that offered them would be offering errors.
    answer([person(99, "me"), person(1, "ada")]);
    setup();

    await screen.findByText("me");
    // One row has the controls; the reader's own has none.
    expect(screen.getAllByRole("button", { name: /actions for/i })).toHaveLength(1);
  });

  it("sets your own name here, wherever your row is, starting from the current one", async () => {
    mocks.setOwnName.mockResolvedValue(undefined);
    // The reader is not on this page of the roster at all.
    answer([person(1, "ada")], 60);
    setup("Ana");

    await userEvent.click(await screen.findByRole("button", { name: "Set your display name" }));
    const input = await screen.findByLabelText("Display name");
    expect(input).toHaveValue("Ana");
    await userEvent.clear(input);
    await userEvent.type(input, "  Ana B ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mocks.setOwnName).toHaveBeenCalledWith(7, { display_name: "Ana B" })
    );
  });

  it("clears your name when it is left empty", async () => {
    mocks.setOwnName.mockResolvedValue(undefined);
    answer([person(99, "me")]);
    setup("Ana");

    await userEvent.click(await screen.findByRole("button", { name: "Set your display name" }));
    await userEvent.clear(await screen.findByLabelText("Display name"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.setOwnName).toHaveBeenCalledWith(7, { display_name: null }));
  });

  it("says so when the roster cannot be read", async () => {
    mocks.members.mockReturnValue({ data: undefined, isError: true });
    setup();

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
  });
});
