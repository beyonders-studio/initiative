/**
 * The active tool tab is a path segment, not component state — that is what
 * makes it shareable, survive a reload, and answer the back button. These tests
 * pin the mapping from route to tab, including the two fallbacks that keep a
 * stale link from dead-ending.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildCommunity,
  buildInitiative,
  buildToolPlugin,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { InitiativePage } from "./InitiativePage";

const INITIATIVE_ID = 7;

const page = () =>
  HttpResponse.json({ items: [], total_count: 0, page: 1, page_size: 20, has_next: false });

/** Every tool list answers the same envelope; the tabs only need it to be empty. */
const VIEWABLE = [Tool.project, Tool.file, Tool.dashboard, Tool.calendar, Tool.wiki];

function stubEverything(hidden: Tool[] = [], roster = true) {
  server.use(
    communityHttp.get("/initiatives/:id", ({ params }) =>
      HttpResponse.json(
        buildInitiative({
          id: Number(params.id),
          name: "Apollo",
          member_count: 4,
          role_display_name: "Project Manager",
          tools: { dashboard: true, calendar: true, wiki: true },
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
    communityHttp.get("/wikis/", page),
    communityHttp.get("/calendars/", page),
    communityHttp.get("/dashboards/", page)
  );
}

const renderAt = (tool?: string) =>
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

  describe("a tool plug-in's tab", () => {
    const shelf = `shelf.${TOOL_PLUGIN_UID.toLowerCase()}`;
    let name = "Apollo";

    const stubShelf = (plugins: () => Response) => {
      name = "Apollo";
      server.use(
        communityHttp.get("/initiatives/:id", ({ params }) =>
          HttpResponse.json(
            buildInitiative({
              id: Number(params.id),
              name,
              can: {
                manage: false,
                moderate: false,
                roster: true,
                view: [Tool.project, shelf],
                create: [shelf],
              },
            })
          )
        ),
        communityHttp.get("/projects/", page),
        communityHttp.get("/plugins/", plugins),
        communityHttp.get(`/plugin-tools/${shelf}/`, page)
      );
    };

    it("keeps an open add dialog and its draft when the initiative refreshes", async () => {
      stubShelf(() => HttpResponse.json({ items: [buildToolPlugin()] }));
      const { queryClient } = renderAt(shelf);
      const user = userEvent.setup();

      await user.click(await screen.findByRole("button", { name: "New Shelf" }));
      const field = await screen.findByRole("textbox", { name: "Name" });
      await user.type(field, "Novels");
      name = "Apollo II";
      await queryClient.invalidateQueries();

      // The page behind the dialog is hidden from the accessibility tree.
      expect(await screen.findByText("Apollo II")).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Novels");
    });

    it("picks no tab until the installs are read", async () => {
      let release: () => void = () => {};
      const read = new Promise<void>((resolve) => {
        release = resolve;
      });
      stubShelf(() => HttpResponse.json({ items: [] }));
      server.use(
        communityHttp.get("/plugins/", async () => {
          await read;
          return HttpResponse.json({ items: [buildToolPlugin()] });
        })
      );
      renderAt(shelf);

      await waitFor(() => expect(screen.queryAllByRole("tab")).toHaveLength(0));
      release();
      await waitFor(() => expect(selectedTab()).toHaveTextContent("Reading"));
    });

    it("offers a retry rather than another tab when the installs can't be read", async () => {
      stubShelf(() => HttpResponse.json({ detail: "x" }, { status: 500 }));
      renderAt(shelf);

      expect(
        await screen.findByText("This community's tools couldn't be loaded.")
      ).toBeInTheDocument();
      expect(screen.queryAllByRole("tab")).toHaveLength(0);
    });
  });
});
