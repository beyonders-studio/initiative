import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  buildProjectTaskStatus,
  buildTag,
  buildTaskType,
  buildToolLayoutSet,
  buildUser,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  QueueItemRead,
  TaskRead,
  TaskTypeRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { blankQueueItem, QUEUE_ITEM_DETAIL } from "@/lib/layouts/queueItemLayout";
import { blankTask, TASK_DETAIL } from "@/lib/layouts/taskLayout";

import { AddItemDialog, type Written } from "./AddItemDialog";

/** A queue's Add Item, with the dialog closed and opened again by a button. */
const Adding = ({
  create,
}: {
  create: (written: Written<QueueItemRead, unknown>) => Promise<{ id: number }>;
}) => {
  const [open, setOpen] = useState(true);
  const leaving = useRef(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <AddItemDialog
        open={open}
        onOpenChange={setOpen}
        detail={QUEUE_ITEM_DETAIL}
        blank={blankQueueItem(1)}
        context={{ readOnly: false, queueId: 1, initiativeId: 1, leaving, actions: null }}
        layouts={() => null}
        title="Add Item"
        ready={(item) => item.label.trim() !== ""}
        create={create}
        onAdded={() => setOpen(false)}
      />
    </>
  );
};

describe("adding an item", () => {
  it("is drawn as its kind is laid out, and made whole by Add", async () => {
    const patched = vi.fn();
    server.use(
      communityHttp.patch("/queue-items/:itemId", () => {
        patched();
        return HttpResponse.json({});
      })
    );
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();

    const add = await screen.findByRole("button", { name: "Add Item" });
    expect(add).toBeDisabled();
    await user.type(screen.getByPlaceholderText("Item name"), "Goblin");
    const position = within(screen.getByRole("group", { name: "Position" })).getByRole(
      "spinbutton"
    );
    await user.clear(position);
    await user.type(position, "12");
    await user.click(add);

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ fields: { label: "Goblin", position: 12 }, properties: [] })
      )
    );
    expect(patched).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Add Item" })).not.toBeInTheDocument()
    );
  });

  it("drops what was typed when it is closed", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText("Item name"), "Ogre");
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(await screen.findByPlaceholderText("Item name")).toHaveValue("");
    expect(create).not.toHaveBeenCalled();
  });

  it("waits while a field is emptied or shows what it cannot take", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();
    const add = await screen.findByRole("button", { name: "Add Item" });
    const label = screen.getByPlaceholderText("Item name");

    await user.type(label, "Imp");
    await user.clear(label);
    expect(add).toBeDisabled();

    await user.type(label, "Imp");
    const position = within(screen.getByRole("group", { name: "Position" })).getByRole(
      "spinbutton"
    );
    await user.type(position, "4");
    await user.clear(position);
    expect(add).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(create).not.toHaveBeenCalled();

    await user.type(position, "7");
    expect(add).toBeEnabled();
  });
});

/** A project's Create Task, where the task starts as Bug. */
const AddingTask = ({
  types,
  create,
  onOpenChange = () => {},
  laidOut = false,
}: {
  types: TaskTypeRead[];
  create: (written: Written<TaskRead, TaskUpdate>) => Promise<{ id: number }>;
  onOpenChange?: (open: boolean) => void;
  /** Its type's page is the project's own, as the server reads it. */
  laidOut?: boolean;
}) => {
  const leaving = useRef(false);
  const status = buildProjectTaskStatus();
  return (
    <AddItemDialog
      open
      onOpenChange={onOpenChange}
      detail={TASK_DETAIL}
      blank={blankTask(1, status, types[0])}
      context={{
        readOnly: false,
        readOnlyMessage: null,
        statuses: [status],
        types,
        initiativeId: 1,
        askScope: async () => null,
        actions: null,
        leaving,
      }}
      layouts={() => (laidOut ? { tool: "project", tool_id: 1 } : null)}
      title="Create task"
      ready={() => true}
      create={create}
      onAdded={() => {}}
    />
  );
};

