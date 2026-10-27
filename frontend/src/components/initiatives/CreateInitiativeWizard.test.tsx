/**
 * The wizard is the first thing most people do in a community, so what it
 * refuses to let them build matters as much as what it sends.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { CreateInitiativeWizard } from "./CreateInitiativeWizard";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

/** Captures the create payload, and the role PATCHes that follow it — with
 *  the initiative id each one was addressed to, because sending them to the
 *  wrong initiative is the failure mode a wildcard route would hide. */
function stubCreate() {
  const created: Record<string, unknown>[] = [];
  const rolePatches: Record<string, unknown>[] = [];
  const patchedInitiatives: string[] = [];
  server.use(
    communityHttp.post("/initiatives/", async ({ request }) => {
      created.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(buildInitiative({ id: 7, name: "Apollo" }), { status: 201 });
    }),
    communityHttp.get("/initiatives/:id/roles", ({ params }) =>
      // A roles lookup against an initiative that is not the one just created
      // is the bug, so answer it the way the server would: with nothing.
      String(params.id) === "7"
        ? HttpResponse.json([
            {
              id: 1,
              name: "moderator",
              display_name: "Moderator",
              is_manager: true,
              permissions: {},
            },
            { id: 2, name: "member", display_name: "Member", is_manager: false, permissions: {} },
          ])
        : new HttpResponse(null, { status: 404 })
    ),
    communityHttp.patch("/initiatives/:id/roles/:roleId", async ({ request, params }) => {
      patchedInitiatives.push(String(params.id));
      rolePatches.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ id: 2 });
    })
  );
  return { created, rolePatches, patchedInitiatives };
}

const renderWizard = () =>
  renderPage(() => <CreateInitiativeWizard open onOpenChange={() => {}} />, {
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin" }),
    },
  });

const nameIt = async (name = "Apollo") => {
  await userEvent.type(await screen.findByLabelText(/name/i), name);
  await userEvent.click(screen.getByRole("button", { name: "Next: Tools" }));
};

