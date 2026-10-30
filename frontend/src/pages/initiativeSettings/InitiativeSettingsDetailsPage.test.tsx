import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildInitiativeRole,
  buildUser,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeRead, InitiativeRoleRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "@/lib/mascotToast";

import { InitiativeSettingsDetailsPage } from "./InitiativeSettingsDetailsPage";

const INITIATIVE_ID = 7;
const MANAGER_ID = 42;

/** Records what each PATCH actually sent, so a save can be read field by field. */
function stubInitiative(overrides: Partial<InitiativeRead> = {}, patchFails?: [number, string]) {
  const patches: unknown[] = [];
  server.use(
    communityHttp.get("/initiatives/:id", () =>
      HttpResponse.json(
        buildInitiative({
          id: INITIATIVE_ID,
          name: "Apollo",
          can: initiativeCan({ manage: true }),
          ...overrides,
        })
      )
    ),
    communityHttp.patch("/initiatives/:id", async ({ request }) => {
      const body = await request.json();
      patches.push(body);
      if (patchFails) {
        const [status, detail] = patchFails;
        return HttpResponse.json({ detail }, { status });
      }
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }));
    })
  );
  return patches;
}

/** The initiative's roles, plus a record of every role PATCH the page sends. */
function stubRoles(roles: InitiativeRoleRead[]) {
  const patches: { roleId: string; body: unknown }[] = [];
  server.use(
    communityHttp.get("/initiatives/:id/roles", () => HttpResponse.json(roles)),
    communityHttp.patch("/initiatives/:id/roles/:roleId", async ({ request, params }) => {
      patches.push({ roleId: String(params.roleId), body: await request.json() });
      return HttpResponse.json(roles[0]);
    })
  );
  return patches;
}

/** The two roles most initiatives have: a manager who sees everything and an
 *  ordinary member who sees only what its permissions say. */
const managerRole = () =>
  buildInitiativeRole({
    id: 1,
    name: "project_manager",
    display_name: "Project Manager",
    is_builtin: true,
    is_manager: true,
  });
const memberRole = (permissions: Record<string, boolean> = {}) =>
  buildInitiativeRole({
    id: 2,
    name: "member",
    display_name: "Member",
    is_builtin: true,
    permissions: permissions as InitiativeRoleRead["permissions"],
  });

