import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import type { ChecklistItem } from "@/api/generated/initiativeAPI.schemas";

import { TaskChecklist } from "./TaskChecklist";

const TASK_ID = 12;

const items: ChecklistItem[] = [
  { id: "one", text: "Draft the copy", done: false },
  { id: "two", text: "Get it reviewed", done: false },
];

/** Record what each kind of write asked for, so the two can be told apart. */
function stubWrites() {
  const ticks: { itemId: string; body: unknown }[] = [];
  const listWrites: unknown[] = [];
  server.use(
    communityHttp.patch("/tasks/:taskId/checklist/:itemId", async ({ request, params }) => {
      const body = await request.json();
      ticks.push({ itemId: String(params.itemId), body });
      return HttpResponse.json(
        items.map((item) =>
          item.id === params.itemId ? { ...item, done: (body as { done: boolean }).done } : item
        )
      );
    }),
    communityHttp.patch("/tasks/:taskId", async ({ request }) => {
      const body = (await request.json()) as { checklist?: unknown };
      listWrites.push(body.checklist);
      return HttpResponse.json(buildTask({ id: TASK_ID }));
    })
  );
  return { ticks, listWrites };
}

const renderChecklist = (canEdit = true, list: ChecklistItem[] = items) =>
  renderPage(() => <TaskChecklist taskId={TASK_ID} items={list} canEdit={canEdit} />, {
    queryClient: createTestQueryClient(),
  });

const LONG = "A step with rather more to say about itself than a single line can hold at once";

/**
 * jsdom lays nothing out, so "the text runs past the end of the field" is
 * stood in for: ten pixels a character against a 500px field.
 */
const stubWidths = () => {
  Object.defineProperty(HTMLInputElement.prototype, "scrollWidth", {
    configurable: true,
    get(this: HTMLInputElement) {
      return this.value.length * 10;
    },
  });
  Object.defineProperty(HTMLInputElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 500,
  });
};

afterEach(() => {
  Reflect.deleteProperty(HTMLInputElement.prototype, "scrollWidth");
  Reflect.deleteProperty(HTMLInputElement.prototype, "clientWidth");
});

