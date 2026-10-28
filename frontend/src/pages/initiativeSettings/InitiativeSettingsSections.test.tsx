/**
 * Each settings section is its own route, so each one is asked to render on its
 * own — with nothing in front of it — and to refuse a reader who arrives at the
 * address without the standing the section needs.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildInitiativeJoinRequest,
  buildInitiativeRole,
  buildToolLayoutSet,
  buildUserSummary,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { InitiativeSettingsDangerPage } from "./InitiativeSettingsDangerPage";
import { InitiativeSettingsExportPage } from "./InitiativeSettingsExportPage";
import { InitiativeSettingsLayoutsPage } from "./InitiativeSettingsLayoutsPage";
import { InitiativeSettingsMembersPage } from "./InitiativeSettingsMembersPage";
import { InitiativeSettingsPropertiesPage } from "./InitiativeSettingsPropertiesPage";
import { InitiativeSettingsRolesPage } from "./InitiativeSettingsRolesPage";

const INITIATIVE_ID = 7;

/** The initiative, saying whether this reader may run it. */
function stubInitiative({
  manage = true,
  ...overrides
}: Partial<InitiativeRead> & { manage?: boolean } = {}) {
  const initiative = buildInitiative({
    id: INITIATIVE_ID,
    name: "Apollo",
    can: initiativeCan({ manage }),
    ...overrides,
  });
  server.use(
    communityHttp.get("/initiatives/", () => HttpResponse.json([initiative])),
    communityHttp.get("/initiatives/:id", () => HttpResponse.json(initiative)),
    communityHttp.get("/initiatives/:id/roles", () => HttpResponse.json([]))
  );
}

const renderSection = (
  Section: React.ComponentType,
  path: string,
  role: "admin" | "member" = "admin"
) =>
  renderPage(Section, {
    communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1, role }) },
    initialRoute: `/c/$communityId/i/$initiativeId/settings/${path}`,
    routeParams: { communityId: "1", initiativeId: String(INITIATIVE_ID) },
  });

