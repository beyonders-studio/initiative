/**
 * The door into an initiative, which lives with the roster it fills:
 * `/settings/members` is where a manager sets who may join and how, sees who
 * has asked, and manages who is already in.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildInitiativeMember,
  buildInitiativeRole,
  buildPage,
  buildUser,
  buildUserSummary,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeMemberRead, InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from "@/lib/mascotToast";

import { MembersPage } from "./MembersPage";

const INITIATIVE_ID = 7;
const MANAGER_ID = 42;

/** The auto-join switch, when the reader is offered one at all. */
const AUTO_JOIN_LABEL = "Add every new community member automatically";
const autoJoinSwitch = () => screen.queryByLabelText(AUTO_JOIN_LABEL);

/** Records what each PATCH actually sent, so a save can be read field by field.
 *  `members` is the roster page the table reads beside the row. */
function stubInitiative(
  {
    members = [],
    ...overrides
  }: Partial<InitiativeRead> & { members?: InitiativeMemberRead[] } = {},
  patchFails?: [number, string]
) {
  const patches: unknown[] = [];
  server.use(
    communityHttp.get("/initiatives/:id/members", () => HttpResponse.json(buildPage(members))),
    communityHttp.get("/initiatives/:id", () =>
      HttpResponse.json(
        buildInitiative({
          id: INITIATIVE_ID,
          name: "Apollo",
          // Everyone these tests sign in as manages it: an admin, or a member
          // holding the manager role.
          can: initiativeCan({ manage: true }),
          ...overrides,
        })
      )
    ),
    communityHttp.get("/initiatives/:id/roles", () => HttpResponse.json([])),
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

/** A membership that makes the signed-in user a manager of the initiative —
 *  the standing that reaches these settings without being a community admin. */
const managerMembership = () =>
  buildInitiativeMember({ user: buildUserSummary({ id: MANAGER_ID }), is_manager: true });

const renderMembers = (role: "admin" | "member" = "admin") =>
  renderPage(MembersPage, {
    auth: { user: buildUser({ id: MANAGER_ID }) },
    communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1, role }) },
    initialRoute: "/c/$communityId/i/$initiativeId/settings/members",
    routeParams: { communityId: "1", initiativeId: String(INITIATIVE_ID) },
  });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MembersPage", () => {
  it("puts joining above the roster it fills", async () => {
    stubInitiative();

    renderMembers();

    // Both on one screen, the door first.
    const joining = await screen.findByText("Joining");
    const members = screen.getByText("Members");
    expect(joining.compareDocumentPosition(members)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("offers every way into an initiative", async () => {
    stubInitiative();

    renderMembers();

    expect(await screen.findByRole("radio", { name: /Invite only/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /By request/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Anyone can join/ })).toBeInTheDocument();
  });

  it("saves the chosen policy on its own, touching no other field", async () => {
    const patches = stubInitiative();

    renderMembers();

    await userEvent.click(await screen.findByRole("radio", { name: /Anyone can join/ }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ join_policy: "open" });
  });

  it("saves the by-request policy", async () => {
    const patches = stubInitiative();

    renderMembers();

    await userEvent.click(await screen.findByRole("radio", { name: /By request/ }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ join_policy: "request" });
  });

  it("shows the initiative's current policy as the chosen one", async () => {
    stubInitiative({ join_policy: "request" });

    renderMembers();

    expect(await screen.findByRole("radio", { name: /By request/ })).toBeChecked();
  });

  it("finds someone to add by searching the community, and seats an admin as moderator", async () => {
    stubInitiative({ members: [managerMembership()] });
    const searches: (string | null)[] = [];
    const added: unknown[] = [];
    // Bo is in the community and already in the initiative, which the picker
    // asks of the initiative by id rather than reading its whole roster.
    const lookedUp: string[][] = [];
    server.use(
      communityHttp.get("/initiatives/:id/members/search", ({ request }) => {
        const ids = new URL(request.url).searchParams.getAll("user_id");
        lookedUp.push(ids);
        return HttpResponse.json(
          buildPage(
            ids.includes("56") ? [buildUserSummary({ id: 56, display_name: "Bo Member" })] : []
          )
        );
      }),
      communityHttp.get("/initiatives/:id/roles", () =>
        HttpResponse.json([
          buildInitiativeRole({ id: 20, name: "member", display_name: "Member" }),
          buildInitiativeRole({
            id: 21,
            name: "moderator",
            display_name: "Moderator",
            is_manager: true,
          }),
        ])
      ),
      communityHttp.get("/users/search", ({ request }) => {
        searches.push(new URL(request.url).searchParams.get("search"));
        return HttpResponse.json(
          buildPage([
            buildUserSummary({ id: 55, display_name: "Ada Admin", community_role: "admin" }),
            buildUserSummary({ id: 56, display_name: "Bo Member" }),
          ])
        );
      }),
      communityHttp.post("/initiatives/:id/members", async ({ request }) => {
        added.push(await request.json());
        return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID }));
      })
    );

    renderMembers();

    await userEvent.click(await screen.findByRole("combobox", { name: "Select user" }));
    await userEvent.type(screen.getByPlaceholderText("Search"), "ada");
    // The community is asked for what was typed, once the picker's debounce
    // has let it through.
    await waitFor(() => expect(searches).toContain("ada"));
    await waitFor(() => expect(lookedUp).toContainEqual(["55", "56"]));
    await waitFor(() =>
      expect(screen.queryByRole("option", { name: "Bo Member" })).not.toBeInTheDocument()
    );
    await userEvent.click(await screen.findByRole("option", { name: "Ada Admin" }));
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    // Its admin lands on the moderator role whatever the role select held.
    await waitFor(() => expect(added).toEqual([{ user_id: 55, role_id: 21 }]));
  });

  /**
   * Auto-join enrols every future community member on arrival. It is a community
   * admin's decision, and the server holds it to a single pair — auto-join with
   * "anyone can join" — so the interesting cases are all about who is offered
   * it, and about never assembling a combination the server would refuse.
   */
  describe("auto-join", () => {
    it("offers the switch to a community admin on an open initiative", async () => {
      stubInitiative({ join_policy: "open" });

      renderMembers();

      expect(await screen.findByLabelText(AUTO_JOIN_LABEL)).toBeEnabled();
    });

    it("says people already in the community are not swept in", async () => {
      stubInitiative({ join_policy: "open" });

      renderMembers();

      expect(
        await screen.findByText(/People already in the community are not added/)
      ).toBeVisible();
    });

    it("will not let a closed initiative enrol anyone, and says why", async () => {
      stubInitiative({ join_policy: "private" });

      renderMembers();

      await screen.findByRole("radio", { name: /Invite only/ });
      expect(autoJoinSwitch()).toBeDisabled();
      expect(screen.getByText(/needs the “Anyone can join” policy/)).toBeVisible();
    });

    it("will not let a by-request initiative enrol anyone either", async () => {
      stubInitiative({ join_policy: "request" });

      renderMembers();

      await screen.findByRole("radio", { name: /By request/ });
      expect(autoJoinSwitch()).toBeDisabled();
    });

    it("is not offered to a manager who is not a community admin", async () => {
      stubInitiative({ join_policy: "open", members: [managerMembership()] });

      // A manager reaches these settings and may set the policy — but the
      // server refuses `auto_join` from them, so the switch is simply absent.
      renderMembers("member");

      expect(await screen.findByRole("radio", { name: /Anyone can join/ })).toBeInTheDocument();
      expect(autoJoinSwitch()).not.toBeInTheDocument();
    });

    it("saves the switch on its own, touching no other field", async () => {
      const patches = stubInitiative({ join_policy: "open" });

      renderMembers();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ auto_join: true });
    });

    it("turns it back off", async () => {
      const patches = stubInitiative({ join_policy: "open", auto_join: true });

      renderMembers();

      expect(await screen.findByLabelText(AUTO_JOIN_LABEL)).toBeChecked();
      await userEvent.click(screen.getByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ auto_join: false });
    });

    it("closing the initiative clears auto-join in the same save", async () => {
      const patches = stubInitiative({ join_policy: "open", auto_join: true });

      renderMembers();

      await userEvent.click(await screen.findByRole("radio", { name: /Invite only/ }));

      // Sent as one request rather than a policy change the server would refuse.
      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ join_policy: "private", auto_join: false });
      await waitFor(() =>
        expect(toast.info).toHaveBeenCalledWith(
          "Auto-join is off — it is only available while anyone can join."
        )
      );
    });

    it("locks the closed policies for a manager who cannot clear auto-join", async () => {
      stubInitiative({ join_policy: "open", auto_join: true, members: [managerMembership()] });

      renderMembers("member");

      expect(await screen.findByRole("radio", { name: /Anyone can join/ })).toBeEnabled();
      expect(screen.getByRole("radio", { name: /Invite only/ })).toBeDisabled();
      expect(screen.getByRole("radio", { name: /By request/ })).toBeDisabled();
      expect(screen.getByText(/Ask an admin to turn auto-join off/)).toBeVisible();
    });

    it("reports the server's refusal of a non-admin in the server's words", async () => {
      stubInitiative({ join_policy: "open" }, [403, "INITIATIVE_AUTO_JOIN_ADMIN_ONLY"]);

      renderMembers();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Only community admins can change auto-join")
      );
    });

    it("reports the server's refusal of a closed initiative", async () => {
      stubInitiative({ join_policy: "open" }, [400, "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"]);

      renderMembers();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Auto-join is only available for initiatives anyone can join"
        )
      );
    });
  });
});
