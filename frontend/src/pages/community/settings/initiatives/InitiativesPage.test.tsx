/**
 * Settings › Initiatives: the roster and its project-manager picker, and the
 * rules the community sets for every initiative.
 *
 * The roster is a community admin's way into an initiative they have not
 * joined: their sidebar lists only their own memberships, so taking the
 * project manager role here is what brings one into it.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildInitiativeMember,
  buildPage,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { InitiativesPage } from "./InitiativesPage";

const INITIATIVE_ID = 7;
const ADMIN_ID = 1;
const MEMBER_ID = 2;

const PM_ROLE = {
  id: 10,
  initiative_id: INITIATIVE_ID,
  name: "project_manager",
  display_name: "Project Manager",
  is_manager: true,
  is_builtin: true,
  override_share_restrictions: false,
  permissions: {},
};
const MEMBER_ROLE = {
  ...PM_ROLE,
  id: 11,
  name: "member",
  display_name: "Member",
  is_manager: false,
};

/** The initiative's managers, as the picker asks for them, and the roles it
 *  resolves against. */
function stubTable(managers: ReturnType<typeof buildInitiativeMember>[]) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  server.use(
    communityHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: INITIATIVE_ID, name: "Apollo", member_count: 3 })])
    ),
    // Only the managers: an answer to anything wider would hand the picker
    // people who are not.
    communityHttp.get("/initiatives/:id/members", ({ request }) =>
      new URL(request.url).searchParams.get("is_manager") === "true"
        ? HttpResponse.json(buildPage(managers))
        : HttpResponse.json({ detail: "unexpected roster read" }, { status: 400 })
    ),
    communityHttp.get("/initiatives/:id/roles", () => HttpResponse.json([PM_ROLE, MEMBER_ROLE])),
    // The community's member search — what the picker offers, and how it learns
    // whether a manager is a community admin.
    communityHttp.get("/users/search", () =>
      HttpResponse.json(
        buildPage([
          buildUserSummary({
            id: ADMIN_ID,
            username: "ada",
            display_name: "Ada Lovelace",
            community_role: "admin",
          }),
          buildUserSummary({
            id: MEMBER_ID,
            username: "bo",
            display_name: "Bo Diddley",
            community_role: "member",
          }),
        ])
      )
    ),
    communityHttp.post("/initiatives/:id/members", async ({ request }) => {
      calls.push({ method: "POST", url: "members", body: await request.json() });
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID }));
    }),
    communityHttp.patch("/initiatives/:id/members/:userId", async ({ request, params }) => {
      calls.push({ method: "PATCH", url: String(params.userId), body: await request.json() });
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID }));
    }),
    communityHttp.delete("/initiatives/:id/members/:userId", ({ params }) => {
      calls.push({ method: "DELETE", url: String(params.userId) });
      return new HttpResponse(null, { status: 204 });
    })
  );
  return calls;
}

const render = () => {
  const community = buildCommunity({ id: 1, role: "admin" });
  renderPage(() => <InitiativesPage />, {
    communities: {
      communities: [community],
      activeCommunityId: community.id,
      activeCommunity: community,
    },
  });
};

/** Opens the row's manager picker and ticks (or unticks) one candidate. */
async function pick(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("combobox", { name: "Project managers" }));
  await user.click(await screen.findByRole("option", { name }));
}

describe("InitiativesPage project managers", () => {
  it("names the initiative's managers, and says so when it has none", async () => {
    stubTable([]);
    render();

    expect(await screen.findByRole("combobox", { name: "Project managers" })).toHaveTextContent(
      "No manager"
    );
    // The headcount is the row's own, not a roster read per row.
    expect(screen.getByText("3 members")).toBeInTheDocument();
  });

  it("reads every manager, starting again when the roster changes between pages", async () => {
    stubTable([]);
    const ada = buildInitiativeMember({
      user: buildUserSummary({ id: ADMIN_ID, display_name: "Ada Lovelace" }),
    });
    const bo = buildInitiativeMember({
      user: buildUserSummary({ id: MEMBER_ID, display_name: "Bo Diddley" }),
    });
    const asked: number[] = [];
    server.use(
      communityHttp.get("/initiatives/:id/members", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        asked.push(page);
        // The first ask for page 2 lands after a change: past the end, so the
        // server answers with page 1 again.
        const served = page === 2 && asked.filter((p) => p === 2).length > 1 ? 2 : 1;
        return HttpResponse.json(
          buildPage(served === 1 ? [ada] : [bo], { page: served, has_next: served === 1 })
        );
      })
    );
    render();

    expect(await screen.findByRole("combobox", { name: "Project managers" })).toHaveTextContent(
      "Ada Lovelace and Bo Diddley"
    );
    expect(asked).toEqual([1, 2, 2]);
  });

  // The same call promotes someone already in it: the server moves an existing
  // member onto the role it names rather than adding them twice.
  it("adds a community admin who is in no initiative as its project manager", async () => {
    const calls = stubTable([]);
    const user = userEvent.setup();
    render();

    await pick(user, "Ada Lovelace");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "POST",
      body: { user_id: ADMIN_ID, role_id: PM_ROLE.id },
    });
  });

  it("unticking an ordinary manager leaves them in the initiative as a member", async () => {
    const calls = stubTable([
      buildInitiativeMember({
        user: buildUserSummary({ id: MEMBER_ID, username: "bo" }),
        role_id: PM_ROLE.id,
        role_name: "project_manager",
        is_manager: true,
      }),
    ]);
    const user = userEvent.setup();
    render();

    await pick(user, "Bo Diddley");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      url: String(MEMBER_ID),
      body: { role_id: MEMBER_ROLE.id },
    });
  });

  it("unticking a community admin takes their membership away, since they hold no other role", async () => {
    const calls = stubTable([
      buildInitiativeMember({
        user: buildUserSummary({ id: ADMIN_ID, username: "ada" }),
        role_id: PM_ROLE.id,
        role_name: "project_manager",
        is_manager: true,
      }),
    ]);
    const user = userEvent.setup();
    render();

    await pick(user, "Ada Lovelace");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "DELETE", url: String(ADMIN_ID) });
  });
});