const renderDetails = (role: "admin" | "member" = "admin") =>
  renderPage(InitiativeSettingsDetailsPage, {
    auth: { user: buildUser({ id: MANAGER_ID }) },
    communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1, role }) },
    initialRoute: "/c/$communityId/i/$initiativeId/settings",
    routeParams: { communityId: "1", initiativeId: String(INITIATIVE_ID) },
  });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InitiativeSettingsDetailsPage", () => {
  it("refuses the section to someone who reached the address without the standing", async () => {
    stubInitiative({ can: initiativeCan() });

    // Straight to the section, with no layout in front of it.
    renderDetails("member");

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  /**
   * The master switch is half of what it looks like: the initiative offering a
   * tool and a role being allowed to see it are separate gates, and the switch
   * only ever moved the first. These cover the second being asked about,
   * answered, and reported.
   */
  describe("tool switches", () => {
    it("asks who a tool is for instead of turning it straight on", async () => {
      const patches = stubInitiative();
      stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByRole("switch", { name: /Posts/ }));

      expect(await screen.findByRole("dialog")).toHaveTextContent("Turn on Posts");
      // Nothing is saved until the audience question is answered.
      expect(patches).toHaveLength(0);
    });

    it("grants the tool to every ordinary role when it is for everyone", async () => {
      const initiativePatches = stubInitiative();
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByRole("switch", { name: /Posts/ }));
      await userEvent.click(await screen.findByRole("radio", { name: /Everyone in this/ }));
      await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));

      await waitFor(() => expect(initiativePatches).toEqual([{ posts_enabled: true }]));
      await waitFor(() => expect(rolePatches).toHaveLength(1));
      // The member role, not the manager one — a manager already sees everything.
      expect(rolePatches[0].roleId).toBe("2");
      // Only the key being granted is sent, so a permission somebody else
      // changed since the roster was read is not written back over.
      expect((rolePatches[0].body as { permissions: Record<string, boolean> }).permissions).toEqual(
        {
          posts_enabled: true,
        }
      );
    });

    it("leaves every role alone when the tool is for managers only", async () => {
      const initiativePatches = stubInitiative();
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByRole("switch", { name: /Posts/ }));
      await userEvent.click(await screen.findByRole("radio", { name: /Managers only/ }));
      await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));

      await waitFor(() => expect(initiativePatches).toEqual([{ posts_enabled: true }]));
      expect(rolePatches).toHaveLength(0);
    });

    it("says who can see a tool that is already on", async () => {
      stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole({ posts_enabled: true })]);

      renderDetails();

      // Scoped to the Posts row: projects and files are switched on too
      // now, so the page says "Visible to Member" in several places and only
      // this one is the answer under test.
      const postsRow = (await screen.findByRole("switch", { name: /Posts/ })).closest(
        "[data-slot='tool-card']"
      );
      expect(postsRow).not.toBeNull();
      expect(within(postsRow as HTMLElement).getByText(/Visible to Member/)).toBeInTheDocument();
    });

    it("shows a switch the community set as set, and offers no change", async () => {
      stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole({ posts_enabled: true })]);
      server.use(
        communityHttp.get("/initiatives/defaults", () =>
          HttpResponse.json({ tools: { post: true }, member_permissions: {}, custom_roles: true })
        )
      );

      renderDetails();

      const posts = await screen.findByRole("switch", { name: /Posts/ });
      await waitFor(() => expect(posts).toBeDisabled());
      const postsRow = posts.closest("[data-slot='tool-card']") as HTMLElement;
      expect(within(postsRow).getByText(/sets this for every initiative/)).toBeInTheDocument();
    });

    it("warns when a tool is on but no ordinary role has been given it", async () => {
      stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole()]);

      renderDetails();

      expect(await screen.findByText(/Only managers can see this/)).toBeInTheDocument();
    });

    it("grants it to everyone from that warning, without touching the switch", async () => {
      const initiativePatches = stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(
        (await screen.findAllByRole("button", { name: "Give it to everyone" }))[0]
      );

      await waitFor(() => expect(rolePatches).toHaveLength(1));
      expect(rolePatches[0].roleId).toBe("2");
      expect(initiativePatches).toHaveLength(0);
    });

    it("does not claim a tool reached everyone when the roster could not be read", async () => {
      const initiativePatches = stubInitiative();
      server.use(
        communityHttp.get("/initiatives/:id/roles", () =>
          HttpResponse.json({ detail: "BOOM" }, { status: 500 })
        )
      );

      renderDetails();

      await userEvent.click(await screen.findByRole("switch", { name: /Posts/ }));
      await userEvent.click(await screen.findByRole("radio", { name: /Everyone in this/ }));
      await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));

      // The switch still moves — that half succeeded — but the grant that
      // could not read the roster reports failure rather than success.
      await waitFor(() => expect(initiativePatches).toEqual([{ posts_enabled: true }]));
      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(toast.success).not.toHaveBeenCalledWith(expect.stringContaining("can now see"));
    });

    it("says what turning a tool off hides before it hides it", async () => {
      const patches = stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole({ posts_enabled: true })]);

      renderDetails();

      await userEvent.click(await screen.findByRole("switch", { name: /Posts/ }));

      expect(await screen.findByRole("alertdialog")).toHaveTextContent(
        /hides Posts and everything in it from everyone/
      );
      expect(patches).toHaveLength(0);

      await userEvent.click(screen.getByRole("button", { name: "Turn it off" }));
      await waitFor(() => expect(patches).toEqual([{ posts_enabled: false }]));
    });
  });
});