describe("adding a task", () => {
  const bug = () =>
    buildTaskType({
      name: "Bug",
      starting_values: {
        description: "What happened?",
        checklist: [],
        priority: "high",
        recurrence: null,
        recurrence_strategy: null,
      },
    });

  const pickType = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name }));
  };

  it("shows its title, type and main column, with the rest folded until asked for", async () => {
    renderPage(() => (
      <AddingTask types={[bug(), buildTaskType({ name: "Feature" })]} create={vi.fn()} />
    ));
    const user = userEvent.setup();

    expect(await screen.findByRole("combobox", { name: "Type" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/task title/i)).toBeInTheDocument();
    expect(document.getElementById("task-description")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Priority" })).not.toBeInTheDocument();

    const more = screen.getByRole("button", { name: "More options" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("combobox", { name: "Priority" })).toBeInTheDocument();
    // The type is drawn up front, not again in the fold.
    expect(screen.getAllByRole("combobox", { name: "Type" })).toHaveLength(1);
  });

  it("puts what its type's page requires up front, and waits for it", async () => {
    const type = buildTaskType({ id: 1, name: "Feature" });
    server.use(
      communityHttp.get("/tags/", () => HttpResponse.json([buildTag({ id: 7, name: "Lore" })])),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: type.id,
                task_type_name: type.name,
                definition: {
                  side: [
                    {
                      type: "section",
                      children: [
                        { type: "field", props: { field: "priority" } },
                        { type: "field", props: { field: "tags", required: true } },
                      ],
                    },
                  ],
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[type]} create={create} laidOut />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(document.querySelector('[data-required-missing="tags"]')).toBeInTheDocument()
    );
    const tags = document.querySelector('[data-required-missing="tags"]') as HTMLElement;
    expect(within(tags).getByText("Required")).toBeVisible();
    // The rest of the side stays folded.
    expect(screen.queryByRole("combobox", { name: "Priority" })).not.toBeInTheDocument();
    const add = screen.getByRole("button", { name: "Create task" });
    expect(add).toBeDisabled();
    expect(screen.getByText("Fill in what is required to add it.")).toBeInTheDocument();

    await user.click(within(tags).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Lore" }));
    await waitFor(() => expect(add).toBeEnabled());
    expect(document.querySelector("[data-required-missing]")).not.toBeInTheDocument();
    await user.click(add);

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ fields: expect.objectContaining({ tag_ids: [7] }) })
      )
    );
  });

  it("takes a checklist a type requires, written before the task exists", async () => {
    const type = buildTaskType({ id: 1, name: "Packing" });
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: type.id,
                task_type_name: type.name,
                definition: {
                  main: [{ type: "field", props: { field: "checklist", required: true } }],
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[type]} create={create} laidOut />);
    const user = userEvent.setup();

    // Its page, once read, holds the checklist alone, marked.
    await waitFor(() =>
      expect(document.querySelector('[data-required-missing="checklist"]')).not.toBeNull()
    );
    const line = screen.getByPlaceholderText("Add checklist item");
    const add = screen.getByRole("button", { name: "Create task" });
    expect(add).toBeDisabled();
    await user.type(line, "Tent{Enter}");
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          fields: expect.objectContaining({
            checklist: [expect.objectContaining({ text: "Tent", done: false })],
          }),
        })
      )
    );
  });

  it("keeps More options open when the type changes the page", async () => {
    renderPage(() => (
      <AddingTask
        types={[
          buildTaskType({ name: "Feature" }),
          buildTaskType({ name: "Milestone", layout_preset: "dates" }),
        ]}
        create={vi.fn()}
      />
    ));
    const user = userEvent.setup();

    await screen.findByRole("combobox", { name: "Type" });
    await user.click(screen.getByRole("button", { name: "More options" }));
    await pickType(user, "Milestone");
    expect(screen.getByRole("button", { name: "More options" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
  });

  it("starts with what its type starts with, and follows the type until it is changed", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => (
      <AddingTask types={[bug(), buildTaskType({ name: "Feature" })]} create={create} />
    ));
    const user = userEvent.setup();

    // Written, it opens on its preview; the box behind it holds the text.
    await screen.findByRole("combobox", { name: "Type" });
    const description = document.getElementById("task-description");
    expect(description).toHaveValue("What happened?");
    await pickType(user, "Feature");
    expect(description).toHaveValue("");
    await pickType(user, "Bug");
    expect(description).toHaveValue("What happened?");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ description: "What happened?", priority: "high" }),
        })
      )
    );
  });

  it("keeps a description the person wrote when the type changes", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => (
      <AddingTask types={[buildTaskType({ name: "Feature" }), bug()]} create={create} />
    ));
    const user = userEvent.setup();

    const description = await screen.findByRole("textbox", { name: "Description" });
    await user.type(description, "Mine");
    await pickType(user, "Bug");

    expect(description).toHaveValue("Mine");
  });

  it("keeps a priority the person picked when the type changes", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    const [feature, chore] = [
      buildTaskType({ name: "Feature" }),
      buildTaskType({
        name: "Chore",
        starting_values: {
          description: null,
          checklist: [],
          priority: "low",
          recurrence: null,
          recurrence_strategy: null,
        },
      }),
    ];
    renderPage(() => <AddingTask types={[feature, chore]} create={create} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "More options" }));
    await user.click(screen.getByRole("combobox", { name: "Priority" }));
    await user.click(await screen.findByRole("option", { name: /Urgent/ }));
    await pickType(user, "Chore");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ task_type_id: chore.id, priority: "urgent" }),
        })
      )
    );
  });
});

