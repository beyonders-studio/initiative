/**
 * The active tool tab is a path segment, not component state — that is what
 * makes it shareable, survive a reload, and answer the back button. These tests
 * pin the mapping from route to tab, including the two fallbacks that keep a
 * stale link from dead-ending.
 */
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCommunity, buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { InitiativePage } from "./InitiativePage";

const INITIATIVE_ID = 7;

const page = () =>
  HttpResponse.json({ items: [], total_count: 0, page: 1, page_size: 20, has_next: false });

/** Every tool list answers the same envelope; the tabs only need it to be empty. */
const VIEWABLE = [Tool.project, Tool.file, Tool.dashboard, Tool.calendar, Tool.counter_group];

function stubEverything(hidden: Tool[] = [], roster = true) {
  server.use(
    communityHttp.get("/initiatives/:id", ({ params }) =>
      HttpResponse.json(
        buildInitiative({
          id: Number(params.id),
          name: "Apollo",
          member_count: 4,
          role_display_name: "Project Manager",
          dashboards_enabled: true,
          calendars_enabled: true,
          counter_groups_enabled: true,
          can: {
            manage: false,
            moderate: false,
            roster,
            view: VIEWABLE.filter((tool) => !hidden.includes(tool)),
            create: [],
          },
        })
      )
    ),
    communityHttp.get("/projects/", page),
    communityHttp.get("/files/", page),
    communityHttp.get("/counter-groups/", page),
    communityHttp.get("/calendars/", page),
    communityHttp.get("/dashboards/", page)
  );
}

const renderAt = (tool?: Tool) =>
  renderPage(() => <InitiativePage tool={tool} />, {
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin" }),
    },
    initialRoute: "/c/$communityId/i/$initiativeId",
    routeParams: { communityId: "1", initiativeId: String(INITIATIVE_ID) },
  });

/** Radix marks the selected trigger with aria-selected. */
const selectedTab = () =>
  screen.getAllByRole("tab").find((tab) => tab.getAttribute("aria-selected") === "true");

describe("InitiativePage", () => {
  it("heads the page with the headcount and the reader's own role", async () => {
    stubEverything();
    renderAt();

    expect((await screen.findAllByText("4 members")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Project Manager").length).toBeGreaterThan(0);
  });

  it("opens the roster from the headcount only for a reader who may read it", async () => {
    stubEverything();
    renderAt();
    expect(await screen.findByRole("button", { name: "4 members" })).toBeInTheDocument();
  });

  it("shows a guest given items the headcount and nobody in it", async () => {
    stubEverything([], false);
    renderAt();

    expect((await screen.findAllByText("4 members")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "4 members" })).not.toBeInTheDocument();
  });

  it("selects the tab the route names", async () => {
    stubEverything();
    renderAt(Tool.dashboard);

    expect(await screen.findByRole("tab", { name: "Dashboards" })).toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Dashboards");
  });

  it("falls back to the first tab when the route names none", async () => {
    stubEverything();
    renderAt();

    // The tabs follow the registry order, which opens with projects.
    expect(await screen.findByRole("tab", { name: "Projects" })).toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Projects");
  });

  // A permission change shouldn't dead-end a bookmark someone already has.
  it("falls back to the first available tab for a tool this member can't view", async () => {
    stubEverything([Tool.dashboard]);
    renderAt(Tool.dashboard);

    expect(await screen.findByRole("tab", { name: "Projects" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Dashboards" })).not.toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Projects");
  });

  it("links each tab at its own URL rather than swapping state", async () => {
    stubEverything();
    renderAt(Tool.file);

    const projectsTab = await screen.findByRole("tab", { name: "Projects" });
    expect(projectsTab).toHaveAttribute("href", `/c/1/i/${INITIATIVE_ID}/projects`);
  });
});
