import { describe, expect, it } from "vitest";

import {
  buildTagSummary,
  buildTask,
  buildTaskAssignee,
  buildTaskType,
} from "@/__tests__/factories";
import type { TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { createRecurrenceFromPreset, type RecurrenceRule, shiftFor } from "@/lib/recurrence";
import type { TitlePerson, TitleReading } from "@/lib/smartTitle";

import { NOTHING_APPLIED, readingCreate, readingEdit } from "./smartTaskTitle";

const DUE = new Date(2026, 9, 23, 15, 0);

const reading = (overrides: Partial<TitleReading> = {}): TitleReading => ({
  title: "Send the invoice",
  parts: [],
  due: null,
  dueHasTime: false,
  priority: null,
  repeat: null,
  repeatStrategy: "fixed",
  tags: [],
  people: [],
  type: null,
  ...overrides,
});

const sam: TitlePerson = {
  id: 2,
  username: "sam",
  discriminator: 1,
  display_name: null,
  avatar_url: null,
  status: "active",
};

const blank = (overrides: Partial<TaskRead> = {}): TaskRead =>
  ({
    ...buildTask(),
    title: "",
    due_date: null,
    priority: "medium",
    tags: [],
    assignees: [],
    ...overrides,
  }) as TaskRead;

describe("readingEdit", () => {
  it("sends nothing until the reading moves", () => {
    const task = blank();
    const { edit } = readingEdit(task, reading({ title: "" }), { ...NOTHING_APPLIED, title: "" });
    expect(edit).toBeNull();
  });

  it("sets what the title says, and shows it on the fields", () => {
    const tag = buildTagSummary({ id: 9, name: "billing" });
    const { edit } = readingEdit(
      blank(),
      reading({ due: DUE, priority: "high", tags: [tag], people: [sam] }),
      NOTHING_APPLIED
    );
    expect(edit?.patch).toMatchObject({
      title: "Send the invoice",
      due_date: DUE.toISOString(),
      priority: "high",
      tag_ids: [9],
      assignee_ids: [2],
    });
    expect(edit?.shows).toMatchObject({
      due_date: DUE.toISOString(),
      priority: "high",
      tags: [tag],
    });
    expect(edit?.shows.assignees?.map((person) => person.id)).toEqual([2]);
    expect(edit?.shows).not.toHaveProperty("title");
  });

  it("puts a field back as it was once its words are gone", () => {
    const task = blank({ priority: "low" });
    const first = readingEdit(task, reading({ due: DUE, priority: "urgent" }), NOTHING_APPLIED);
    const after = blank({ priority: "urgent", due_date: DUE.toISOString() });
    const { edit } = readingEdit(after, reading(), first.applied);
    expect(edit?.patch).toEqual({ due_date: null, priority: "low" });
  });

  it("keeps a field picked by hand once the title's words for it go", () => {
    const task = blank({ priority: "low" });
    const first = readingEdit(task, reading({ due: DUE, priority: "high" }), NOTHING_APPLIED);
    // Both changed by hand since the title set them.
    const picked = blank({ priority: "urgent", due_date: "2026-12-01T00:00:00.000Z" });
    const { edit } = readingEdit(picked, reading(), first.applied);
    expect(edit).toBeNull();
  });

  it("does not set over a field picked by hand when the title says something new", () => {
    const first = readingEdit(blank(), reading({ priority: "high" }), NOTHING_APPLIED);
    const picked = blank({ priority: "urgent" });
    const { edit, applied } = readingEdit(picked, reading({ priority: "low" }), first.applied);
    expect(edit).toBeNull();
    expect(applied.priority).toBe("low");
  });

  it("leaves a field alone that the reading did not change", () => {
    const first = readingEdit(blank(), reading({ due: DUE }), NOTHING_APPLIED);
    // The due date was picked by hand since; the title typed on.
    const task = blank({ due_date: "2026-12-01T00:00:00.000Z" });
    const { edit } = readingEdit(
      task,
      reading({ title: "Send the invoices", due: DUE }),
      first.applied
    );
    expect(edit?.patch).toEqual({ title: "Send the invoices" });
  });

  it("keeps the tags and people picked by hand beside the ones it names", () => {
    const picked = buildTagSummary({ id: 1, name: "picked" });
    const named = buildTagSummary({ id: 9, name: "billing" });
    const alex = buildTaskAssignee({ id: 3 });
    const task = blank({ tags: [picked], assignees: [alex] });
    const first = readingEdit(task, reading({ tags: [named], people: [sam] }), NOTHING_APPLIED);
    expect(first.edit?.patch.tag_ids).toEqual([1, 9]);
    expect(first.edit?.patch.assignee_ids).toEqual([3, 2]);

    const now = blank({ tags: [picked, named], assignees: [alex] });
    const { edit } = readingEdit(now, reading(), first.applied);
    expect(edit?.patch.tag_ids).toEqual([1]);
    expect(edit?.patch.assignee_ids).toEqual([3]);
  });

  it("sets a repeat, and takes it off", () => {
    const rule = createRecurrenceFromPreset("daily");
    const first = readingEdit(blank(), reading({ due: DUE, repeat: rule }), NOTHING_APPLIED);
    expect(first.edit?.patch).toMatchObject({
      recurrence: "RRULE:FREQ=DAILY",
      recurrence_strategy: "fixed",
    });
    expect(first.edit?.patch.tz).toBeTruthy();
    expect(first.edit?.shows.recurrence).toBe("RRULE:FREQ=DAILY");
    const { edit } = readingEdit(blank(), reading({ due: DUE }), first.applied);
    expect(edit?.patch).toEqual({ recurrence: null });
  });
});

describe("readingEdit — task types", () => {
  const PLAIN = buildTaskType({ id: 1, name: "Task" });
  const BUG = buildTaskType({
    id: 2,
    name: "Bug",
    starting_values: {
      description: "What happened?",
      checklist: [],
      priority: "high",
      recurrence: null,
      recurrence_strategy: null,
    },
  });
  const typed = (overrides: Partial<TaskRead> = {}) =>
    blank({ task_type_id: PLAIN.id, task_type: PLAIN, description: null, ...overrides });
  /** The task as the add dialog shows it once an edit is taken. */
  const shown = (task: TaskRead, shows: Partial<TaskRead> | undefined) =>
    ({ ...task, ...shows }) as TaskRead;

  it("sets the type, with what it starts with", () => {
    const { edit } = readingEdit(typed(), reading({ type: BUG }), NOTHING_APPLIED);
    expect(edit?.patch).toMatchObject({
      task_type_id: BUG.id,
      description: "What happened?",
      priority: "high",
    });
    expect(edit?.shows).toMatchObject({ task_type_id: BUG.id, task_type: BUG, priority: "high" });
  });

  it("goes back to the type it had once its words go", () => {
    const task = typed();
    const first = readingEdit(task, reading({ type: BUG }), NOTHING_APPLIED);
    const { edit } = readingEdit(shown(task, first.edit?.shows), reading(), first.applied);
    expect(edit?.patch).toEqual({
      task_type_id: PLAIN.id,
      description: null,
      priority: "medium",
    });
  });

  it("keeps a type picked by hand once the title's words for it go", () => {
    const first = readingEdit(typed(), reading({ type: BUG }), NOTHING_APPLIED);
    const other = buildTaskType({ id: 3, name: "Idea" });
    const picked = typed({ task_type_id: other.id, task_type: other });
    const { edit } = readingEdit(picked, reading(), first.applied);
    expect(edit).toBeNull();
  });

  it("sets nothing when the title names the type the task already is", () => {
    const { edit } = readingEdit(typed(), reading({ type: PLAIN }), {
      ...NOTHING_APPLIED,
      title: "Send the invoice",
    });
    expect(edit).toBeNull();
  });

  it("sets the title's priority over the type's, and goes back to the type's", () => {
    const task = typed();
    const first = readingEdit(task, reading({ type: BUG, priority: "low" }), NOTHING_APPLIED);
    expect(first.edit?.patch).toMatchObject({ task_type_id: BUG.id, priority: "low" });
    const { edit } = readingEdit(
      shown(task, first.edit?.shows),
      reading({ type: BUG }),
      first.applied
    );
    expect(edit?.patch).toEqual({ priority: "high" });
  });

  it("moves what the title's priority goes back to when the type comes after it", () => {
    const task = typed();
    const first = readingEdit(task, reading({ priority: "low" }), NOTHING_APPLIED);
    const second = readingEdit(
      shown(task, first.edit?.shows),
      reading({ type: BUG, priority: "low" }),
      first.applied
    );
    expect(second.edit?.patch).toMatchObject({ task_type_id: BUG.id });
    expect(second.edit?.patch).not.toHaveProperty("priority");
    const now = shown(shown(task, first.edit?.shows), second.edit?.shows);
    const { edit } = readingEdit(now, reading({ type: BUG }), second.applied);
    expect(edit?.patch).toEqual({ priority: "high" });
  });
});

describe("readingEdit — repeats that need more than a rule", () => {
  it("counts an hourly repeat from completion, and shows it as the server keeps it", () => {
    const rule = { ...createRecurrenceFromPreset("hourly"), interval: 4 } as RecurrenceRule;
    const { edit } = readingEdit(
      blank(),
      reading({ due: DUE, repeat: rule, repeatStrategy: "rolling" }),
      NOTHING_APPLIED
    );
    expect(edit?.patch).toMatchObject({
      recurrence: "RRULE:FREQ=HOURLY;INTERVAL=4",
      recurrence_strategy: "rolling",
      recurrence_limit: null,
    });
    expect(edit?.shows.recurrence_shift).toBe(shiftFor(rule, DUE));
  });

  it("shows the repeat with the shift of the due date the task keeps", () => {
    const rule = { ...createRecurrenceFromPreset("weekly", DUE.toISOString()) } as RecurrenceRule;
    const first = readingEdit(blank(), reading({ due: DUE }), NOTHING_APPLIED);
    // A due date picked by hand since, early in the UTC day: its local date
    // is another day wherever the zone is not UTC.
    const picked = "2026-12-01T00:30:00.000Z";
    const { edit } = readingEdit(
      blank({ due_date: picked }),
      reading({ due: DUE, repeat: rule }),
      first.applied
    );
    expect(edit?.patch).not.toHaveProperty("due_date");
    expect(edit?.shows.recurrence_shift).toBe(shiftFor(rule, new Date(picked)));
  });

  it("works the shift out again when the title's date moves under its repeat", () => {
    const rule = createRecurrenceFromPreset("daily") as RecurrenceRule;
    const first = readingEdit(blank(), reading({ due: DUE, repeat: rule }), NOTHING_APPLIED);
    const later = new Date(2026, 11, 1, 0, 30);
    const { edit } = readingEdit(
      blank({ due_date: DUE.toISOString(), recurrence: "RRULE:FREQ=DAILY" }),
      reading({ due: later, repeat: rule }),
      first.applied
    );
    expect(edit?.patch.due_date).toBe(later.toISOString());
    expect(edit?.shows.recurrence_shift).toBe(shiftFor(rule, later));
  });

  it("sends a changed strategy even when the rule reads the same", () => {
    const rule = createRecurrenceFromPreset("daily") as RecurrenceRule;
    const first = readingEdit(blank(), reading({ due: DUE, repeat: rule }), NOTHING_APPLIED);
    const { edit } = readingEdit(
      blank(),
      reading({ due: DUE, repeat: rule, repeatStrategy: "rolling" }),
      first.applied
    );
    expect(edit?.patch.recurrence_strategy).toBe("rolling");
  });
});

describe("readingCreate", () => {
  it("adds what the title says beside who the task already goes to", () => {
    const tag = buildTagSummary({ id: 9, name: "billing" });
    expect(
      readingCreate(reading({ due: DUE, priority: "high", tags: [tag], people: [sam] }), [7])
    ).toEqual({
      title: "Send the invoice",
      due_date: DUE.toISOString(),
      priority: "high",
      tag_ids: [9],
      assignee_ids: [7, 2],
    });
  });

  it("adds the type the title names", () => {
    const type = buildTaskType({ id: 4, name: "Bug" });
    expect(readingCreate(reading({ type }))).toEqual({
      title: "Send the invoice",
      task_type_id: 4,
    });
  });

  it("adds only the title when nothing else was read", () => {
    expect(readingCreate(reading())).toEqual({ title: "Send the invoice" });
  });
});