/** A reader who keeps their titles as typed. */
const asTyped = { auth: { user: buildUser({ smart_task_titles: false }) } };

/** What the last Create task was given. */
const sent = (create: ReturnType<typeof vi.fn>) =>
  (create.mock.calls.at(-1)?.[0] as Written<TaskRead, TaskUpdate>) ?? null;

describe("adding a task with its title read", () => {
  const reader = { auth: { user: buildUser({ smart_task_titles: true }) } };

  it("sets what the title says on the task, and adds it without those words", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, reader);
    const user = userEvent.setup();

    const title = await screen.findByPlaceholderText(/task title/i);
    await user.type(title, "Fix the login tomorrow at 9am !urgent");
    expect(title).toHaveValue("Fix the login tomorrow at 9am !urgent");
    const read = screen.getByRole("list", { name: "Read from the title" });
    expect(read).toHaveTextContent(/urgent priority/i);
    expect(read).toHaveTextContent(/due/i);
    // Enter adds it straight from the title.
    await user.keyboard("{Enter}");

    await waitFor(() => expect(create).toHaveBeenCalled());
    const { item, fields } = sent(create);
    expect(fields).toMatchObject({ title: "Fix the login", priority: "urgent" });
    expect(item.priority).toBe("urgent");
    const due = new Date(fields.due_date as string);
    expect(due.getHours()).toBe(9);
  });

  it("puts a field back once its words are gone", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, reader);
    const user = userEvent.setup();

    const title = await screen.findByPlaceholderText(/task title/i);
    await user.type(title, "Fix the login !urgent");
    await user.type(title, "{Backspace}".repeat(" !urgent".length));
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    const { item, fields } = sent(create);
    expect(fields.title).toBe("Fix the login");
    expect(item.priority).toBe("medium");
  });

  it("keeps words in the title once they are taken off the list", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, reader);
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText(/task title/i), "Fix the login !urgent");
    await user.click(screen.getByRole("button", { name: "Keep “!urgent” in the title" }));
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    const { item, fields } = sent(create);
    expect(fields.title).toBe("Fix the login !urgent");
    expect(item.priority).toBe("medium");
  });

  it("adds the title as typed where the reader has it off", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, asTyped);
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText(/task title/i), "Fix the login !urgent");
    expect(screen.queryByRole("list", { name: "Read from the title" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(sent(create).fields.title).toBe("Fix the login !urgent");
  });
});

