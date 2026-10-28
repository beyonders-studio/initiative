import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildProject, buildPropertyDefinition, readerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { definitionsHandler } from "@/__tests__/helpers/handlers/property.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { ProjectRead, PropertyDefinitionCreate } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { ProjectSettingsMetadataPage } from "./ProjectSettingsMetadataPage";

/** The project's Metadata tab, for `project` (id 3), holding `metadata`. */
const open = (project: ProjectRead, metadata = [buildPropertyDefinition()]) => {
  server.use(
    communityHttp.get("/projects/:id", () => HttpResponse.json(project)),
    definitionsHandler([buildPropertyDefinition({ id: 90, name: "Initiative's own" })], {
      project: metadata,
    })
  );
  renderPage(ProjectSettingsMetadataPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/projects/$projectId/settings/metadata",
    routeParams: { communityId: "1", initiativeId: "1", projectId: "3" },
  });
  return userEvent.setup();
};

describe("ProjectSettingsMetadataPage", () => {
  it("lists the project's metadata, not the initiative's properties, and makes more", async () => {
    let created: PropertyDefinitionCreate | null = null;
    server.use(
      communityHttp.post("/property-definitions/", async ({ request }) => {
        created = (await request.json()) as PropertyDefinitionCreate;
        return HttpResponse.json(
          buildPropertyDefinition({ id: 12, name: created.name, project_id: 3 }),
          { status: 201 }
        );
      })
    );
    const user = open(buildProject({ id: 3, initiative_id: 1 }), [
      buildPropertyDefinition({ id: 11, name: "Sprint", project_id: 3 }),
    ]);

    expect(await screen.findByRole("cell", { name: "Sprint" })).toBeInTheDocument();
    expect(screen.queryByText("Initiative's own")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New metadata" }));
    const dialog = await screen.findByRole("dialog", { name: "New metadata" });
    await user.type(within(dialog).getByLabelText("Name"), "Estimate");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(created).toMatchObject({
        name: "Estimate",
        type: "text",
        initiative_id: 1,
        project_id: 3,
        // A new one goes last.
        position: 1,
      })
    );
  });

  it("only lists the metadata to someone who may not change the project's tasks", async () => {
    open(buildProject({ id: 3, initiative_id: 1, can: { ...readerCan(), configure: false } }), [
      buildPropertyDefinition({ id: 11, name: "Sprint", project_id: 3 }),
    ]);

    expect(await screen.findByRole("cell", { name: "Sprint" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New metadata" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit metadata" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete metadata" })).not.toBeInTheDocument();
  });
});
