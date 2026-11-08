/**
 * What a refetch is allowed to do to a form somebody is typing in.
 *
 * These settings fill themselves in from the entity the frame loaded, and used
 * to refill whenever a fresh copy of it arrived. That happens for reasons that
 * have nothing to do with the reader — a realtime signal about the thing being
 * edited, a window brought back to the front, another query's mutation — so it
 * landed on half-written text and replaced it. Handing the section a changed
 * entity is exactly what those refetches do.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ownerCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "@/pages/community/tools/settings/ToolSettingsContext";

import { DetailsPage } from "./DetailsPage";

vi.mock("@/components/tags", () => ({
  TagPicker: () => <div data-testid="tag-picker" />,
}));

const buildEntity = (overrides: Partial<ToolSettingsEntity> = {}): ToolSettingsEntity => ({
  id: 7,
  name: "Q3 Roadmap",
  description: "A description",
  initiative_id: 3,
  can: ownerCan(),
  tags: [],
  grants: [],
  comments_enabled: true,
  archived_at: null,
  ...overrides,
});

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

/**
 * The section mounted the way its route mounts it, with a button standing in
 * for the moment a fresh copy of the entity arrives.
 */
const renderSection = (arrived: ToolSettingsEntity) => {
  const Harness = () => {
    const [entity, setEntity] = useState(buildEntity());
    return (
      <>
        <button type="button" onClick={() => setEntity(arrived)}>
          refetch
        </button>
        <ToolSettingsProvider
          value={{
            tool: Tool.counter_group,
            entity,
            update: noopMutation(),
            setGrants: noopMutation(),
            remove: noopMutation(),
          }}
        >
          <DetailsPage />
        </ToolSettingsProvider>
      </>
    );
  };
  return renderPage(Harness);
};

describe("a settings form during a background refetch", () => {
  it("keeps what has been typed when a fresh copy of the entity arrives", async () => {
    // Somebody else moved something about this group meanwhile — a comment
    // switch, a rename, anything the read schema carries.
    renderSection(buildEntity({ name: "Renamed by somebody else" }));
    const user = userEvent.setup();

    await user.clear(await screen.findByLabelText(/name/i));
    await user.type(screen.getByLabelText(/name/i), "Half-written name");
    await user.click(screen.getByRole("button", { name: "refetch" }));

    await waitFor(() => expect(screen.getByLabelText(/name/i)).toHaveValue("Half-written name"));
  });

  it("catches up with a rename while nobody is typing", async () => {
    renderSection(buildEntity({ name: "Renamed by somebody else" }));
    const user = userEvent.setup();
    expect(await screen.findByLabelText(/name/i)).toHaveValue("Q3 Roadmap");

    await user.click(screen.getByRole("button", { name: "refetch" }));

    await waitFor(() =>
      expect(screen.getByLabelText(/name/i)).toHaveValue("Renamed by somebody else")
    );
  });
});
