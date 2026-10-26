/**
 * A target's layouts in settings: its views and its pages apart, and each view
 * shown in its layout menu or hidden from here, one always staying shown, and
 * each task type deleted with its page, one always staying.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildToolLayoutSet } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type DetailLayoutRead,
  type ListLayoutWrite,
  type TaskTypeDeleteRequest,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { LayoutList } from "@/components/layouts/LayoutList";
import { instanceTarget } from "@/hooks/useToolLayouts";

const bugPage: DetailLayoutRead = {
  kind: "task",
  task_type_id: 2,
  task_type_name: "Bug",
  definition: {},
  updated_at: null,
};

const mount = (target = true, extra: DetailLayoutRead[] = []) =>
  renderPage(
    () => (
      <LayoutList
        layouts={
          buildToolLayoutSet({ hidden: ["table", "gantt", "calendar"], layouts: extra }).layouts
        }
        target={target ? instanceTarget(Tool.project, 1) : undefined}
      />
    ),
    { initialRoute: "/c/1" }
  );

describe("LayoutList", () => {
  it("groups a project's views apart from its task pages, and shows a hidden view", async () => {
    const sent = vi.fn();
    server.use(
      communityHttp.put("/layouts/", async ({ request }) => {
        sent((await request.json()) as ListLayoutWrite);
        return HttpResponse.json(buildToolLayoutSet());
      })
    );
    const user = userEvent.setup();
    mount();

    const views = await screen.findByRole("region", { name: "Views" });
    expect(within(views).getAllByRole("listitem")).toHaveLength(4);
    const pages = screen.getByRole("region", { name: "Task pages" });
    expect(within(pages).getByText("Task page")).toBeVisible();

    // The board is the one shown, so it stays shown.
    expect(screen.getByRole("switch", { name: "Show Board in the layout menu" })).toBeDisabled();
    await user.click(screen.getByRole("switch", { name: "Show Gantt in the layout menu" }));
    await waitFor(() =>
      expect(sent).toHaveBeenCalledWith({ kind: "gantt", definition: { hidden: false } })
    );
  });

  it("deletes a task type, its tasks going to the default, and keeps the last", async () => {
    const sent = vi.fn();
    server.use(
      communityHttp.delete("/projects/:id/task-types/:typeId", async ({ params, request }) => {
        sent(params.typeId, (await request.json()) as TaskTypeDeleteRequest);
        return new HttpResponse(null, { status: 204 });
      })
    );
    const user = userEvent.setup();
    mount(true, [bugPage]);

    await user.click(await screen.findByRole("button", { name: "Delete the Bug task type" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(sent).toHaveBeenCalledWith("2", { fallback_type_id: 1 }));
  });

  it("keeps a project's only task type", async () => {
    mount();

    expect(await screen.findByRole("button", { name: "Delete the Task task type" })).toBeDisabled();
  });

  it("only reads, saying which views are hidden, without a target", async () => {
    mount(false);

    expect(await screen.findAllByText("Hidden")).toHaveLength(3);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /task type/ })).not.toBeInTheDocument();
  });
});
