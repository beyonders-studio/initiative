import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildCommunity,
  buildFileSummary,
  buildInitiative,
  buildProject,
  buildUser,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { queryClient } from "@/lib/queryClient";

import { MyToolsPage } from "./MyToolsPage";

const READER = buildUser({ id: 42 });

const HOME = buildCommunity({ id: 1, name: "Ravenloft" });
const AWAY = buildCommunity({ id: 2, name: "Barovia" });

const page = (items: unknown[], totalCount = items.length) =>
  HttpResponse.json({
    items,
    total_count: totalCount,
    page: 1,
    page_size: 20,
    has_next: false,
  });

/** Every tool answers through the same envelope, so one shape covers all six. */
function stubMyTools({
  counts = {},
  projects = [],
  files = [],
}: {
  counts?: Record<string, number>;
  projects?: unknown[];
  files?: unknown[];
} = {}) {
  server.use(
    http.get("/api/v1/me/tools/counts", () =>
      HttpResponse.json({
        counts: {
          project: 0,
          file: 0,
          counter_group: 0,
          calendar: 0,
          dashboard: 0,
          ...counts,
        },
      })
    ),
    http.get("/api/v1/me/projects", () => page(projects)),
    http.get("/api/v1/me/files", () => page(files)),
    http.get("/api/v1/me/counter-groups", () => page([])),
    http.get("/api/v1/me/calendars", () => page([])),
    http.get("/api/v1/me/dashboards", () => page([])),
    communityHttp.get("/initiatives/", () => HttpResponse.json([]))
  );
}

const render = (search?: Record<string, unknown>, communities = [HOME]) =>
  renderPage(MyToolsPage, {
    auth: { user: READER },
    communities: { communities, activeCommunityId: HOME.id, activeCommunity: HOME },
    initialRoute: "/my-tools",
    routerSearch: search,
  });

describe("MyToolsPage", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("offers a tab only for the tools the reader has something of", async () => {
    stubMyTools({
      counts: { project: 3, file: 1 },
      projects: [buildProject({ name: "Apollo", community_id: HOME.id })],
    });

    render();

    expect(await screen.findByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Files" })).toBeInTheDocument();
    // Nothing in any of these anywhere, so no tab onto an empty table.
    expect(screen.queryByRole("link", { name: "Calendars" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboards" })).not.toBeInTheDocument();
  });

  it("says there is nothing to browse when no tool has anything behind it", async () => {
    stubMyTools();

    render();

    expect(await screen.findByText("Nothing to browse yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("addresses each row in its own community", async () => {
    stubMyTools({
      counts: { file: 2 },
      files: [buildFileSummary({ id: 5, name: "Campaign notes", community_id: AWAY.id })],
    });

    render({ tool: "files" }, [HOME, AWAY]);

    const link = await screen.findByRole("link", { name: "Campaign notes" });
    // The reader is standing in community 1; the row lives in community 2 and says so.
    expect(link).toHaveAttribute("href", expect.stringContaining("/c/2/"));
    expect(screen.getByRole("link", { name: "Barovia" })).toBeInTheDocument();
  });

  it("switches the whole view to what the reader made", async () => {
    let lastCreatedByMe: string | null = null;
    stubMyTools({ counts: { file: 1 }, files: [buildFileSummary({ name: "Standup" })] });
    server.use(
      http.get("/api/v1/me/files", ({ request }) => {
        lastCreatedByMe = new URL(request.url).searchParams.get("created_by_me");
        return page([buildFileSummary({ name: "Standup" })]);
      })
    );

    render({ tool: "files" });
    await screen.findByRole("link", { name: "Standup" });
    expect(lastCreatedByMe).toBeNull();

    await userEvent.click(screen.getByRole("radio", { name: "Made by me" }));

    await waitFor(() => expect(lastCreatedByMe).toBe("true"));
    expect(screen.getByRole("radio", { name: "Made by me" })).toHaveAttribute("data-state", "on");
  });

  it("narrows the list to the chosen communities", async () => {
    let lastCommunityIds: string[] = [];
    stubMyTools({ counts: { project: 1 } });
    server.use(
      http.get("/api/v1/me/projects", ({ request }) => {
        lastCommunityIds = new URL(request.url).searchParams.getAll("community_ids");
        return page([buildProject({ name: "Apollo", community_id: AWAY.id })]);
      })
    );

    render({ tool: "projects", communities: String(AWAY.id) }, [HOME, AWAY]);

    await screen.findByRole("link", { name: "Apollo" });
    await waitFor(() => expect(lastCommunityIds).toEqual([String(AWAY.id)]));
  });

  it("names each row's initiative, wherever it lives", async () => {
    stubMyTools({
      counts: { project: 1 },
      projects: [buildProject({ name: "Apollo", community_id: AWAY.id, initiative_id: 9 })],
    });
    server.use(
      communityHttp.get("/initiatives/", ({ params }) =>
        HttpResponse.json(
          Number(params.communityId) === AWAY.id
            ? [buildInitiative({ id: 9, name: "Mists", community_id: AWAY.id })]
            : []
        )
      )
    );

    render({ tool: "projects" }, [HOME, AWAY]);

    expect(await screen.findByRole("link", { name: "Mists" })).toBeInTheDocument();
  });
});
