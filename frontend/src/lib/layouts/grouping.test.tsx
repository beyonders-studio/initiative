import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildPropertyOption,
  buildTagSummary,
  buildTask,
  TASK_GROUPINGS,
} from "@/__tests__/factories";
import {
  type GroupsResponse,
  type LayoutGrouping,
  type ListLayoutReadKind,
  MetadataType,
  type TaskListRead,
} from "@/api/generated/initiativeAPI.schemas";
import { propertyFieldId } from "@/lib/layouts/fields";
import {
  boardBands,
  catalogChoices,
  groupables,
  groupRowId,
  groupRows,
  NO_GROUP,
  offeredGroupings,
  type ServedGroups,
  uniqueTasksFromRows,
  viewGrouping,
  withGroupShown,
} from "@/lib/layouts/grouping";
import { taskFields } from "@/lib/layouts/tasks";
import type { TranslateFn } from "@/types/i18n";

const t = ((key: string, options?: { defaultValue?: string }) =>
  options?.defaultValue ?? key) as TranslateFn;

const BUILT_INS = [
  "date_group",
  "priority",
  "task_status_id",
  "parent_task_id",
  "assignee_ids",
  "created_by",
  "tag_ids",
  "project_id",
];

const sprint = buildPropertyDefinition({
  name: "Sprint",
  type: MetadataType.multi_select,
  options: [buildPropertyOption({ value: "s1" }), buildPropertyOption({ value: "s2" })],
});
const note = buildPropertyDefinition({ name: "Note", type: MetadataType.text });
const sprintField = propertyFieldId(sprint.id);

const all = groupables(TASK_GROUPINGS, taskFields([sprint, note]), t);
const choices = catalogChoices(TASK_GROUPINGS);

const offered = (
  groupings: LayoutGrouping[] | null,
  {
    kind = "table",
    tasks = [],
    served,
  }: { kind?: ListLayoutReadKind; tasks?: TaskListRead[]; served?: ServedGroups } = {}
) =>
  offeredGroupings({
    all,
    groupings,
    kind,
    statuses: buildDefaultTaskStatuses(),
    tasks,
    served,
    t,
  });

const served = (field: string, data: GroupsResponse): ServedGroups => ({ field, data });

describe("what a list offers", () => {
  it("offers every field that groups without a bucket until its layout names its own", () => {
    expect(offered(null).map(({ grouping }) => grouping.id)).toEqual(BUILT_INS);
    expect(
      offered([
        { field: sprintField, hidden: ["s1"] },
        { field: "due_date", bucket: "month" },
        // A property the project no longer has, and one whose values don't group.
        { field: "property:999" },
        { field: propertyFieldId(note.id) },
      ]).map(({ grouping, hidden }) => [grouping.id, grouping.bucket ?? null, [...hidden]])
    ).toEqual([
      [sprintField, null, ["s1"]],
      ["due_date", "month", []],
    ]);
  });

  it("never offers a board its statuses, which its columns are", () => {
    expect(offered(null, { kind: "board" }).map(({ grouping }) => grouping.id)).toEqual(
      BUILT_INS.filter((id) => id !== "task_status_id")
    );
    expect(viewGrouping(undefined, "board", ["task_status_id group"], choices)).toEqual([]);
  });

  it("hides a group of one grouping, and shows it again", () => {
    const hidden = withGroupShown(null, "table", choices, "assignee_ids", NO_GROUP, false);

    expect(hidden.find((entry) => entry.field === "assignee_ids")?.hidden).toEqual([NO_GROUP]);
    expect(hidden.map((entry) => entry.field)).toEqual(BUILT_INS);
    expect(
      withGroupShown(hidden, "table", choices, "assignee_ids", NO_GROUP, true).find(
        (entry) => entry.field === "assignee_ids"
      )?.hidden
    ).toEqual([]);
  });

  it("starts on the layout's grouping until a person picks, and keeps their pick while offered", () => {
    const layout = {
      groupings: [{ field: "task_status_id" }, { field: sprintField }],
      group_by: "task_status_id",
    };

    expect(viewGrouping(layout, "table", null, choices)).toEqual(["task_status_id group"]);
    expect(viewGrouping(layout, "table", [], choices)).toEqual([]);
    expect(viewGrouping(layout, "table", [`${sprintField} group`], choices)).toEqual([
      `${sprintField} group`,
    ]);
    // A pick the list no longer offers goes back to where it starts.
    expect(viewGrouping(layout, "table", ["priority group"], choices)).toEqual([
      "task_status_id group",
    ]);
  });
});

