import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildIdea, buildIdeaStatus, buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { IdeaListRead, IdeaRead } from "@/api/generated/initiativeAPI.schemas";
import { CLOUD_ORIGIN } from "@/lib/cloud";

import { IdeaPage } from "./IdeaPage";
import { IdeasPage } from "./IdeasPage";

const cloud = { getServerOrigin: () => CLOUD_ORIGIN };

const considering = () =>
  buildIdeaStatus({ name: "Under consideration", icon: "lightbulb", category: "todo" });
const shipped = () =>
  buildIdeaStatus({ name: "Shipped", icon: "rocket", color: "#059669", category: "done" });

/** Serves `ideas` as the list, narrowed by the category asked for, and
 *  reports each request's parameters. */
const serveList = (ideas: IdeaRead[]) => {
  const asked: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/ideas", ({ request }) => {
      const params = new URL(request.url).searchParams;
      asked.push(params);
      const category = params.get("category");
      const items = ideas.filter((idea) => !category || idea.category === category);
      return HttpResponse.json({
        total_count: items.length,
        page: 1,
        page_size: 50,
        has_next: false,
        has_prev: false,
        items,
        statuses: [...new Map(ideas.map((idea) => [idea.status.id, idea.status])).values()],
        categories: [
          { name: "Calendars", count: ideas.filter((i) => i.category === "Calendars").length },
          { name: "Projects", count: ideas.filter((i) => i.category === "Projects").length },
        ],
      } satisfies IdeaListRead);
    })
  );
  return asked;
};

describe("IdeasPage", () => {
  it("lists the suggestions with their summary, category, status and upvote", async () => {
    serveList([
      buildIdea({
        title: "Recurring events skip holidays",
        summary: "A repeating event leaves out the public holidays.",
        category: "Calendars",
        status: considering(),
        votes: 2,
      }),
    ]);
    renderPage(IdeasPage, { initialRoute: "/suggestions", server: cloud, auth: { user: null } });

    expect(
      await screen.findByRole("link", { name: "Recurring events skip holidays" })
    ).toHaveAttribute("href", "/suggestions/2");
    expect(screen.getByText("A repeating event leaves out the public holidays.")).toBeVisible();
    const row = within(screen.getByRole("list", { name: "Suggestions" })).getByRole("listitem");
    expect(within(row).getByText("Calendars")).toBeVisible();
    expect(within(row).getByText("Under consideration")).toBeVisible();
    expect(
      within(row).getByRole("button", { name: "2 votes. Upvote Recurring events skip holidays" })
    ).toHaveAttribute("aria-pressed", "false");
    // Signed out, the band says how to vote, and comes back here.
    expect(screen.getByRole("link", { name: "Sign in to vote" })).toHaveAttribute(
      "href",
      "/login?next=%2Fsuggestions"
    );
    expect(screen.getByRole("link", { name: "Send feedback" })).toHaveAttribute(
      "href",
      "/feedback"
    );
    // Only somebody signed in has votes of their own to narrow to.
    expect(screen.queryByRole("radio", { name: "Voted by me" })).toBeNull();
  });

  it("narrows to a category, each offered with its count", async () => {
    const user = userEvent.setup();
    const asked = serveList([
      buildIdea({ title: "Holiday calendars", category: "Calendars", status: considering() }),
      buildIdea({ title: "Board shortcuts", category: "Projects", status: considering() }),
    ]);
    renderPage(IdeasPage, {
      initialRoute: "/suggestions",
      server: cloud,
      auth: { user: buildUser() },
    });

    await screen.findByRole("link", { name: "Board shortcuts" });
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Voted by me" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Projects 1" }));

    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Holiday calendars" })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("link", { name: "Board shortcuts" })).toBeInTheDocument();
    expect(asked.at(-1)?.get("category")).toBe("Projects");
  });

  it("says when nothing matches", async () => {
    serveList([]);
    renderPage(IdeasPage, { initialRoute: "/suggestions", server: cloud, auth: { user: null } });
    expect(await screen.findByText("No suggestions match.")).toBeVisible();
  });

  it("sends somebody signed out to sign in to upvote, and upvotes for somebody signed in", async () => {
    const user = userEvent.setup();
    const idea = buildIdea({ title: "Recurring events skip holidays", votes: 2 });
    serveList([idea]);
    server.use(
      http.put("/api/v1/ideas/:taskId/vote", () =>
        HttpResponse.json({ ...idea, votes: 3, voted: true })
      )
    );
    const out = renderPage(IdeasPage, {
      initialRoute: "/suggestions",
      server: cloud,
      auth: { user: null },
    });
    const signedOut = await screen.findByRole("button", {
      name: "2 votes. Upvote Recurring events skip holidays",
    });
    expect(signedOut).toBeEnabled();
    expect(signedOut).toHaveAccessibleDescription("Sign in to vote");
    await user.click(signedOut);
    expect(out.router.state.location.pathname).toBe("/login");
    expect(out.router.state.location.search).toEqual({ next: "/suggestions" });
    out.unmount();

    renderPage(IdeasPage, {
      initialRoute: "/suggestions",
      server: cloud,
      auth: { user: buildUser() },
    });
    const signedIn = await screen.findByRole("button", {
      name: "2 votes. Upvote Recurring events skip holidays",
    });
    expect(signedIn).not.toHaveAccessibleDescription();
    await user.click(signedIn);
    expect(await screen.findByText("Upvoted. 3 votes.")).toBeInTheDocument();
  });

  it("shows a closed suggestion's votes as text, with no button", async () => {
    serveList([buildIdea({ title: "Print a month", status: shipped(), votes: 5 })]);
    renderPage(IdeasPage, { initialRoute: "/suggestions", server: cloud, auth: { user: null } });

    expect(await screen.findByRole("img", { name: "5 votes, voting closed" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Upvote/ })).toBeNull();
  });

  it("draws the Roadmap's columns, each a list under its status", async () => {
    const planned = buildIdeaStatus({ name: "Planned", category: "in_progress" });
    const building = buildIdeaStatus({ name: "Building", category: "in_progress" });
    const done = shipped();
    server.use(
      http.get("/api/v1/ideas/roadmap", () =>
        HttpResponse.json({
          columns: [
            {
              status: planned,
              items: [
                buildIdea({ title: "Board shortcuts", status: planned, category: "Projects" }),
              ],
            },
            { status: building, items: [] },
            { status: done, items: [buildIdea({ title: "Print a month", status: done })] },
          ],
        })
      )
    );
    renderPage(IdeasPage, {
      initialRoute: "/suggestions",
      routerHash: "roadmap",
      server: cloud,
      auth: { user: null },
    });

    const plannedList = await screen.findByRole("list", { name: "Planned" });
    expect(within(plannedList).getByRole("link", { name: "Board shortcuts" })).toBeVisible();
    expect(within(plannedList).getByText("Projects")).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "Building" })).toBeInTheDocument();
    expect(screen.getByText("0 suggestions")).toBeInTheDocument();
    const shippedList = screen.getByRole("list", { name: "Shipped" });
    expect(
      within(shippedList).getByRole("img", { name: "0 votes, voting closed" })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Roadmap" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "List" })).not.toHaveAttribute("aria-current");
  });

  it("leads home anywhere but Initiative Cloud", async () => {
    const { router } = renderPage(IdeasPage, {
      initialRoute: "/suggestions",
      auth: { user: null },
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });
});