describe("initiative settings sections", () => {
  it("serves the roster, and the queue feeding it, at /settings/members", async () => {
    stubInitiative();
    server.use(
      communityHttp.get("/initiatives/:id/join-requests", () =>
        HttpResponse.json([
          buildInitiativeJoinRequest({
            id: 11,
            initiative_id: INITIATIVE_ID,
            user: buildUserSummary({ id: 42, display_name: "Ada Lovelace" }),
          }),
        ])
      )
    );

    renderSection(InitiativeSettingsMembersPage, "members");

    expect(await screen.findByText("Requests to join")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Members")).toBeInTheDocument();
  });

  it("serves role permissions at /settings/roles", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsRolesPage, "roles");

    expect(await screen.findByText("Role permissions")).toBeInTheDocument();
  });

  /**
   * Moderator holds every permission by construction, so its card says what the
   * role is instead of offering a set of switches with nothing to change.
   */
  it("gives the moderator a card with no tool switches on /settings/roles", async () => {
    stubInitiative();
    server.use(
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([
          buildInitiativeRole({
            name: "moderator",
            display_name: "Moderator",
            is_builtin: true,
            is_manager: true,
            override_share_restrictions: true,
            position: 0,
          }),
          buildInitiativeRole({
            name: "member",
            display_name: "Member",
            is_builtin: true,
            position: 1,
          }),
        ])
      )
    );

    renderSection(InitiativeSettingsRolesPage, "roles");

    expect(await screen.findByText("Moderator")).toBeInTheDocument();
    expect(screen.getByText("Full access")).toBeInTheDocument();
    expect(screen.getByText(/Moderators can use every tool/)).toBeInTheDocument();

    // The member card carries the permission switches; this one carries none.
    const moderatorCard = screen.getByText("Moderator").closest("div.rounded-xl");
    expect(moderatorCard).not.toBeNull();
    expect(within(moderatorCard as HTMLElement).queryByRole("switch")).toBeNull();
    expect(screen.getAllByRole("switch").length).toBeGreaterThan(0);
  });

  it("gives the project manager a card with no tool switches either", async () => {
    stubInitiative();
    server.use(
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([
          buildInitiativeRole({
            name: "project_manager",
            display_name: "Project Manager",
            is_builtin: true,
            is_manager: true,
            position: 1,
          }),
        ])
      )
    );

    renderSection(InitiativeSettingsRolesPage, "roles");

    // It holds every permission by construction, like the moderator. It used
    // to render sixteen switches pinned on and refused — controls whose only
    // job was to say no.
    expect(await screen.findByText("Project Manager")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
    // Every tool permission, but not the share override — so it is a manager,
    // and "Full access" belongs to the moderator alone.
    expect(screen.getByText("Manager")).toBeInTheDocument();
    expect(screen.queryByText("Full access")).not.toBeInTheDocument();
  });

  it("keeps Delete on a custom manager role", async () => {
    stubInitiative();
    server.use(
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([
          buildInitiativeRole({
            name: "producer",
            display_name: "Producer",
            is_builtin: false,
            is_manager: true,
            member_count: 0,
          }),
        ])
      )
    );

    renderSection(InitiativeSettingsRolesPage, "roles");

    // It gets the manager summary like the built-in ones, but it is still a
    // role somebody made and can unmake — only the built-ins are permanent, so
    // its card carries rename AND delete, not rename alone.
    const card = (await screen.findByText("Producer")).closest("div.rounded-xl");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getAllByRole("button")).toHaveLength(2);
  });

  it("grants view along with create, and takes create away with view", async () => {
    const patches: Record<string, unknown>[] = [];
    stubInitiative();
    server.use(
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([
          buildInitiativeRole({
            id: 2,
            name: "member",
            display_name: "Member",
            is_builtin: true,
            permissions: { projects_enabled: true, create_projects: false },
          }),
        ])
      ),
      communityHttp.patch("/initiatives/:id/roles/:roleId", async ({ request }) => {
        patches.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: 2 });
      })
    );

    renderSection(InitiativeSettingsRolesPage, "roles");

    // Making something you cannot see is not a state worth being able to
    // express, so the pair moves together — in one write, never via a moment
    // where the role can create a project it cannot open.
    await userEvent.click(await screen.findByRole("switch", { name: "Create Projects" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      permissions: { projects_enabled: true, create_projects: true },
    });

    await userEvent.click(screen.getByRole("switch", { name: "View Projects" }));
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1]).toMatchObject({
      permissions: { projects_enabled: false, create_projects: false },
    });
  });

  /**
   * A permission for a tool the initiative has switched off grants nothing —
   * the mirror of the details screen never mentioning roles. The roles screen
   * has to say so, or the two halves of the gate stay invisible to each other.
   */
  it("says on /settings/roles when a tool's permissions grant nothing yet", async () => {
    stubInitiative({ posts_enabled: false });
    server.use(
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([buildInitiativeRole({ display_name: "Member" })])
      )
    );

    renderSection(InitiativeSettingsRolesPage, "roles");

    // The tools the initiative has switched off are gathered below a line,
    // under ONE explanation — not eight copies of the same sentence.
    expect(await screen.findByText("Turned off for this initiative")).toBeInTheDocument();
    expect(screen.getAllByText(/grant nothing until the tool is turned back on/)).toHaveLength(1);
  });

  it("serves custom properties at /settings/properties", async () => {
    stubInitiative();
    server.use(communityHttp.get("/property-definitions/", () => HttpResponse.json([])));

    renderSection(InitiativeSettingsPropertiesPage, "properties");

    expect(
      await screen.findByText("Define reusable metadata for anything in this initiative.")
    ).toBeInTheDocument();
  });

  it("serves the export wizard at /settings/export", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsExportPage, "export");

    expect(await screen.findByRole("button", { name: /Export/ })).toBeInTheDocument();
  });

  it("serves archiving and deletion at /settings/danger", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsDangerPage, "danger");

    expect(
      await screen.findByText(/Deleting an initiative removes all of its projects/)
    ).toBeInTheDocument();
  });

  it("lists the calendar's and each project's layouts at /settings/layouts", async () => {
    stubInitiative({ calendars_enabled: true });
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(buildToolLayoutSet({ tool: "calendar" }))
      ),
      communityHttp.get("/layouts/initiative", () =>
        HttpResponse.json([
          {
            tool: "project",
            tool_id: 3,
            name: "Launch",
            ...buildToolLayoutSet({
              layouts: [
                {
                  kind: "table",
                  is_default: false,
                  hidden: false,
                  definition: {},
                  updated_at: null,
                },
                {
                  kind: "board",
                  is_default: true,
                  hidden: false,
                  definition: {},
                  updated_at: "2026-10-01T12:00:00.000Z",
                },
              ],
            }),
          },
          {
            tool: "project",
            tool_id: 4,
            name: "Archive digs",
            ...buildToolLayoutSet({ can_configure: false }),
          },
        ])
      )
    );

    renderSection(InitiativeSettingsLayoutsPage, "layouts");

    // In the sidebar's order: the calendar before the projects.
    const calendar = await screen.findByRole("region", { name: "Calendar" });
    expect(within(calendar).getByText("Event detail")).toBeInTheDocument();
    expect(within(calendar).getByRole("link", { name: /edit layouts/i })).toHaveAttribute(
      "href",
      `/c/1/i/${INITIATIVE_ID}/calendars/layouts`
    );
    const launch = await screen.findByRole("region", { name: "Launch" });
    expect(
      calendar.compareDocumentPosition(launch) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    const board = within(launch).getByText("Board").closest("li");
    expect(board).not.toBeNull();
    expect(
      within(board as HTMLElement).getByRole("img", { name: "Opens first" })
    ).toBeInTheDocument();
    expect(within(board as HTMLElement).getByRole("time")).toBeInTheDocument();
    const table = within(launch).getByText("Table").closest("li");
    expect(within(table as HTMLElement).getByLabelText("As shipped")).toBeInTheDocument();
    expect(within(launch).getByRole("link", { name: /edit layouts/i })).toHaveAttribute(
      "href",
      expect.stringContaining("/projects/3/layouts")
    );
    const digs = screen.getByRole("region", { name: "Archive digs" });
    expect(within(digs).queryByRole("link", { name: /edit layouts/i })).not.toBeInTheDocument();
  });

  it.each([
    ["members", InitiativeSettingsMembersPage],
    ["roles", InitiativeSettingsRolesPage],
    ["properties", InitiativeSettingsPropertiesPage],
    ["layouts", InitiativeSettingsLayoutsPage],
    ["export", InitiativeSettingsExportPage],
    ["danger", InitiativeSettingsDangerPage],
  ])(
    "refuses /settings/%s to a reader who may not configure the initiative",
    async (path, Section) => {
      stubInitiative({ manage: false });

      // The address is typeable, so the section — not the tab bar — is what says no.
      renderSection(Section as React.ComponentType, path as string, "member");

      expect(await screen.findByText("Permission required")).toBeInTheDocument();
    }
  );
});