describe("a grouping the server worked out", () => {
  const bug = buildTagSummary({ name: "bug" });
  const later = buildTagSummary({ name: "later" });
  const tagged = buildTask({ id: 7, tags: [bug, later] });
  const bare = buildTask({ id: 8, tags: [] });
  const byTag = served("tag_ids", {
    groups: [
      { key: String(later.id), label: "later" },
      { key: String(bug.id), label: "bug" },
      { key: NO_GROUP },
    ],
    rows: { "7": [String(bug.id), String(later.id)] },
  });
  const tags = () =>
    offered([{ field: "tag_ids" }], { tasks: [tagged, bare], served: byTag })[0].grouping;

  it("lists a task under each of its groups, and one in none in the empty group", () => {
    const rows = groupRows([tagged, bare], tags());

    expect(rows.map(groupRowId)).toEqual([`7::${bug.id}`, `7::${later.id}`, "8::"]);
    expect("group" in tagged).toBe(false);
  });

  it("orders its groups as the server does", () => {
    expect([NO_GROUP, String(bug.id), String(later.id)].sort(tags().compare)).toEqual([
      String(later.id),
      String(bug.id),
      NO_GROUP,
    ]);
  });

  it("knows nothing of a grouping it was not served", () => {
    const [priority] = offered([{ field: "priority" }], { tasks: [tagged], served: byTag });

    expect(priority.grouping.keys(tagged)).toEqual([]);
    expect(priority.grouping.values).toBeUndefined();
  });

  it("collapses a task's rows back to the task the list holds", () => {
    const selected = uniqueTasksFromRows(
      groupRows([tagged], tags()),
      new Map([[tagged.id, tagged]])
    );

    expect(selected).toEqual([tagged]);
    expect(selected[0]).toBe(tagged);
  });

  it("names a date's bucket by its first day", () => {
    const [due] = offered([{ field: "due_date", bucket: "year" }], {
      served: served("due_date", { groups: [{ key: "2026-01-01" }], rows: {} }),
    });
    render(<>{due.grouping.header("2026-01-01")}</>);

    expect(screen.getByText("2026")).toBeInTheDocument();
    expect(due.grouping.move).toBeUndefined();
  });
});

describe("a drop into another group", () => {
  const moveOf = (field: string) =>
    offered([{ field }]).find(({ grouping }) => grouping.id === field)?.grouping.move;

  it("moves a person off the group a task came from and onto the one it went to", () => {
    expect(moveOf("assignee_ids")?.("1", "2")).toEqual({
      patch: { add_assignee_ids: [2], remove_assignee_ids: [1] },
    });
    expect(moveOf("assignee_ids")?.("1", NO_GROUP)).toEqual({
      patch: { add_assignee_ids: [], remove_assignee_ids: [1] },
    });
  });

  it("changes one option of a multi-select, against what the task holds", () => {
    expect(moveOf(sprintField)?.("s1", "s2")).toEqual({
      properties: {
        merge: true,
        options: [{ property_id: sprint.id, add: ["s2"], remove: ["s1"] }],
      },
    });
  });

  it("puts a task dropped into a task's band under that task, and out of every band under none", () => {
    expect(moveOf("parent_task_id")?.("4", "7")).toEqual({ patch: { parent_task_id: 7 } });
    expect(moveOf("parent_task_id")?.("4", NO_GROUP)).toEqual({ patch: { parent_task_id: null } });
  });

  it("writes a status drop as the status, and nothing for a date window", () => {
    expect(moveOf("date_group")).toBeUndefined();
    expect(moveOf("task_status_id")?.("1", "2")).toEqual({ status: 2 });
  });
});

describe("boardBands", () => {
  it("bands every group the server lists, holding a task or not, and leaves out the hidden", () => {
    const urgent = buildTask({ id: 1, priority: "urgent" });
    const low = buildTask({ id: 2, priority: "low" });
    const [priorities] = offered([{ field: "priority", hidden: ["high"] }], {
      kind: "board",
      tasks: [urgent, low],
      served: served("priority", {
        groups: ["urgent", "high", "medium", "low"].map((key) => ({ key })),
        rows: { "1": ["urgent"], "2": ["low"] },
      }),
    });

    const bands = boardBands(priorities, [low, urgent]);

    expect(bands.map((band) => [band.key, band.tasks])).toEqual([
      ["urgent", [urgent]],
      ["medium", []],
      ["low", [low]],
    ]);
  });
});