describe("IdeaPage", () => {
  const serveIdea = (idea: IdeaRead) =>
    server.use(http.get("/api/v1/ideas/:taskId", () => HttpResponse.json(idea)));

  it("shows the suggestion, a way to add one's thoughts, and the release it shipped in", async () => {
    const idea = buildIdea({
      title: "Print a month",
      description: "A clean month on one page.",
      category: "Calendars",
      status: shipped(),
      release: "0.79.0",
      votes: 5,
    });
    serveIdea(idea);
    renderPage(IdeaPage, {
      initialRoute: "/suggestions/$taskId",
      routeParams: { taskId: String(idea.task_id) },
      server: cloud,
      auth: { user: null },
    });

    expect(await screen.findByRole("heading", { level: 1, name: "Print a month" })).toBeVisible();
    expect(screen.getByText("A clean month on one page.")).toBeVisible();
    expect(screen.getByRole("link", { name: "All suggestions" })).toHaveAttribute(
      "href",
      "/suggestions"
    );
    expect(screen.getByRole("link", { name: "Shipped in 0.79.0" })).toHaveAttribute(
      "href",
      "/whats-new/0.79.0"
    );
    expect(screen.getByRole("link", { name: "Add your thoughts" })).toHaveAttribute(
      "href",
      `/feedback?idea=${idea.task_id}`
    );
    expect(screen.getByRole("img", { name: "5 votes, voting closed" })).toBeVisible();
  });

  it("names no release for a suggestion that has not shipped", async () => {
    const idea = buildIdea({ title: "Board shortcuts", status: considering() });
    serveIdea(idea);
    renderPage(IdeaPage, {
      initialRoute: "/suggestions/$taskId",
      routeParams: { taskId: String(idea.task_id) },
      server: cloud,
      auth: { user: null },
    });

    await screen.findByRole("heading", { level: 1, name: "Board shortcuts" });
    expect(screen.queryByRole("link", { name: /Shipped in/ })).toBeNull();
    expect(screen.getByRole("button", { name: "0 votes. Upvote Board shortcuts" })).toBeVisible();
  });
});