describe("InitiativesPage roster and rules", () => {
  it("keeps archived initiatives in a view of their own", async () => {
    stubTable([]);
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }),
          buildInitiative({ id: 8, name: "Gemini", archived_at: "2026-01-01T00:00:00Z" }),
        ])
      )
    );
    const user = userEvent.setup();
    render();

    expect(await screen.findByText("Apollo")).toBeInTheDocument();
    expect(screen.queryByText("Gemini")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Archived/ }));
    expect(await screen.findByText("Gemini")).toBeInTheDocument();
    expect(screen.queryByText("Apollo")).not.toBeInTheDocument();
  });

  it("lists the community's rules as sentences, and names who a new one changes", async () => {
    stubTable([]);
    let saved: unknown;
    server.use(
      communityHttp.get("/initiatives/defaults", () =>
        HttpResponse.json({
          tools: { contact: false },
          member_permissions: { create_posts: false },
          plugin_member_permissions: [],
          custom_roles: true,
          own_tools: { calendar: [INITIATIVE_ID] },
          own_member_permissions: {},
        })
      ),
      communityHttp.patch("/initiatives/defaults", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({});
      })
    );
    const user = userEvent.setup();
    render();

    expect(await screen.findByText("Turned off in every initiative.")).toBeInTheDocument();
    expect(screen.getByText("Members can't create posts.")).toBeInTheDocument();

    // Calendar is the first tool with no rule, in sidebar order.
    await user.click(screen.getByRole("button", { name: "Add a rule" }));
    await user.click(await screen.findByRole("radio", { name: "Off in every initiative" }));
    expect(
      screen.getByText("Turns Calendar off in Apollo. Nothing in it is deleted.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save rule" }));
    await waitFor(() =>
      expect(saved).toEqual({
        tools: { calendar: false },
        member_permissions: { calendars_enabled: null, create_calendars: null },
      })
    );
  });

  it("lists a plug-in's rule beside the tools', and names who a change reaches", async () => {
    stubTable([]);
    let saved: unknown;
    server.use(
      // CI is placed in Apollo only, so Gemini is never changed.
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }),
          buildInitiative({ id: 8, name: "Gemini" }),
        ])
      ),
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({
          items: [
            {
              id: 3,
              name: "CI",
              placed_initiative_ids: [INITIATIVE_ID],
              permissions: [
                { id: "use", level: "initiative", name: null, members: false },
                { id: "export", level: "initiative", name: { en: "Export builds" }, members: true },
                { id: "use", level: "community", name: null, members: false },
              ],
            },
          ],
        })
      ),
      communityHttp.get("/initiatives/defaults", () =>
        HttpResponse.json({
          tools: {},
          member_permissions: {},
          plugin_member_permissions: [{ install_id: 3, permission: "export", enabled: false }],
          custom_roles: true,
          own_tools: {},
          own_member_permissions: {},
          // Apollo's own Member role holds export beneath the rule, and not use.
          own_plugin_member_permissions: [
            { install_id: 3, permission: "use", initiative_ids: [] },
            { install_id: 3, permission: "export", initiative_ids: [INITIATIVE_ID] },
          ],
        })
      ),
      communityHttp.patch("/initiatives/defaults", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({});
      })
    );
    const user = userEvent.setup();
    render();

    expect(await screen.findByText("Only managers have “Export builds”.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit the CI rule" }));
    const use = await screen.findByRole("radiogroup", { name: "Do members have “Use”?" });
    await user.click(within(use).getByRole("radio", { name: "Yes, in every initiative" }));
    const exportRule = screen.getByRole("radiogroup", { name: "Do members have “Export builds”?" });
    await user.click(within(exportRule).getByRole("radio", { name: "Each initiative decides" }));
    expect(screen.getByText("Gives members “Use” in Apollo.")).toBeInTheDocument();
    expect(screen.getByText("Gives members “Export builds” in Apollo.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save rule" }));
    await waitFor(() =>
      expect(saved).toEqual({
        plugin_member_permissions: [
          { install_id: 3, permission: "use", enabled: true },
          { install_id: 3, permission: "export", enabled: null },
        ],
      })
    );
  });
});
