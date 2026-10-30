/**
 * Community settings › Roles: the community's custom roles, and the form that
 * adds one.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { AdminSurface, type CustomRoleCreate } from "@/api/generated/initiativeAPI.schemas";
import { toast } from "@/lib/mascotToast";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { SettingsCommunityRolesPage } from "./SettingsCommunityRolesPage";

const setup = () => {
  const community = buildCommunity({ role: "admin" });
  renderPage(() => <SettingsCommunityRolesPage />, {
    communities: {
      communities: [community],
      activeCommunityId: community.id,
      activeCommunity: community,
    },
  });
};

/** Open the form, name the role, and tick every part it offers. */
const fillNewRole = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("button", { name: "Add role" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Name"), "Greeter");
  const offered = within(dialog).getAllByRole("checkbox");
  for (const box of offered) await user.click(box);
  return { dialog, offered };
};

describe("SettingsCommunityRolesPage", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockReset();
    // An admin with no custom role holds every part.
    server.use(
      communityHttp.get("/custom-roles/held", () =>
        HttpResponse.json({ surfaces: Object.values(AdminSurface) })
      )
    );
  });

  it("says when the community has no roles, beside the way to add one", async () => {
    setup();

    expect(await screen.findByText("This community has no custom roles.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add role" })).toBeInTheDocument();
  });

  it("makes a role for members holding only what a member may hold", async () => {
    const sent: CustomRoleCreate[] = [];
    server.use(
      communityHttp.post("/custom-roles/", async ({ request }) => {
        const body = (await request.json()) as CustomRoleCreate;
        sent.push(body);
        return HttpResponse.json({ id: 1, ...body }, { status: 201 });
      })
    );
    const user = userEvent.setup();
    setup();

    const { dialog, offered } = await fillNewRole(user);
    expect(offered).toHaveLength(5);
    await user.click(within(dialog).getByRole("button", { name: "Add role" }));

    await waitFor(() =>
      expect(sent).toEqual([
        {
          name: "Greeter",
          base_rung: "member",
          surfaces: ["profile", "invites", "members", "community_calendars", "usage"],
        },
      ])
    );
  });

  it("says why the server refused a role beyond the reader's own", async () => {
    server.use(
      communityHttp.post("/custom-roles/", () =>
        HttpResponse.json({ detail: "CUSTOM_ROLE_BEYOND_YOURS" }, { status: 403 })
      )
    );
    const user = userEvent.setup();
    setup();

    const { dialog } = await fillNewRole(user);
    await user.click(within(dialog).getByRole("button", { name: "Add role" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "You can only make or give a role with what you can do yourself."
      )
    );
  });

  it("offers only the changes the server would make", async () => {
    // An admin a custom role narrows to the roster and the roles.
    server.use(
      communityHttp.get("/custom-roles/held", () =>
        HttpResponse.json({ surfaces: ["members", "roles"] })
      ),
      communityHttp.get("/custom-roles/", () =>
        HttpResponse.json([
          { id: 1, name: "Doors", base_rung: "member", surfaces: ["invites"] },
          { id: 2, name: "Roll", base_rung: "admin", surfaces: ["members"] },
        ])
      )
    );
    setup();

    expect(
      await screen.findByText("You can't change this role: it holds something you don't.")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Only an admin who holds everything can delete an admin role: its holders get everything back."
      )
    ).toBeInTheDocument();
    // Doors holds what the reader lacks, so it has no actions; Roll does.
    expect(screen.getAllByRole("button", { name: /Roll|Doors/ })).toHaveLength(1);
  });
});