describe("TaskChecklist", () => {
  it("ticks one item by id rather than rewriting the list", async () => {
    const user = userEvent.setup();
    const { ticks, listWrites } = stubWrites();
    renderChecklist();

    const boxes = await screen.findAllByLabelText("Mark checklist item as complete");
    await user.click(boxes[0]);

    await waitFor(() => expect(ticks).toHaveLength(1));
    expect(ticks[0]).toMatchObject({ itemId: "one", body: { done: true } });
    // The rest of the list is not part of a tick.
    expect(listWrites).toHaveLength(0);
  });

  it("shows how much is done", async () => {
    const { ticks } = stubWrites();
    const user = userEvent.setup();
    renderChecklist();

    expect(await screen.findByText("0/2 items")).toBeInTheDocument();

    await user.click(screen.getAllByLabelText("Mark checklist item as complete")[0]);

    await waitFor(() => expect(ticks).toHaveLength(1));
    expect(screen.getByText("1/2 items")).toBeInTheDocument();
  });

  it("sends the whole list when a line is added", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    await user.type(await screen.findByPlaceholderText("Add checklist item"), "Ship it{Enter}");

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect(listWrites[0]).toEqual([
      { id: "one", text: "Draft the copy", done: false },
      { id: "two", text: "Get it reviewed", done: false },
      { id: expect.any(String), text: "Ship it", done: false },
    ]);
  });

  it("splits a pasted block into one item per line", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    await user.click(await screen.findByPlaceholderText("Add checklist item"));
    await user.paste("- First thing\n- Second thing");

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect((listWrites[0] as { text: string }[]).map((item) => item.text)).toEqual([
      "Draft the copy",
      "Get it reviewed",
      "First thing",
      "Second thing",
    ]);
  });

  it("opens a fresh line on Enter without saving it until it says something", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    const first = await screen.findByDisplayValue("Draft the copy");
    await user.click(first);
    await user.keyboard("{Enter}");

    // A blank line is not a checklist item, so nothing has been sent.
    expect(listWrites).toHaveLength(0);
    expect(screen.getAllByPlaceholderText("Checklist item")).toHaveLength(3);

    await user.keyboard("Third thing");
    await user.tab();

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect((listWrites[0] as { text: string }[]).map((item) => item.text)).toEqual([
      "Draft the copy",
      "Third thing",
      "Get it reviewed",
    ]);
  });

  it("says when a suggestion was written from only the newest comments", async () => {
    server.use(
      communityHttp.get("/settings/ai/resolved", () =>
        HttpResponse.json({ enabled: true, source: "platform" })
      ),
      communityHttp.post("/tasks/:taskId/ai/checklist", () =>
        HttpResponse.json({ items: ["Book the hall"], comments_read: 12, comments_total: 40 })
      )
    );
    const user = userEvent.setup();
    renderChecklist();

    await user.click(await screen.findByRole("button", { name: "AI Generate" }));

    expect(await screen.findByLabelText("Book the hall")).toBeChecked();
    expect(screen.getByText("Written from the 12 most recent of 40 comments.")).toBeInTheDocument();
  });

  it("offers no edits without write access", async () => {
    stubWrites();
    renderChecklist(false);

    expect(await screen.findByPlaceholderText("Read-only")).toBeDisabled();
    expect(screen.queryByLabelText("Delete checklist item")).not.toBeInTheDocument();
  });

  it("offers to open only the lines that do not fit", async () => {
    stubWidths();
    stubWrites();
    renderChecklist(true, [
      { id: "one", text: "Short", done: false },
      { id: "two", text: LONG, done: false },
    ]);

    await screen.findByDisplayValue("Short");
    // One control, for the one line that runs past the end.
    expect(screen.getAllByLabelText("Show the whole item")).toHaveLength(1);
  });

  it("opens a long line to read all of it, and closes it again", async () => {
    const user = userEvent.setup();
    stubWidths();
    stubWrites();
    renderChecklist(true, [{ id: "two", text: LONG, done: false }]);

    const open = await screen.findByLabelText("Show the whole item");
    expect(open).toHaveAttribute("aria-expanded", "false");
    await user.click(open);

    // The same text, now in a field that can show all of it.
    const opened = screen.getByDisplayValue(LONG);
    expect(opened.tagName).toBe("TEXTAREA");

    const close = screen.getByLabelText("Show less");
    expect(close).toHaveAttribute("aria-expanded", "true");
    await user.click(close);

    expect(screen.getByDisplayValue(LONG).tagName).toBe("INPUT");
  });

  it("an opened line is still editable and still saves", async () => {
    const user = userEvent.setup();
    stubWidths();
    const { listWrites } = stubWrites();
    renderChecklist(true, [{ id: "two", text: LONG, done: false }]);

    await user.click(await screen.findByLabelText("Show the whole item"));
    await user.type(screen.getByDisplayValue(LONG), " — and more");
    await user.tab();

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect((listWrites[0] as { text: string }[])[0].text).toBe(`${LONG} — and more`);
  });

  it("makes a saved line a task and takes it off the list", async () => {
    const user = userEvent.setup();
    stubWrites();
    const promoted: string[] = [];
    server.use(
      communityHttp.post("/tasks/:taskId/checklist/:itemId/promote", ({ params }) => {
        promoted.push(String(params.itemId));
        return HttpResponse.json(buildTask({ id: 99, title: "Get it reviewed" }), { status: 201 });
      })
    );
    renderChecklist();

    const buttons = await screen.findAllByLabelText("Make this checklist item a task");
    await user.click(buttons[1]);

    await waitFor(() => expect(promoted).toEqual(["two"]));
    await waitFor(() => expect(screen.queryByDisplayValue("Get it reviewed")).toBeNull());
    expect(screen.getByDisplayValue("Draft the copy")).toBeInTheDocument();
  });

  it("keeps what is typed into another line while one becomes a task", async () => {
    const user = userEvent.setup();
    stubWrites();
    let answer: () => void = () => {};
    server.use(
      communityHttp.post(
        "/tasks/:taskId/checklist/:itemId/promote",
        () =>
          new Promise<Response>((resolve) => {
            answer = () =>
              resolve(HttpResponse.json(buildTask({ id: 99 }), { status: 201 }) as Response);
          })
      )
    );
    // The task as the server holds it, which a refetch hands the checklist.
    let refetch: (next: ChecklistItem[]) => void = () => {};
    const Held = () => {
      const [held, setHeld] = useState(items);
      refetch = setHeld;
      return <TaskChecklist taskId={TASK_ID} items={held} canEdit />;
    };
    renderPage(() => <Held />, { queryClient: createTestQueryClient() });

    const buttons = await screen.findAllByLabelText("Make this checklist item a task");
    await user.click(buttons[1]);
    await user.type(screen.getByDisplayValue("Draft the copy"), " today");
    answer();
    await waitFor(() => expect(screen.queryByDisplayValue("Get it reviewed")).toBeNull());
    act(() => refetch([items[0]]));

    expect(screen.getByDisplayValue("Draft the copy today")).toBeInTheDocument();
  });

  it("offers no task for a line the server does not hold yet", async () => {
    const user = userEvent.setup();
    stubWrites();
    renderChecklist();

    const first = await screen.findByDisplayValue("Draft the copy");
    await user.type(first, " now");

    const buttons = screen.getAllByLabelText("Make this checklist item a task");
    expect(buttons[0]).toBeDisabled();
    expect(buttons[1]).toBeEnabled();
  });

  it("offers nothing to a reader who cannot change the task", async () => {
    renderChecklist(false);

    await screen.findByDisplayValue("Draft the copy");
    expect(screen.queryByLabelText("Make this checklist item a task")).toBeNull();
  });
});
