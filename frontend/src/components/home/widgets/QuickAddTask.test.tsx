import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildTagSummary,
  buildTask,
  buildTaskType,
  buildUser,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { QuickAddTask } from "./QuickAddTask";

const LIST = { communityId: 3, initiativeId: 4, projectId: 5 };

/** Serve the community's tags and take the task it adds. */
const stubAdd = () => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.get("/tags/", () =>
      HttpResponse.json([buildTagSummary({ id: 21, name: "billing" })])
    ),
    communityHttp.post("/tasks/", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      return HttpResponse.json(buildTask({ title: String(body.title) }));
    })
  );
  return sent;
};

const renderBox = (smart: boolean) =>
  renderWithProviders(<QuickAddTask list={LIST} name="Chores" />, {
    auth: { user: buildUser({ id: 7, smart_task_titles: smart }) },
  });

describe("QuickAddTask", () => {
  it("reads the title for its details where the reader has that on", async () => {
    const sent = stubAdd();
    renderBox(true);
    const box = screen.getByRole("textbox", { name: /add a task to chores/i });
    await userEvent.type(box, "Pay the invoice tomorrow !high #billing");

    const read = await screen.findByRole("list", { name: /read from the title/i });
    expect(read).toHaveTextContent(/high priority/i);
    await waitFor(() => expect(read).toHaveTextContent("billing"));

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      title: "Pay the invoice",
      project_id: 5,
      priority: "high",
      tag_ids: [21],
      assignee_ids: [7],
    });
    expect(typeof sent[0].due_date).toBe("string");
  });

  it("gives the task the type its title starts with", async () => {
    const sent = stubAdd();
    const milestone = buildTaskType({ id: 61, name: "Milestone" });
    server.use(
      communityHttp.get("/projects/:id/task-types/", () =>
        HttpResponse.json([buildTaskType({ id: 60, name: "Task" }), milestone])
      )
    );
    renderBox(true);
    await userEvent.type(screen.getByRole("textbox"), "Milestone: Ship v2");
    const read = await screen.findByRole("list", { name: /read from the title/i });
    await waitFor(() => expect(read).toHaveTextContent("Milestone"));

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ title: "Ship v2", task_type_id: 61 });
  });

  it("offers what a title can say only where the reader has titles read", async () => {
    renderBox(true);
    await userEvent.click(screen.getByRole("button", { name: /what a title can say/i }));
    expect(await screen.findByText(/type the details into the title/i)).toBeInTheDocument();
  });

  it("offers no hints where the reader has titles read as typed", () => {
    renderBox(false);
    expect(screen.queryByRole("button", { name: /what a title can say/i })).not.toBeInTheDocument();
  });

  it("keeps words taken off the list in the title", async () => {
    const sent = stubAdd();
    renderBox(true);
    await userEvent.type(screen.getByRole("textbox"), "Plan the trip next week");
    await userEvent.click(
      await screen.findByRole("button", { name: /keep “next week” in the title/i })
    );
    expect(screen.queryByRole("list", { name: /read from the title/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].title).toBe("Plan the trip next week");
    expect(sent[0]).not.toHaveProperty("due_date");
  });

  it("adds the title as typed where the reader has it off", async () => {
    const sent = stubAdd();
    renderBox(false);
    await userEvent.type(screen.getByRole("textbox"), "Pay the invoice tomorrow !high");
    expect(screen.queryByRole("list", { name: /read from the title/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({
      title: "Pay the invoice tomorrow !high",
      project_id: 5,
      assignee_ids: [7],
    });
  });

  it("offers the project's people under @, and gives the task to the one picked", async () => {
    const sent = stubAdd();
    const asked: string[] = [];
    server.use(
      communityHttp.get("/users/search", ({ request, params }) => {
        asked.push(`${params.communityId}:${new URL(request.url).searchParams.get("resource_id")}`);
        return HttpResponse.json({
          items: [buildUserSummary({ id: 42, username: "sam", display_name: "Sam Vimes" })],
          total_count: 1,
          page: 1,
          page_size: 8,
          has_next: false,
          has_prev: false,
        });
      })
    );
    renderBox(true);
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "Water the plants @sa");
    await userEvent.click(await screen.findByRole("button", { name: /Sam Vimes/ }));
    expect(box).toHaveValue("Water the plants @sam ");
    expect(asked).toContain("3:5");

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ title: "Water the plants", assignee_ids: [7, 42] });
  });

  it("starts the next task afresh, with nothing kept from the last", async () => {
    const sent = stubAdd();
    renderBox(true);
    const box = screen.getByRole("textbox");
    await userEvent.type(box, "Plan the trip next week");
    await userEvent.click(
      await screen.findByRole("button", { name: /keep “next week” in the title/i })
    );
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    await waitFor(() => expect(box).toHaveValue(""));

    await userEvent.type(box, "Send the invoices next week");
    await screen.findByRole("list", { name: /read from the title/i });
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].title).toBe("Send the invoices");
    expect(typeof sent[1].due_date).toBe("string");
  });

  it("assigns everybody named, when one is found by more than one handle", async () => {
    const sent = stubAdd();
    const sam = buildUserSummary({ id: 42, username: "sam" });
    const samJones = buildUserSummary({ id: 43, username: "sam.jones" });
    server.use(
      communityHttp.get("/users/search", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search");
        // Searching "sam" finds sam.jones too.
        const items = search === "sam" ? [sam, samJones] : [samJones];
        return HttpResponse.json({
          items,
          total_count: items.length,
          page: 1,
          page_size: 20,
          has_next: false,
          has_prev: false,
        });
      })
    );
    renderBox(true);
    await userEvent.type(screen.getByRole("textbox"), "Review the draft @sam @sam.jones");
    // Typing "@" opens the list; the reading still waits for both lookups.
    await userEvent.keyboard("{Escape}");
    const read = await screen.findByRole("list", { name: /read from the title/i });
    await waitFor(() => expect(read.querySelectorAll("li")).toHaveLength(2));

    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ title: "Review the draft", assignee_ids: [7, 42, 43] });
  });
});
