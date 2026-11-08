import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { ToolCommentsPanel } from "./ToolCommentsPanel";

/** Records the query the panel derived for the thread it wants. The first
 *  page names an older one behind it; that one is the end of the thread. */
const captureList = () => {
  const seen: URLSearchParams[] = [];
  server.use(
    communityHttp.get("/comments/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      seen.push(params);
      return HttpResponse.json(
        params.get("cursor") === "older"
          ? { comments: [buildComment({ content: "Earlier" })], next_cursor: null }
          : { comments: [buildComment({ content: "Existing" })], next_cursor: "older" }
      );
    })
  );
  return seen;
};

describe("ToolCommentsPanel", () => {
  it("derives the thread's query param from the tool", async () => {
    const requests = captureList();

    renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.counter_group}
        entity={{ id: 9, initiative_id: 4, comments_enabled: true }}
      />
    ));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].get("counter_group_id")).toBe("9");
  });

  it("uses the same derivation for a different tool, with no per-tool wiring", async () => {
    const requests = captureList();

    renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.dashboard}
        entity={{ id: 12, initiative_id: 4, comments_enabled: true }}
      />
    ));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].get("dashboard_id")).toBe("12");
  });

  it("asks for the target's thread, not the tool's, when one is given", async () => {
    const requests = captureList();

    renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.wiki}
        entity={{ id: 7, initiative_id: 4, comments_enabled: true }}
        target={{ type: "wiki_page", id: 42 }}
      />
    ));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].get("wiki_page_id")).toBe("42");
    expect(requests[0].get("wiki_id")).toBeNull();
  });

  it("still lets the tool answer for whether a target's thread exists", async () => {
    const requests = captureList();

    const { container } = renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.wiki}
        entity={{ id: 7, initiative_id: 4, comments_enabled: false }}
        target={{ type: "wiki_page", id: 42 }}
      />
    ));

    expect(container).toBeEmptyDOMElement();
    expect(requests).toHaveLength(0);
  });

  it("renders nothing and asks for nothing when the entity has comments off", async () => {
    const requests = captureList();

    const { container } = renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.counter_group}
        entity={{ id: 3, initiative_id: 4, comments_enabled: false }}
      />
    ));

    expect(container).toBeEmptyDOMElement();
    // Nothing to wait on — assert the absence after a tick of the query client.
    await waitFor(() => expect(requests).toHaveLength(0));
  });

  it("shows the newest conversations and loads older ones on demand", async () => {
    const requests = captureList();
    const user = userEvent.setup();

    renderPage(() => (
      <ToolCommentsPanel
        tool={Tool.project}
        entity={{ id: 1, initiative_id: 4, comments_enabled: true }}
      />
    ));

    expect(await screen.findByText("Existing")).toBeInTheDocument();
    expect(screen.queryByText("Earlier")).not.toBeInTheDocument();
    expect(requests[0].get("cursor")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Load older comments" }));

    expect(await screen.findByText("Earlier")).toBeInTheDocument();
    expect(requests[1].get("cursor")).toBe("older");
    expect(requests[1].get("project_id")).toBe("1");
    expect(screen.queryByRole("button", { name: "Load older comments" })).not.toBeInTheDocument();
  });
});
