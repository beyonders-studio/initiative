/**
 * The roster a community's member count leads to.
 *
 * The page adds a surface rather than a source: it asks the same people
 * aggregate the new-conversation picker reads, for one community. So what is worth asserting
 * here is that it asks for the right one, pages within it, and offers each
 * person the same way in that they get anywhere else.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { getListCustomRolesQueryKey } from "@/api/generated/custom-roles/custom-roles";
import type { CommunityRole } from "@/api/generated/initiativeAPI.schemas";

import { MembersPage } from "./MembersPage";

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

/** Every roster read, by its address. */
let searched: URL[] = [];

const answer = (items: ReturnType<typeof person>[], total = items.length) =>
  server.use(
    communityHttp.get("/users/search", ({ request }) => {
      searched.push(new URL(request.url));
      return HttpResponse.json({
        items,
        total_count: total,
        page: 1,
        page_size: 25,
        has_next: false,
        has_prev: false,
      });
    })
  );

/** Records each body sent to `method path`, answering `reply`. */
const capture = (method: "post" | "put" | "patch", path: string, reply: object = {}) => {
  const sent: { url: string; body: unknown }[] = [];
  server.use(
    http[method](path, async ({ request }) => {
      sent.push({ url: new URL(request.url).pathname, body: await request.json() });
      return HttpResponse.json(reply);
    })
  );
  return sent;
};

const setup = (
  displayName: string | null = null,
  role: CommunityRole = "member",
  {
    closedSurfaces = null,
    queryClient,
  }: { closedSurfaces?: string[] | null; queryClient?: QueryClient } = {}
) => {
  const community = buildCommunity({
    id: 7,
    display_name: displayName,
    role,
    closed_surfaces: closedSurfaces,
  });
  return renderPage(() => <MembersPage />, {
    initialRoute: "/c/$communityId/members",
    routeParams: { communityId: "7" },
    auth: { user: buildUser({ id: 99 }) },
    communities: { communities: [community], activeCommunityId: 7, activeCommunity: community },
    queryClient,
  });
};

// Each read that lands redraws the rows, which closes a menu open in one: wait
// for the last to land, and for the redraw it schedules.
const settled = async ({ queryClient }: ReturnType<typeof setup>) => {
  await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
};

beforeEach(() => {
  searched = [];
  answer([]);
});

