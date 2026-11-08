/**
 * What is holding a task up, on the row where the task is read.
 *
 * The count rides on the task payload and the names are fetched only when
 * somebody asks, so the two things worth asserting are that a clear task draws
 * nothing at all, and that a table of rows costs no requests until one is
 * hovered.
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
  type RelationshipRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";

import { TaskBlockersHoverCard } from "./TaskBlockersHoverCard";

const blockerRow = (title: string, isOpen: boolean): RelationshipRead => ({
  id: 1,
  relationship_type: "depends_on",
  direction: "outbound",
  provenance: "manual",
  confidence: null,
  created_by: 1,
  created_by_kind: ActorKind.member,
  created_by_install: null,
  created_at: "2026-09-01T00:00:00Z",
  other: {
    type: SearchEntityType.task,
    id: 42,
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
    is_open: isOpen,
    starts_at: null,
  },
});

const mount = (count: number) =>
  renderPage(() => <TaskBlockersHoverCard task={{ id: 1, blocked_by_open_count: count }} />, {
    initialRoute: "/c/1",
  });

describe("TaskBlockersHoverCard", () => {
  it("draws nothing at all when nothing is holding the task up", () => {
    mount(0);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("marks a task that is waiting on something", async () => {
    mount(2);

    expect(await screen.findByRole("button", { name: "What's holding this up" })).toBeVisible();
  });

  it("costs no request until somebody asks what the things are", async () => {
    const asked = vi.fn();
    server.use(
      communityHttp.get("/relationships/", () => {
        asked();
        return HttpResponse.json([blockerRow("Ship the API", true)]);
      })
    );
    const user = userEvent.setup();
    mount(1);

    const trigger = await screen.findByRole("button", { name: "What's holding this up" });
    expect(asked).not.toHaveBeenCalled();

    await user.hover(trigger);

    expect(await screen.findByText("Ship the API")).toBeInTheDocument();
    await waitFor(() => expect(asked).toHaveBeenCalled());
  });
});
