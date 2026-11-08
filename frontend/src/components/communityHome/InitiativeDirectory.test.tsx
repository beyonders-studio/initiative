import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildInitiativeDirectoryEntry,
  buildInitiativeJoinRequest,
  buildUser,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type InitiativeDirectoryEntry,
  InitiativeJoinPolicy,
  Tool,
  type UserRead,
} from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "@/lib/mascotToast";
import { getItem } from "@/lib/storage";

import { InitiativeDirectory } from "./InitiativeDirectory";

const OPEN_ID = 5;

/** The memory router mounts asynchronously, so every test awaits its first
 *  query. The marker gives the empty case something to wait for. */
const renderDirectory = (entries: InitiativeDirectoryEntry[], user?: UserRead) =>
  renderPage(
    () => (
      <>
        <div data-testid="mounted" />
        <InitiativeDirectory entries={entries} />
      </>
    ),
    {
      communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1 }) },
      ...(user ? { auth: { user } } : {}),
    }
  );

/** The same directory seen by a community admin, whose authority over the community is
 *  not membership of anything in it. */
const renderDirectoryAsAdmin = (entries: InitiativeDirectoryEntry[]) =>
  renderPage(() => <InitiativeDirectory entries={entries} />, {
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin" }),
    },
  });

const openEntry = () =>
  buildInitiativeDirectoryEntry({ id: OPEN_ID, name: "Nebula", join_policy: "open" });

const REQUEST_ID = 6;

const requestEntry = (overrides: Partial<InitiativeDirectoryEntry> = {}) =>
  buildInitiativeDirectoryEntry({
    id: REQUEST_ID,
    name: "Vanguard",
    join_policy: "request",
    ...overrides,
  });

/** The group a heading names, so a card can be asserted to be in one. */
const group = (name: string) => screen.getByRole("heading", { name }).parentElement as HTMLElement;

/** The reader's own row inside an initiative they belong to — the listing the
 *  card reads its badge and its counts from. Returns the reader. */
const stubMembership = (initiative: Parameters<typeof buildInitiative>[0] = {}) => {
  const user = buildUser({ id: 42 });
  server.use(
    communityHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: 7, name: "Apollo", ...initiative })])
    )
  );
  return user;
};

/** The card for an initiative the reader is in. */
const memberEntry = (overrides: Parameters<typeof buildInitiativeDirectoryEntry>[0] = {}) =>
  buildInitiativeDirectoryEntry({ id: 7, name: "Apollo", is_member: true, ...overrides });

/** Records each knock the page sends, and answers however this case needs. */
const stubJoinRequests = (answer?: () => Response) => {
  const sent: Array<{ id: string; body: unknown }> = [];
  server.use(
    communityHttp.post("/initiatives/:id/join-requests", async ({ params, request }) => {
      sent.push({ id: String(params.id), body: await request.json() });
      return (
        answer?.() ??
        HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: REQUEST_ID }), {
          status: 201,
        })
      );
    })
  );
  return sent;
};

/** Records each initiative walked into, and answers however this case needs. */
const stubJoins = (answer?: () => Response) => {
  const joined: string[] = [];
  server.use(
    communityHttp.post("/initiatives/:id/join", ({ params }) => {
      joined.push(String(params.id));
      return answer?.() ?? HttpResponse.json(buildInitiative({ id: OPEN_ID, name: "Nebula" }));
    })
  );
  return joined;
};

