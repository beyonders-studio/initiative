import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ownerCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsProvider } from "@/components/tools/settings/ToolSettingsContext";

import { ToolExportCard } from "./ToolExportCard";

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

const renderCard = (tool: Tool) =>
  renderWithProviders(
    <ToolSettingsProvider
      value={{
        tool,
        entity: {
          id: 3,
          name: "Barovia",
          initiative_id: 1,
          can: ownerCan(),
          tags: [],
          grants: [],
          comments_enabled: true,
          archived_at: null,
        },
        setGrants: noopMutation(),
        remove: noopMutation(),
      }}
    >
      <ToolExportCard />
    </ToolSettingsProvider>
  );

describe("ToolExportCard", () => {
  it("opens the export wizard on the tool's one format, with nothing to choose", async () => {
    renderCard(Tool.dashboard);

    await userEvent.click(await screen.findByRole("button", { name: "Export" }));

    expect(await screen.findByText("Importable file (.json)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start export/i })).toBeInTheDocument();
  });

  it("says a wiki's every download is a zip", async () => {
    renderCard(Tool.wiki);

    await userEvent.click(await screen.findByRole("button", { name: "Export" }));

    for (const name of ["PDF (.zip)", "Markdown (.zip)", "Word (.zip)", "Importable file (.zip)"]) {
      expect(await screen.findByRole("button", { name })).toBeInTheDocument();
    }
  });
});
