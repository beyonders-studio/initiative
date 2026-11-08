/**
 * A task's subtasks, on the row where the task is read: a mark when it has
 * any, and on hover what they are, fetched only then.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  ActorKind,
  type ChecklistProgress,
  type RelationshipRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskSubtasksHoverCard } from "@/components/projects/TaskSubtasksHoverCard";

const row = (
  id: number,
  title: string,
  relationship_type: RelationshipRead["relationship_type"],
  direction: RelationshipRead["direction"]
): RelationshipRead => ({
  id,
  relationship_type,
  direction,
  provenance: "manual",
  confidence: null,
  created_by: 1,
  created_by_kind: ActorKind.member,
  created_by_install: null,
  created_at: "2026-09-01T00:00:00Z",
  other: {
    type: SearchEntityType.task,
    id: 40 + id,
    title,
    initiative_id: 3,
    handle: null,
    updated_at: null,
    tool: Tool.project,
    tool_id: 1,
    tool_title: null,
    image_urls: [],
    icon: null,
    color: null,
    file_type: null,
    mime_type: null,
    original_filename: null,
    smart_link_url: null,
    is_open: true,
    starts_at: null,
  },
});

const mount = (progress: ChecklistProgress | null) =>
  renderPage(() => <TaskSubtasksHoverCard task={{ id: 1, subtask_progress: progress }} />, {
    initialRoute: "/c/1",
  });

describe("TaskSubtasksHoverCard", () => {
  it("draws nothing for a task with no subtasks", () => {
    mount(null);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lists the subtasks on hover, and only then asks for them", async () => {
    const asked = vi.fn();
    server.use(
      communityHttp.get("/relationships/", () => {
        asked();
        return HttpResponse.json([
          row(1, "Find the hideout", "part_of", "inbound"),
          row(2, "The whole campaign", "part_of", "outbound"),
          row(3, "Get a map", "depends_on", "outbound"),
        ]);
      })
    );
    const user = userEvent.setup();
    mount({ completed: 1, total: 3 });

    const trigger = await screen.findByRole("button", { name: "1/3 subtasks" });
    expect(asked).not.toHaveBeenCalled();

    await user.hover(trigger);

    expect(await screen.findByText("Find the hideout")).toBeInTheDocument();
    await waitFor(() => expect(asked).toHaveBeenCalled());
    expect(screen.queryByText("The whole campaign")).not.toBeInTheDocument();
    expect(screen.queryByText("Get a map")).not.toBeInTheDocument();
  });
});
