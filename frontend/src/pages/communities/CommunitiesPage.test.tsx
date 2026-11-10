/**
 * Browsing the community directory.
 *
 * The load-bearing details are that the filter rail actually narrows the
 * request (rather than filtering client-side, which would only ever narrow the
 * current page), that a community the caller is already in offers a way in
 * rather than a second way to join, and that one taking requests is asked
 * rather than joined.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildBanner, buildPage, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { DirectoryCommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { saveNear } from "@/lib/directoryNear";

import { CommunitiesPage } from "./CommunitiesPage";

const directoryFor = vi.fn();
const join = vi.fn();
const ask = vi.fn();
const withdraw = vi.fn();
const fetchNextPage = vi.fn();

vi.mock("@/hooks/useCommunityDirectory", () => ({
  useDirectoryCommunities: (params: unknown, options?: unknown) => directoryFor(params, options),
  useJoinDirectoryCommunity: () => ({ mutateAsync: join, isPending: false }),
  useAskToJoinDirectoryCommunity: () => ({ mutateAsync: ask, isPending: false }),
  useWithdrawDirectoryJoinRequest: () => ({ mutateAsync: withdraw, isPending: false }),
}));

// Whether this deployment has a directory at all is the platform owner's
// setting; everything below is about one that does, bar the test that says so.
const config = vi.hoisted(() => ({ communityDirectory: true, ageGate: true }));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    communityDirectoryEnabled: config.communityDirectory,
    communityAgeGateEnabled: config.ageGate,
    isLoading: false,
  }),
}));

const community = (overrides: Partial<DirectoryCommunityRead> = {}): DirectoryCommunityRead => ({
  id: 1,
  name: "Riverside Players",
  description: "Community theatre.",
  icon_url: null,
  location: null,
  banner: buildBanner(),
  categories: ["art"],
  member_count: 12,
  online_count: 0,
  already_member: false,
  join_policy: "open",
  request_pending: false,
  ...overrides,
});

const renderDirectory = (
  search: Record<string, unknown> = {},
  auth?: { user: ReturnType<typeof buildUser> }
) =>
  renderPage(CommunitiesPage, {
    initialRoute: "/communities",
    routerSearch: search,
    ...(auth ? { auth } : {}),
  });

/** The infinite-query shape the page reads: pages of items plus the paging
 *  flags. `total` is how many matched, so it can exceed what is loaded. */
const directoryResult = (
  items: DirectoryCommunityRead[],
  overrides: Record<string, unknown> = {}
) => ({
  data: { pages: [buildPage(items)] },
  isLoading: false,
  isError: false,
  hasNextPage: false,
  isFetchingNextPage: false,
  fetchNextPage,
  ...overrides,
});

/** What the page says instead of a grid. Exactly one is ever true at a time. */
const VERDICTS = ["No community directory here", "Directory unavailable", "No communities yet"];

/** Who the directory is rendered for, so a kept place has an owner. */
const reader = buildUser();

beforeEach(() => {
  saveNear(null, reader.id);
  vi.clearAllMocks();
  config.communityDirectory = true;
  config.ageGate = true;
  directoryFor.mockReturnValue(directoryResult([community()]));
});

