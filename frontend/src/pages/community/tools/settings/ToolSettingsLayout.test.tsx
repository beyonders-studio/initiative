import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ownerCan, readerCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { type ToolSettingsEntity, ToolSettingsLayout } from "./ToolSettingsLayout";

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

/** The settings frame at one of its section addresses. */
const renderLayout = ({
  entity = buildEntity(),
  path = "",
  extraTabs,
}: {
  entity?: ToolSettingsEntity;
  path?: string;
  extraTabs?: { value: string; label: string }[];
} = {}) =>
  renderPage(
    () => (
      <ToolSettingsLayout
        tool={Tool.counter_group}
        entity={entity}
        isLoading={false}
        isError={false}
        setGrants={noopMutation()}
        remove={noopMutation()}
        extraTabs={extraTabs}
      />
    ),
    {
      initialRoute: `/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings${path}`,
      routeParams: { communityId: "1", initiativeId: "3", counterGroupId: "7" },
    }
  );

describe("ToolSettingsLayout", () => {
  it("names every section as a tab", async () => {
    renderLayout();

    for (const label of ["Details", "Access", "Advanced"]) {
      expect(await screen.findByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("navigates to the section a tab names", async () => {
    const { router } = renderLayout();

    await userEvent.click(await screen.findByRole("tab", { name: "Access" }));

    // The section is an address, not a piece of component state.
    expect(router.state.location.pathname).toBe("/c/1/i/3/counter-groups/7/settings/access");
  });

  it("lights the tab the address names", async () => {
    renderLayout({ path: "/advanced" });

    expect(await screen.findByRole("tab", { name: "Advanced" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("opens on Details, which is the settings address itself", async () => {
    renderLayout();

    expect(await screen.findByRole("tab", { name: "Details" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("keeps the access tab out of the bar for a reader who may not share", async () => {
    renderLayout({ entity: buildEntity({ can: readerCan() }) });

    expect(await screen.findByRole("tab", { name: "Details" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Access" })).not.toBeInTheDocument();
  });

  it("keeps the advanced tab out of the bar when it would hold nothing", async () => {
    // Advanced is a tool's extra operations plus deletion. A reader of a tool
    // that declares neither has no advanced section to visit.
    renderLayout({ entity: buildEntity({ can: readerCan() }) });

    expect(await screen.findByRole("tab", { name: "Details" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Advanced" })).not.toBeInTheDocument();
  });

  it("gives a tool's own section a route beside the shared ones", async () => {
    const { router } = renderLayout({
      extraTabs: [{ value: "task-statuses", label: "Task statuses" }],
    });

    await userEvent.click(await screen.findByRole("tab", { name: "Task statuses" }));

    expect(router.state.location.pathname).toBe("/c/1/i/3/counter-groups/7/settings/task-statuses");
  });

  it("addresses a community-level entity at its community route", async () => {
    renderPage(
      () => (
        <ToolSettingsLayout
          tool={Tool.calendar}
          entity={buildEntity({ initiative_id: null })}
          isLoading={false}
          isError={false}
          setGrants={noopMutation()}
          remove={noopMutation()}
        />
      ),
      {
        initialRoute: "/c/$communityId/calendars/$calendarId/settings",
        routeParams: { communityId: "1", calendarId: "7" },
      }
    );

    expect(await screen.findByRole("tab", { name: "Details" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
});