describe("a community's members page", () => {
  it("asks the community's own roster, and lists everyone in it, reachable or not", async () => {
    answer([person(1, "ada")]);
    await settled(setup());

    // A row leads to that person.
    expect((await screen.findByText("ada")).closest("a")).toHaveAttribute("href", "/u/ada1234");
    const url = searched.at(-1);
    expect(url?.pathname).toBe("/api/v1/c/7/users/search");
    expect(url?.searchParams.get("page")).toBe("1");
    expect(url?.searchParams.get("self_first")).toBe("true");
    // The point of reading the roster rather than the people aggregate: a
    // members page that hid everyone unreachable would be missing members.
    // Somebody who takes no messages has nothing to click.
    expect(screen.queryByRole("link", { name: /message/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /ask to message/i })).toBeNull();
    // And no connect button either: the server would refuse that too, and a
    // roster is the one place a refusal is not worth offering.
    expect(screen.queryByRole("button", { name: /^connect$/i })).toBeNull();

    // Everything else a person can be sits behind the overflow. Ignoring above
    // all: a roster is the likeliest place to want it, and it used to mean
    // knowing somebody's exact handle and opening Settings.
    await userEvent.click(screen.getByRole("button", { name: /actions for ada/i }));
    expect(await screen.findByRole("menuitem", { name: /^ignore$/i })).toBeInTheDocument();
  });

  it("offers the conversation where the server says there is one", async () => {
    server.use(
      http.post("/api/v1/me/dm-permissions", () =>
        HttpResponse.json({ permissions: { "1": { permission: "open", may_connect: true } } })
      )
    );
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

  it("asks about the whole page at once", async () => {
    // Asked per row, this is a request per row -- a hundred on a full page.
    const asked = capture("post", "/api/v1/me/dm-permissions", { permissions: {} });
    answer([person(1, "ada"), person(2, "bram")]);
    setup();

    await screen.findByText("ada");
    await waitFor(() => expect(asked.map(({ body }) => body)).toEqual([{ user_ids: [1, 2] }]));
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
    const sent = capture("put", "/api/v1/communities/:id/membership/display-name");
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
      expect(sent).toEqual([
        { url: "/api/v1/communities/7/membership/display-name", body: { display_name: "Ana B" } },
      ])
    );
  });

  it("clears your name when it is left empty", async () => {
    const sent = capture("put", "/api/v1/communities/:id/membership/display-name");
    answer([person(99, "me")]);
    setup("Ana");

    await userEvent.click(await screen.findByRole("button", { name: "Set your display name" }));
    await userEvent.clear(await screen.findByLabelText("Display name"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent.map(({ body }) => body)).toEqual([{ display_name: null }]));
  });

  it("runs what a custom role holds from here: invites, and members below admin", async () => {
    // A member whose role holds the roster and invites, and nothing else.
    server.use(
      communityHttp.get("/custom-roles/held", () =>
        HttpResponse.json({ surfaces: ["members", "invites"] })
      ),
      communityHttp.get("/custom-roles/", () =>
        HttpResponse.json([
          { id: 1, name: "Doors", base_rung: "member", surfaces: ["invites"] },
          { id: 2, name: "Roll", base_rung: "admin", surfaces: ["members"] },
        ])
      ),
      http.get("/api/v1/communities/:id/invites", () => HttpResponse.json([]))
    );
    const invites = capture("post", "/api/v1/communities/:id/invites", { id: 5, code: "door" });
    answer([person(1, "ada"), person(2, "bram", { community_role: "admin" })]);
    await settled(setup());

    await userEvent.click(await screen.findByRole("button", { name: "Invite members" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generate invite" }));
    expect(await screen.findByText(/\/invite\/door$/)).toBeInTheDocument();
    expect(invites[0].url).toBe("/api/v1/communities/7/invites");
    expect(invites[0].body).toMatchObject({ max_uses: 1 });
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: /actions for ada/i }));
    expect(await screen.findByRole("menuitem", { name: "Set display name" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Remove from community" })).toBeInTheDocument();
    // Making or unmaking an admin takes every part, which this role lacks.
    expect(screen.queryByRole("menuitem", { name: "Community role" })).toBeNull();
    // And it gives only the roles it could make: none on the admin rung.
    await userEvent.click(screen.getByRole("menuitem", { name: "Custom role" }));
    expect(await screen.findByRole("menuitemradio", { name: "Doors" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio", { name: /Roll/ })).toBeNull();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: /actions for bram/i }));
    expect(await screen.findByRole("menuitem", { name: "Set display name" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Remove from community" })).toBeNull();
  });

  it("lets an admin change a member's rung, and gives no custom role while they are off", async () => {
    const rungs = capture("patch", "/api/v1/communities/:id/members/:userId");
    answer([person(1, "ada")]);
    // Custom roles are switched off here, and another page has already read
    // this community's into the cache, which keeps them.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(getListCustomRolesQueryKey(7), [
      { id: 1, name: "Doors", base_rung: "member", surfaces: ["invites"] },
    ]);
    await settled(setup(null, "admin", { closedSurfaces: ["custom_roles"], queryClient }));

    await userEvent.click(await screen.findByRole("button", { name: /actions for ada/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Community role" }));
    expect(screen.queryByRole("menuitem", { name: "Custom role" })).toBeNull();
    await userEvent.click(await screen.findByRole("menuitemradio", { name: "Admin" }));

    await waitFor(() =>
      expect(rungs).toEqual([{ url: "/api/v1/communities/7/members/1", body: { role: "admin" } }])
    );
  });

  it("says so when the roster cannot be read", async () => {
    server.use(communityHttp.get("/users/search", () => new HttpResponse(null, { status: 500 })));
    setup();

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
  });
});