describe("naming somebody in a task's title", () => {
  const reader = { auth: { user: buildUser({ smart_task_titles: true }) } };
  const sam = buildUserSummary({ id: 42, username: "sam", display_name: "Sam Vimes" });
  const stubPeople = () => {
    const asked: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/users/search", ({ request }) => {
        asked.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: [sam],
          total_count: 1,
          page: 1,
          page_size: 8,
          has_next: false,
          has_prev: false,
        });
      })
    );
    return asked;
  };

  it("offers the people who can open the project, and assigns the one picked", async () => {
    const asked = stubPeople();
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, reader);
    const user = userEvent.setup();

    const title = await screen.findByPlaceholderText(/task title/i);
    await user.type(title, "Review the draft @sa");
    await user.click(await screen.findByRole("button", { name: /Sam Vimes/ }));

    expect(title).toHaveValue("Review the draft @sam ");
    expect(asked.some((params) => params.get("tool") === "project")).toBe(true);
    const read = screen.getByRole("list", { name: "Read from the title" });
    expect(read).toHaveTextContent("Sam Vimes");
    // The task's own Assignees field shows them too.
    await user.click(screen.getByRole("button", { name: "More options" }));
    expect(await screen.findByRole("button", { name: /remove sam vimes/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(sent(create).fields).toMatchObject({
      title: "Review the draft",
      assignee_ids: [42],
    });
  });

  it("counts the people and the repeat it is sent with as filled in", async () => {
    stubPeople();
    const type = buildTaskType({ id: 1 });
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: type.id,
                task_type_name: type.name,
                definition: {
                  side: [
                    { type: "field", props: { field: "assignees", required: true } },
                    { type: "field", props: { field: "recurrence", required: true } },
                  ],
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[type]} create={create} laidOut />, reader);
    const user = userEvent.setup();

    const title = await screen.findByPlaceholderText(/task title/i);
    const add = screen.getByRole("button", { name: "Create task" });
    await waitFor(() =>
      expect(document.querySelectorAll("[data-required-missing]")).toHaveLength(2)
    );
    await user.type(title, "Review @sa");
    await user.click(await screen.findByRole("button", { name: /Sam Vimes/ }));
    await waitFor(() =>
      expect(document.querySelector('[data-required-missing="assignees"]')).toBeNull()
    );
    expect(add).toBeDisabled();

    await user.click(screen.getByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Daily" }));
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(sent(create).fields).toMatchObject({
      assignee_ids: [42],
      recurrence: expect.stringContaining("FREQ=DAILY"),
    });
  });

  it("picks with Enter rather than adding the task", async () => {
    stubPeople();
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <AddingTask types={[buildTaskType()]} create={create} />, reader);
    const user = userEvent.setup();

    const title = await screen.findByPlaceholderText(/task title/i);
    await user.type(title, "Review @sa");
    await screen.findByRole("button", { name: /Sam Vimes/ });
    await user.keyboard("{Enter}");

    expect(title).toHaveValue("Review @sam ");
    expect(create).not.toHaveBeenCalled();
  });

  it("closes the list on Escape and leaves the dialog open", async () => {
    stubPeople();
    const onOpenChange = vi.fn();
    renderPage(
      () => (
        <AddingTask
          types={[buildTaskType()]}
          create={vi.fn(async () => ({ id: 5 }))}
          onOpenChange={onOpenChange}
        />
      ),
      reader
    );
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText(/task title/i), "Review @sa");
    await screen.findByRole("button", { name: /Sam Vimes/ });
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Sam Vimes/ })).not.toBeInTheDocument()
    );
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("offers nobody where the reader has titles read as typed", async () => {
    const asked = stubPeople();
    renderPage(
      () => <AddingTask types={[buildTaskType()]} create={vi.fn(async () => ({ id: 5 }))} />,
      asTyped
    );
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText(/task title/i), "Review @sa");
    expect(screen.queryByRole("button", { name: /Sam Vimes/ })).not.toBeInTheDocument();
    expect(asked).toHaveLength(0);
  });
});