describe("CommunitiesPage", () => {
  it("carries the page's heading over the banner, which is itself decorative", async () => {
    const { container } = renderDirectory();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Nobody builds a world alone" })
    ).toBeInTheDocument();
    // The words are DOM text laid over the image rather than baked into it, so
    // the image describes nothing on its own and stays out of the a11y tree.
    const banner = container.querySelector('img[src="/images/community-banner.webp"]');
    expect(banner).toHaveAttribute("alt", "");
    // The image's layer and the copy share one grid cell, so the copy is what
    // gives the banner its height: a translation that wraps to more lines on a
    // narrow screen opens the banner up rather than running past its edge.
    const ground = banner?.parentElement as HTMLElement | null;
    expect(ground?.style.gridRow).toBe("1");
    // The copy sits in a column with the badge corner, and that column is what
    // shares the cell with the ground.
    const copyColumn = screen.getByRole("heading", { level: 1 }).parentElement
      ?.parentElement as HTMLElement;
    expect(copyColumn.style.gridRow).toBe("1");
    // The picture covers whatever that comes to, rather than setting the
    // height itself and leaving a strip too short to read a heading on.
    expect(banner).toHaveClass("absolute", "inset-0", "object-cover");
  });

  it("says so, and asks nothing, where the owner runs no directory", async () => {
    config.communityDirectory = false;
    renderDirectory();

    expect(await screen.findByText("No community directory here")).toBeInTheDocument();
    // The endpoint refuses the request there, so the page must not make it.
    expect(directoryFor).toHaveBeenCalledWith(expect.anything(), { enabled: false });
  });

  // A tab that was open when the owner switched the directory off still has it
  // cached as on: it asks, and the answer settles it. The three verdicts are
  // separate findings, so exactly one of them is ever on screen.
  it.each([
    [
      "reads a refusal as the off state, not a failed load",
      {
        isError: true,
        error: {
          isAxiosError: true,
          response: { status: 403, data: { detail: "COMMUNITY_DIRECTORY_DISABLED" } },
        },
      },
      "No community directory here",
    ],
    [
      "still reports a directory that failed to load",
      { isError: true, error: new Error("boom") },
      "Directory unavailable",
    ],
    [
      "distinguishes an unreachable directory from an empty one",
      { data: undefined, isError: true },
      "Directory unavailable",
    ],
    [
      "says nobody has listed a community when the directory is genuinely empty",
      {},
      "No communities yet",
    ],
  ])("%s", async (_label, answer, verdict) => {
    directoryFor.mockReturnValue(directoryResult([], answer));
    renderDirectory();

    expect(await screen.findByText(verdict)).toBeInTheDocument();
    for (const other of VERDICTS.filter((text) => text !== verdict)) {
      expect(screen.queryByText(other)).not.toBeInTheDocument();
    }
  });

  it("shows a card per community", async () => {
    renderDirectory();

    expect(await screen.findByText("Riverside Players")).toBeInTheDocument();
    expect(screen.getByText("Community theatre.")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
    expect(screen.getByText("Art & design")).toBeInTheDocument();
  });

  it("says where a community is", async () => {
    directoryFor.mockReturnValue(
      directoryResult([
        community({
          location: {
            text: "Seattle, Washington, United States",
            label: "Queen Anne Neighborhood",
            country: "US",
            latitude: 47.6,
            longitude: -122.3,
          },
        }),
      ])
    );

    renderDirectory();

    expect(
      await screen.findByRole("link", {
        name: "Location: Queen Anne Neighborhood, Seattle, Washington, United States",
      })
    ).toBeInTheDocument();
  });

  it("puts the community's banner across the top of its card", async () => {
    directoryFor.mockReturnValue(
      directoryResult([
        community({ banner: buildBanner({ image_url: "/api/v1/communities/1/image/abc" }) }),
      ])
    );

    const { container } = renderDirectory();

    await screen.findByText("Riverside Players");
    const banner = container.querySelector('img[src="/api/v1/communities/1/image/abc"]');
    expect(banner).not.toBeNull();
    // Decorative: the card already says the community's name beneath it.
    expect(banner).toHaveAttribute("alt", "");
  });

  // A card with no artwork still has a banner: whatever colour its community set,
  // or the one it wears by default.
  it.each([
    [
      "the colour its community set instead",
      buildBanner({ color: "#2a9d8f" }),
      "rgb(42, 157, 143)",
    ],
    ["the colour its community wears by default", buildBanner(), "rgb(37, 99, 235)"],
  ])("gives a card with no artwork %s", async (_label, banner, colour) => {
    directoryFor.mockReturnValue(directoryResult([community({ banner })]));

    const { container } = renderDirectory();

    await screen.findByText("Riverside Players");
    expect(container.querySelector(`[style*="${colour}"]`)).not.toBeNull();
    // The page's own hero artwork is the only image on the page.
    expect(container.querySelectorAll("img")).toHaveLength(1);
  });

  // "0 online" reads as a verdict on the community rather than on the moment, so a
  // community nobody is in says nothing about presence at all.
  it.each([
    ["says who is there now beside how many there are", 3, "3 online"],
    ["says nothing about presence in a community nobody is in", 0, null],
  ])("%s", async (_label, online_count, online) => {
    directoryFor.mockReturnValue(directoryResult([community({ online_count })]));
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(screen.getByText("12 members")).toBeInTheDocument();
    if (online) {
      expect(screen.getByText(online)).toBeInTheDocument();
    } else {
      expect(screen.queryByText("0 online")).not.toBeInTheDocument();
    }
  });

  it("asks for everything until a category is picked", async () => {
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith(
      { search: undefined, category: undefined },
      { enabled: true }
    );
  });

  // The filters are the sidebar's, and the address is what carries them here,
  // so what this page owes is that it asks for what the address says.
  it.each([
    ["category", { category: "ttrpg" }, { category: ["ttrpg"] }],
    ["categories", { category: ["ttrpg", "gaming"] }, { category: ["ttrpg", "gaming"] }],
    ["search", { q: "dice" }, { search: "dice" }],
  ])("narrows the request to the %s in the address", async (_label, search, asked) => {
    renderDirectory(search);

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith(expect.objectContaining(asked), expect.anything());
  });

  // Below `lg` the sidebar that normally holds the search is off-canvas, so the
  // page carries a box of its own — the same one, writing the same address.
  it("searches from the page's own box", async () => {
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.type(screen.getByRole("textbox", { name: "Search communities" }), "dice");

    await waitFor(() =>
      expect(directoryFor).toHaveBeenCalledWith(
        expect.objectContaining({ search: "dice" }),
        expect.anything()
      )
    );
  });

  it("sends the countries a search names, so it reaches where communities are", async () => {
    renderDirectory({ q: "Japan" });
    await screen.findByText("Riverside Players");

    expect(directoryFor).toHaveBeenCalledWith(
      expect.objectContaining({ search: "Japan", search_country: ["JP"] }),
      expect.anything()
    );
  });

  it("sends no countries for a search that names none", async () => {
    renderDirectory({ q: "dice" });
    await screen.findByText("Riverside Players");

    expect(directoryFor).toHaveBeenCalledWith(
      expect.objectContaining({ search: "dice", search_country: undefined }),
      expect.anything()
    );
  });

  it("sorts from the place in the address", async () => {
    renderDirectory({
      near_country: "US",
      near_lat: 47.6,
      near_lon: -122.3,
      near_place: "Seattle, Washington, United States",
    });
    await screen.findByText("Riverside Players");

    // The words are the reader's own; only where it is goes to the server.
    expect(directoryFor).toHaveBeenCalledWith(
      expect.objectContaining({ near_country: "US", near_lat: 47.6, near_lon: -122.3 }),
      expect.anything()
    );
    expect(directoryFor.mock.lastCall?.[0]).not.toHaveProperty("near_place");
    expect(
      screen.getByRole("button", { name: "Near Seattle, Washington, United States" })
    ).toBeInTheDocument();
  });

  it("sorts from the place kept on this device, and forgets it when cleared", async () => {
    saveNear({ text: "Kyoto, Japan", country: "JP", latitude: 35.0, longitude: 135.8 }, reader.id);
    renderDirectory({}, { user: reader });
    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenLastCalledWith(
      expect.objectContaining({ near_country: "JP", near_lat: 35.0, near_lon: 135.8 }),
      expect.anything()
    );

    await userEvent.click(screen.getByRole("button", { name: "Stop sorting by location" }));

    await waitFor(() => expect(directoryFor.mock.lastCall?.[0]).not.toHaveProperty("near_country"));
    expect(screen.getByRole("button", { name: "Near me" })).toBeInTheDocument();
  });

  it("says what nothing matched, naming the search it came from", async () => {
    directoryFor.mockReturnValue(directoryResult([]));
    renderDirectory({ q: "dice" });

    expect(await screen.findByText("Nothing matched")).toBeInTheDocument();
    expect(screen.getByText(/dice/)).toBeInTheDocument();
  });

  it("joins a community from its card", async () => {
    join.mockResolvedValue({ id: 1 });
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => expect(join).toHaveBeenCalledWith(1));
  });

  it("asks an unconfirmed account its age before joining, not after", async () => {
    join.mockResolvedValue({ id: 1 });
    renderDirectory({}, { user: buildUser({ age_confirmed_at: null }) });
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    expect(await screen.findByText("How old are you?")).toBeInTheDocument();
    // Nothing joined on the strength of an unanswered question.
    expect(join).not.toHaveBeenCalled();
  });

  it("forgets a birthdate that was typed and then backed out of", async () => {
    // The dialog is kept mounted by the card, so nothing unmounts to clear
    // this — and a date left behind contradicts the note under the field.
    renderDirectory({}, { user: buildUser({ age_confirmed_at: null }) });
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Join" }));
    await userEvent.click(await screen.findByLabelText("Date of birth"));
    await userEvent.type(await screen.findByLabelText("Type or pick a date"), "1990-05-04{Enter}");
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByLabelText("Date of birth")).toHaveTextContent("May 4, 1990");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    expect(await screen.findByLabelText("Date of birth")).toHaveTextContent(
      "Pick your date of birth"
    );
    expect(join).not.toHaveBeenCalled();
  });

  it("joins without asking where the deployment does not ask", async () => {
    config.ageGate = false;
    join.mockResolvedValue({ id: 1 });
    renderDirectory({}, { user: buildUser({ age_confirmed_at: null }) });
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => expect(join).toHaveBeenCalledWith(1));
    expect(screen.queryByText("How old are you?")).not.toBeInTheDocument();
  });

  it("offers a way in, not a second join, for a community already joined", async () => {
    directoryFor.mockReturnValue(directoryResult([community({ already_member: true })]));
    renderDirectory();

    expect(await screen.findByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  describe("a community that takes requests", () => {
    beforeEach(() => {
      directoryFor.mockReturnValue(directoryResult([community({ join_policy: "request" })]));
    });

    it("asks rather than joins, with the note the reader wrote", async () => {
      ask.mockResolvedValue(undefined);
      renderDirectory();

      await userEvent.click(await screen.findByRole("button", { name: "Ask to join" }));
      const dialog = await screen.findByRole("dialog");
      // The note may be all the admins have to go on, so the dialog says so.
      expect(within(dialog).getByText(/may be all they have to go on/)).toBeInTheDocument();
      await userEvent.type(within(dialog).getByRole("textbox"), "  I run the Thursday read.  ");
      await userEvent.click(within(dialog).getByRole("button", { name: "Send request" }));

      await waitFor(() =>
        expect(ask).toHaveBeenCalledWith({ communityId: 1, message: "I run the Thursday read." })
      );
      expect(join).not.toHaveBeenCalled();
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("asks an unconfirmed account its age before asking, not after", async () => {
      renderDirectory({}, { user: buildUser({ age_confirmed_at: null }) });

      await userEvent.click(await screen.findByRole("button", { name: "Ask to join" }));

      expect(await screen.findByText("How old are you?")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Send request" })).not.toBeInTheDocument();
    });

    it("says the ask is waiting, and takes it back", async () => {
      directoryFor.mockReturnValue(
        directoryResult([community({ join_policy: "request", request_pending: true })])
      );
      withdraw.mockResolvedValue(undefined);
      renderDirectory();

      expect(await screen.findByText("Requested")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Ask to join" })).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Withdraw" }));

      await waitFor(() => expect(withdraw).toHaveBeenCalledWith(1));
    });
  });

  it("fetches the next page rather than asking for a bigger one", async () => {
    // A growing page_size runs into the endpoint's 60-per-page ceiling and
    // takes the whole grid down with it, so "show more" pages instead.
    directoryFor.mockReturnValue(directoryResult([community()], { hasNextPage: true }));
    renderDirectory();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    await waitFor(() => expect(fetchNextPage).toHaveBeenCalled());
    expect(directoryFor).not.toHaveBeenCalledWith(
      expect.objectContaining({ page_size: expect.anything() }),
      expect.anything()
    );
  });

  it("offers no more once every match is on screen", async () => {
    directoryFor.mockReturnValue(directoryResult([community()], { hasNextPage: false }));
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });
});