describe("InitiativeDirectory", () => {
  it("offers Join only on an initiative anyone can join", async () => {
    renderDirectory([
      openEntry(),
      buildInitiativeDirectoryEntry({ id: 6, name: "Vanguard", join_policy: "request" }),
    ]);

    // A request-policy card asks rather than walks in, so exactly one card
    // carries the Join button.
    expect(await screen.findByText("Vanguard")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Join" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Request to join" })).toBeInTheDocument();
    // Neither card has anybody waiting, so neither says so.
    expect(screen.queryByText(/waiting to join/)).not.toBeInTheDocument();
  });

  it("splits the ones you're in from the ones you could join", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({ id: 7, name: "Apollo", is_member: true }),
      openEntry(),
    ]);

    expect(await screen.findByRole("heading", { name: "Your initiatives" })).toBeInTheDocument();
    expect(within(group("Your initiatives")).getByText("Apollo")).toBeInTheDocument();
    expect(within(group("Open to join")).getByText("Nebula")).toBeInTheDocument();
  });

  it("files a card you're not in under Open to join, as plain text with no counts", async () => {
    renderDirectory([openEntry()]);

    expect(await screen.findByRole("heading", { name: "Open to join" })).toBeInTheDocument();
    // No heading over an empty grid.
    expect(screen.queryByRole("heading", { name: "Your initiatives" })).not.toBeInTheDocument();
    // A title you cannot enter is not a link, and what is inside a card you are
    // not in is not on offer either.
    expect(screen.getByText("Nebula")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nebula" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^Projects:/)).not.toBeInTheDocument();
  });

  it("leads into an initiative you're in from its title", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 7,
        name: "Apollo",
        join_policy: "open",
        is_member: true,
      }),
    ]);

    // The title is the way in — there is no second button saying the same.
    expect(await screen.findByRole("link", { name: "Apollo" })).toHaveAttribute("href", "/c/1/i/7");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("shows the reader's own private initiative as theirs, never as joinable", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 9,
        name: "Skunkworks",
        join_policy: "private",
        is_member: true,
      }),
    ]);

    // A member's private initiative rounds out the list: in their own group,
    // labeled invite-only, with nothing offered to anyone else's eyes.
    expect(await screen.findByText("Invite only")).toBeInTheDocument();
    expect(within(group("Your initiatives")).getByText("Skunkworks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  // An admin's authority over the community is unchanged; this page just stops
  // standing in for it. An admin can reach either card anyway, so it stays on
  // offer rather than being filed as theirs — and an admin walks in rather than
  // knocking, so it carries Join and never Request to join.
  it.each([
    ["one that asks people to knock", InitiativeJoinPolicy.request, "Knockable", 11],
    ["one anyone can join", InitiativeJoinPolicy.open, "Nebula", 12],
  ])(
    "offers an admin %s they have not joined, without filing it as theirs",
    async (_label, join_policy, name, id) => {
      renderDirectoryAsAdmin([
        buildInitiativeDirectoryEntry({ id, name, join_policy, is_member: false }),
      ]);

      expect(await screen.findByRole("heading", { name: "Open to join" })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Your initiatives" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Join" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
    }
  );

  it("names the reader's role on a card they're in", async () => {
    const user = stubMembership();

    renderDirectory([memberEntry({ role_display_name: "Project Manager" })], user);

    // The badge says WHAT you are there, which already implies that you're in.
    expect(await screen.findByText("Project Manager")).toBeInTheDocument();
    expect(screen.queryByText("Joined")).not.toBeInTheDocument();
  });

  it("counts what is inside an initiative you're in, tool by tool", async () => {
    const user = stubMembership({
      counter_groups_enabled: true,
      // Calendars stay off for this reader, so they get no stat.
      can: initiativeCan({ view: [Tool.project, Tool.counter_group] }),
    });
    server.use(
      communityHttp.get("/tools/counts/by-initiative", () =>
        HttpResponse.json({ counts: { project: { "7": 3 }, counter_group: { "7": 2 } } })
      )
    );

    renderDirectory([memberEntry()], user);

    expect(await screen.findByText("Projects: 3")).toBeInTheDocument();
    expect(screen.getByText("Counters: 2")).toBeInTheDocument();
    // A tool this member can't view has no number to report.
    expect(screen.queryByText(/^Calendar:/)).not.toBeInTheDocument();
  });

  it.each([
    ["1 member", 1],
    ["3 members", 3],
  ])("names each initiative's roster size as %s", async (shown, member_count) => {
    renderDirectory([buildInitiativeDirectoryEntry({ name: "Nebula", member_count })]);

    expect(await screen.findByText(shown)).toBeInTheDocument();
  });

  it("collapses the whole section from its heading, and remembers it", async () => {
    const { unmount } = renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: /Initiatives/ }));

    await waitFor(() => expect(screen.queryByText("Nebula")).not.toBeInTheDocument());
    expect(getItem("guildHome.initiatives.collapsed.1")).toBe("true");

    // Coming back to this community finds the section as it was left.
    unmount();
    renderDirectory([openEntry()]);
    await screen.findByTestId("mounted");
    expect(screen.queryByText("Nebula")).not.toBeInTheDocument();
  });

  it("sends a request to join, with the note the reader wrote", async () => {
    const requests = stubJoinRequests();

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.type(await screen.findByLabelText(/Message/), "I run the Thursday session.");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toEqual({
      id: String(REQUEST_ID),
      body: { message: "I run the Thursday session." },
    });
    expect(toast.success).toHaveBeenCalledWith("Your request to join Vanguard was sent.");
  });

  it("sends a request with no note at all", async () => {
    const requests = stubJoinRequests();

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // The note is optional, and an empty one is sent as no note rather than "".
    await waitFor(() => expect(requests.map((sent) => sent.body)).toEqual([{ message: null }]));
  });

  it("shows a knock already waiting as a state, not a button", async () => {
    renderDirectory([requestEntry({ has_pending_request: true })]);

    expect(await screen.findByText("Requested")).toBeInTheDocument();
    // Nothing the requester can press moves it along.
    expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
  });

  it("explains a refused request in the reader's own words", async () => {
    stubJoinRequests(() =>
      HttpResponse.json({ detail: "INITIATIVE_JOIN_REQUEST_ALREADY_PENDING" }, { status: 409 })
    );

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // The backend answers with a code; the reader gets the mapped sentence.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "You already have a request waiting on this initiative"
      )
    );
  });

  it("tells a manager how many are waiting at their own door", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 7,
        name: "Apollo",
        join_policy: "request",
        is_member: true,
        pending_join_request_count: 3,
      }),
    ]);

    // The count reads zero for anyone who couldn't answer the queue, so its
    // presence is the permission check.
    expect(await screen.findByText("3 waiting to join")).toBeInTheDocument();
    // And it leads to the queue itself, which is a route of its own.
    expect(screen.getByRole("link", { name: "3 waiting to join" })).toHaveAttribute(
      "href",
      "/c/1/i/7/settings/members"
    );
  });

  it("joins an open initiative and says so", async () => {
    const joined = stubJoins();

    renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    await waitFor(() => expect(joined).toEqual([String(OPEN_ID)]));
    expect(toast.success).toHaveBeenCalledWith("You joined Nebula.");
  });

  it("explains a refused join in the reader's own words", async () => {
    stubJoins(() => HttpResponse.json({ detail: "INITIATIVE_NOT_JOINABLE" }, { status: 403 }));

    renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // The backend answers with a code; the reader gets the mapped sentence.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This initiative isn't open to join")
    );
  });

  it("renders nothing when the community lists no initiatives", async () => {
    renderDirectory([]);

    await screen.findByTestId("mounted");
    expect(screen.queryByRole("heading", { name: "Initiatives" })).not.toBeInTheDocument();
  });
});
