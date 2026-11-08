/**
 * A tag's page lists everything carrying it, one tab per tool — a task under
 * the project tool it lives in, a wiki page under wikis. Each tab holds a
 * server-paged table of the tool's own rows and one per kind inside it, drawn
 * only where the tag's counts say there is something to list.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildPage,
  buildProject,
  buildTag,
  buildTaggedEntity,
  buildTask,
} from "@/__tests__/factories";
import { buildTaskListResponse } from "@/__tests__/factories/task.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";

import { TagPage } from "./TagPage";

const tag = buildTag({ id: 3, name: "Urgent" });

const wikiPage = buildTaggedEntity({
  entity_type: SearchEntityType.wiki_page,
  entity_id: 11,
  title: "Rota",
  initiative_id: 5,
  tool: Tool.wiki,
  tool_id: 4,
  tool_title: "Handbook",
});

/** The tag carries a project, a task in it and a wiki page; records what the
 *  lists were asked for. */
const serveTag = () => {
  const asked: { projects?: URLSearchParams; entities: URLSearchParams[] } = { entities: [] };
  server.use(
    communityHttp.get("/tags/:tagId", () => HttpResponse.json(tag)),
    communityHttp.get("/tags/:tagId/counts", () =>
      HttpResponse.json({ counts: { project: 1, task: 1, wiki_page: 1 } })
    ),
    communityHttp.get("/projects/", ({ request }) => {
      asked.projects = new URL(request.url).searchParams;
      return HttpResponse.json(
        buildPage([buildProject({ id: 7, name: "Rewiring", initiative_id: 5 })])
      );
    }),
    communityHttp.get("/tasks/", () =>
      HttpResponse.json(
        buildTaskListResponse([
          buildTask({ id: 9, title: "Wire the doorbell", project_id: 7, initiative_id: 5 }),
        ])
      )
    ),
    communityHttp.get("/tags/:tagId/entities", ({ request }) => {
      asked.entities.push(new URL(request.url).searchParams);
      return HttpResponse.json(buildPage([wikiPage]));
    })
  );
  return asked;
};

const renderTagPage = (routerSearch?: Record<string, string>) =>
  renderPage(TagPage, {
    initialRoute: "/c/$communityId/tags/$tagId",
    routeParams: { communityId: "1", tagId: String(tag.id) },
    routerSearch,
  });

describe("TagPage", () => {
  it("tabs each tool by what carries the tag in it, and tables its own rows and its tasks", async () => {
    const asked = serveTag();
    renderTagPage();

    expect(await screen.findByRole("tab", { name: /Projects \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Wikis \(1\)/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Documents/ })).not.toBeInTheDocument();

    const projects = await screen.findByRole("link", { name: /Rewiring/ });
    expect(projects).toHaveAttribute("href", "/c/1/i/5/projects/7");
    expect(asked.projects?.getAll("tag_ids")).toEqual(["3"]);
    // A tag page spans initiatives: the list is the community's, not one's.
    expect(asked.projects?.has("initiative_id")).toBe(false);

    expect(screen.getByRole("heading", { name: /Tasks \(1\)/ })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Wire the doorbell/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/projects/7/tasks/9"
    );
    // Nothing inside a project but tasks carries tags, and no wiki is asked
    // for until its tab opens.
    expect(asked.entities).toEqual([]);
  });

  it("lists the pages inside a wiki by name, beside the wiki they are in", async () => {
    const asked = serveTag();
    renderTagPage();

    await userEvent.click(await screen.findByRole("tab", { name: /Wikis \(1\)/ }));
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).queryByRole("heading", { name: /^Wikis/ })).not.toBeInTheDocument();
    expect(await within(panel).findByRole("link", { name: /Rota/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/wikis/4/pages/11"
    );
    expect(within(panel).getByRole("link", { name: "Handbook" })).toHaveAttribute(
      "href",
      "/c/1/i/5/wikis/4"
    );
    expect(asked.entities.map((params) => params.get("kind"))).toEqual(["wiki_page"]);
  });

  it("opens the tab the address names", async () => {
    serveTag();
    renderTagPage({ tool: "wikis" });

    expect(await screen.findByRole("tab", { name: /Wikis \(1\)/ })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(await screen.findByRole("link", { name: /Rota/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/wikis/4/pages/11"
    );
  });

  it("says when the tag's counts could not be read, and asks again", async () => {
    let fail = true;
    server.use(
      communityHttp.get("/tags/:tagId", () => HttpResponse.json(tag)),
      communityHttp.get("/tags/:tagId/counts", () =>
        fail
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({ counts: {} })
      )
    );
    renderTagPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing carries this tag yet.")).toBeInTheDocument();
  });

  it("lists tagged tasks without controls a row cannot promise", async () => {
    serveTag();
    renderTagPage();

    const link = await screen.findByRole("link", { name: /Wire the doorbell/ });
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("To Do")).toBeInTheDocument();
    expect(within(row).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("says so when nothing carries the tag", async () => {
    server.use(
      communityHttp.get("/tags/:tagId", () => HttpResponse.json(tag)),
      communityHttp.get("/tags/:tagId/counts", () => HttpResponse.json({ counts: {} }))
    );
    renderTagPage();

    expect(await screen.findByText("Nothing carries this tag yet.")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});
