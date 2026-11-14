import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative, initiativeCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { SettingsLayout } from "./SettingsLayout";

const INITIATIVE_ID = 7;

/** The initiative, saying whether this reader may run it. */
function stubInitiative(manage: boolean) {
  server.use(
    communityHttp.get("/initiatives/:id", () =>
      HttpResponse.json(
        buildInitiative({ id: INITIATIVE_ID, name: "Apollo", can: initiativeCan({ manage }) })
      )
    )
  );
}

/** The settings frame, for a reader with the given standing. */
const renderLayout = ({
  role = "admin",
  user,
}: {
  role?: "admin" | "member";
  user?: UserRead;
} = {}) =>
  renderPage(SettingsLayout, {
    communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1, role }) },
    initialRoute: "/c/$communityId/i/$initiativeId/settings",
    routeParams: { communityId: "1", initiativeId: String(INITIATIVE_ID) },
    ...(user ? { auth: { user } } : {}),
  });

/**
 * How the bar itself behaves — naming every section, navigating to the one a
 * tab names, lighting the one the address names — is the shared
 * `SettingsTabsNav`, proved once in
 * `src/pages/community/tools/settings/ToolSettingsLayout.test.tsx`. What is left
 * here is who gets a bar at all, which only this layout decides.
 */
describe("SettingsLayout", () => {
  it("keeps the export tab out of the bar for someone who may not export", async () => {
    // A plain community member who manages nothing here: the layout still refuses
    // the whole surface, so no section is offered at all.
    stubInitiative(false);

    renderLayout({ role: "member" });

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Export" })).not.toBeInTheDocument();
  });

  it("lets an initiative manager who is no community admin in", async () => {
    stubInitiative(true);

    renderLayout({ role: "member" });

    expect(await screen.findByRole("tab", { name: "Members" })).toBeInTheDocument();
  });

  it("says so when the initiative isn't one this reader can see", async () => {
    server.use(
      communityHttp.get("/initiatives/:id", () => new HttpResponse(null, { status: 404 }))
    );

    renderLayout();

    expect(await screen.findByText("Initiative not found")).toBeInTheDocument();
  });
});