describe("CreateInitiativeWizard", () => {
  it("will not move past a nameless initiative", async () => {
    stubCreate();
    renderWizard();

    // The name is the one thing with no sensible default, so the step holds.
    expect(await screen.findByRole("button", { name: "Next: Tools" })).toBeDisabled();
  });

  it("refuses an initiative with nothing in it, and says why", async () => {
    stubCreate();
    renderWizard();
    await nameIt();

    // Projects and files start ticked; turning both off leaves nowhere to
    // put anything, which is the one combination the wizard will not build.
    await userEvent.click(await screen.findByRole("switch", { name: /Projects/ }));
    await userEvent.click(screen.getByRole("switch", { name: /Files/ }));

    expect(screen.getByRole("button", { name: "Next: Membership" })).toBeDisabled();
    expect(screen.getByText(/needs somewhere to put things/i)).toBeInTheDocument();
  });

  it("sends exactly the tools that were ticked", async () => {
    const { created } = stubCreate();
    renderWizard();
    await nameIt();

    // Add a calendar to the two that start on.
    await userEvent.click(await screen.findByRole("switch", { name: /Calendar/ }));
    await userEvent.click(screen.getByRole("button", { name: "Next: Membership" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next: Permissions" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create initiative" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      name: "Apollo",
      projects_enabled: true,
      files_enabled: true,
      calendars_enabled: true,
      queues_enabled: false,
    });
  });

  it("lets ordinary members see the tools it just switched on, by default", async () => {
    const { rolePatches } = stubCreate();
    renderWizard();
    await nameIt();
    await userEvent.click(await screen.findByRole("switch", { name: /Calendar/ }));
    await userEvent.click(screen.getByRole("button", { name: "Next: Membership" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next: Permissions" }));

    // "See things" is what the built-in member role already is, so it is the
    // answer the wizard starts on.
    expect(await screen.findByRole("radio", { name: /See things/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Create initiative" }));

    // Without this the calendar is on for managers and invisible to everybody
    // else — the whole reason the step exists. Managers are skipped: they hold
    // every permission by construction. Viewing only: no create_* is written.
    await waitFor(() => expect(rolePatches).toHaveLength(1));
    expect(rolePatches[0]).toMatchObject({
      permissions: {
        calendars_enabled: true,
        projects_enabled: true,
        // Seeing, not making: the create rights are written off rather than
        // left unsaid, so the answer holds whatever the role arrived with.
        create_calendars: false,
        create_projects: false,
      },
    });
  });

  it("lets members make things when asked to", async () => {
    const { rolePatches } = stubCreate();
    renderWizard();
    await nameIt();
    await userEvent.click(await screen.findByRole("switch", { name: /Calendar/ }));
    await userEvent.click(screen.getByRole("button", { name: "Next: Membership" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next: Permissions" }));
    await userEvent.click(await screen.findByRole("radio", { name: /Make things/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create initiative" }));

    await waitFor(() => expect(rolePatches).toHaveLength(1));
    expect(rolePatches[0]).toMatchObject({
      permissions: {
        calendars_enabled: true,
        create_calendars: true,
        projects_enabled: true,
        create_projects: true,
      },
    });
  });

  it("takes projects and files back off members for managers only", async () => {
    const { rolePatches } = stubCreate();
    renderWizard();
    await nameIt();
    await userEvent.click(await screen.findByRole("button", { name: "Next: Membership" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next: Permissions" }));
    await userEvent.click(await screen.findByRole("radio", { name: /Managers only/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create initiative" }));

    // "Managers only" is a revoke, not a no-op: the built-in member role
    // arrives already holding projects and files, so writing nothing would
    // leave members able to see exactly what this answer says they cannot.
    await waitFor(() => expect(rolePatches).toHaveLength(1));
    expect(rolePatches[0]).toMatchObject({
      permissions: {
        projects_enabled: false,
        files_enabled: false,
        create_projects: false,
        create_files: false,
      },
    });
  });

  it("addresses the permissions to the initiative it just created", async () => {
    const { patchedInitiatives } = stubCreate();
    renderWizard();
    await nameIt();
    await userEvent.click(await screen.findByRole("button", { name: "Next: Membership" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next: Permissions" }));
    await userEvent.click(screen.getByRole("button", { name: "Create initiative" }));

    // The id only exists once the create resolves. Reading it from state would
    // send every write to the initiative that state held a render ago — none.
    await waitFor(() => expect(patchedInitiatives).toEqual(["7"]));
  });

  it("explains what an initiative is when it is the community's first", async () => {
    stubCreate();
    renderPage(() => <CreateInitiativeWizard open isFirst onOpenChange={() => {}} />, {
      communities: {
        activeCommunityId: 1,
        activeCommunity: buildCommunity({ id: 1, role: "admin" }),
      },
    });

    expect(await screen.findByText("Your first initiative")).toBeInTheDocument();
    expect(screen.getByText(/a folder for one big effort or team/)).toBeInTheDocument();
    // The docs open in their own tab: the wizard is half-filled by this point.
    const more = screen.getByRole("link", { name: "Read more here" });
    expect(more).toHaveAttribute("target", "_blank");
    expect(more).toHaveAttribute(
      "href",
      "https://beyonders-studio.github.io/initiative/en/guides/initiatives/"
    );
  });

  it("says nothing of the sort once the community has one", async () => {
    stubCreate();
    renderWizard();

    await screen.findByLabelText(/name/i);
    expect(screen.queryByText("Your first initiative")).not.toBeInTheDocument();
  });

  it("lets a step be taken back without losing the answer before it", async () => {
    stubCreate();
    renderWizard();
    await nameIt("Gemini");

    await userEvent.click(await screen.findByRole("button", { name: "Back" }));

    expect(await screen.findByLabelText(/name/i)).toHaveValue("Gemini");
  });
});
