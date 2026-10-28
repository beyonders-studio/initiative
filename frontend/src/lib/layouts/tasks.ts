import { Ban, MessageSquare } from "lucide-react";

import {
  type DetailLayoutDefinitionInput,
  MetadataType,
  type PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";
import { namePropertyColumns } from "@/components/properties/propertyColumns";
import { isEmptyPropertyValue } from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";

import { at, detailLayoutSpec, type Region, storedLayout } from "./detailLayout";
import { type FieldDef, propertyFieldId } from "./fields";
import type { LayoutNode } from "./tree";

const builtin = (
  field: Omit<FieldDef, "source" | "label" | "hideable" | "requireable"> & Partial<FieldDef>
): FieldDef => ({
  source: "builtin",
  label: `kanban.fields.${field.id}`,
  hideable: true,
  requireable: false,
  ...field,
});

/**
 * Everything a task view can show: the built-ins, then one field per property
 * the initiative defines, then the plug-ins' (`pluginFields`). Each is keyed
 * by the id a view stores it under, which a table's column shares; two
 * properties that share a name are told apart in their labels.
 */
export const taskFields = (
  definitions: PropertyDefinitionRead[],
  plugins: FieldDef[] = [],
  { typed = true }: { typed?: boolean } = {}
): Map<string, FieldDef> => {
  const fields: FieldDef[] = [
    builtin({
      id: "title",
      kind: "title",
      // What a table's column has always been called.
      label: "table.taskColumn",
      hideable: false,
      value: (task) => task.title,
      // A table has no room for the card's icon of its own, so its title
      // cell draws it.
      typeOf: (task) => (typed ? task.task_type : null),
    }),
    // A project with one type draws none: the type tells nothing apart.
    builtin({ id: "type", kind: "taskType", value: (task) => (typed ? task.task_type : null) }),
    builtin({
      id: "description",
      kind: "excerpt",
      requireable: true,
      value: (task) => task.description_excerpt,
    }),
    builtin({
      id: "assignees",
      kind: "people",
      requireable: true,
      value: (task) => task.assignees,
    }),
    builtin({
      id: "startDate",
      kind: "date",
      phrase: "kanban.starts",
      past: "primary",
      value: (task) => task.start_date,
    }),
    builtin({
      id: "dueDate",
      kind: "date",
      phrase: "kanban.due",
      past: "destructive",
      value: (task) => task.due_date,
    }),
    builtin({
      id: "recurrence",
      kind: "recurrence",
      requireable: true,
      value: (task) => task.recurrence,
    }),
    builtin({
      id: "checklist",
      kind: "checklist",
      requireable: true,
      value: (task) => task.checklist_progress,
    }),
    // How far the tasks that are part of this one have got, and the task
    // this one is part of.
    builtin({ id: "subtasks", kind: "subtasks", value: (task) => task.subtask_progress }),
    builtin({ id: "parent", kind: "parent", value: (task) => task.parent }),
    builtin({
      id: "priority",
      kind: "priority",
      phrase: "kanban.priority",
      value: (task) => task.priority,
    }),
    // A count of none shows nothing.
    builtin({
      id: "comments",
      kind: "count",
      icon: MessageSquare,
      value: (task) => task.comment_count || null,
    }),
    // The signal the retired Blocked column used to give, keeping itself
    // current: it goes when the last thing holding this up is finished.
    builtin({
      id: "blockers",
      kind: "count",
      icon: Ban,
      tone: "warning",
      phrase: "relations:blockers.label",
      value: (task) => task.blocked_by_open_count || null,
    }),
    builtin({ id: "tags", kind: "tags", requireable: true, value: (task) => task.tags }),
    ...propertyFields(definitions, (task, id) => {
      const summary = task.properties?.find((s) => s.property_id === id);
      return summary && !isEmptyPropertyValue(summary.value) ? summary : null;
    }),
    ...plugins,
  ];
  return new Map(fields.map((field) => [field.id, field]));
};

/** One field per property the initiative defines, two that share a name told
 *  apart in their labels; `read` reads one's value off an item. */
export const propertyFields = (
  definitions: PropertyDefinitionRead[],
  read: (item: Parameters<FieldDef["value"]>[0], definitionId: number) => unknown
): FieldDef[] =>
  namePropertyColumns(definitions).map(({ definition, label }) => ({
    id: propertyFieldId(definition.id),
    kind: "property",
    source: "property",
    label,
    hideable: true,
    // A checkbox is always on or off, so never empty.
    requireable: definition.type !== MetadataType.checkbox,
    icon: iconForPropertyType(definition.type),
    value: (item) => read(item, definition.id),
    property: definition,
  }));

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/** The table's columns as shipped, in order: the fields it draws as columns. */
export const TASK_COLUMNS = [
  "title",
  "assignees",
  "startDate",
  "dueDate",
  "priority",
  "tags",
  "comments",
];

/** The board's card as shipped. */
export const TASK_CARD: LayoutNode = {
  type: "card",
  children: [
    {
      type: "stack",
      props: { align: "start" },
      children: [
        // What the task is a piece of, above what it is called.
        field("parent"),
        // The type's icon leads the name it qualifies.
        {
          type: "stack",
          props: { direction: "row", gap: "sm", align: "start" },
          children: [field("type"), field("title")],
        },
        field("description"),
        {
          type: "stack",
          props: { tone: "muted" },
          children: [field("assignees"), field("startDate"), field("dueDate"), field("recurrence")],
        },
        field("checklist"),
        field("subtasks"),
      ],
    },
    {
      type: "stack",
      props: { direction: "row", gap: "sm", wrap: true },
      children: [
        field("priority"),
        field("comments"),
        field("blockers"),
        field("tags"),
        { type: "properties" },
      ],
    },
  ],
};

/** What every task page has across the top: its title and what else can be
 *  done with it, who made it, and why it cannot be changed when it cannot. */
const TASK_HEADER: LayoutNode[] = [
  {
    type: "stack",
    props: { direction: "row", gap: "sm", align: "start" },
    children: [field("title"), { type: "actions" }],
  },
  { type: "byline" },
  { type: "notice" },
];

const section = (...children: LayoutNode[]): LayoutNode => ({ type: "section", children });

/**
 * A task's page as shipped (the `plain` shape): what the task is in the main
 * column, and the fields that place it beside them. On one column, the fields
 * follow the description.
 */
const PLAIN: Record<Region, LayoutNode[]> = {
  header: TASK_HEADER,
  main: [
    at(1, section(field("description"))),
    at(3, field("checklist")),
    at(4, { type: "case" }),
    at(6, { type: "comments" }),
  ],
  side: [
    at(
      2,
      section(
        field("type"),
        { type: "status" },
        field("priority"),
        field("assignees"),
        { type: "dates" },
        field("recurrence"),
        field("tags"),
        { type: "properties" }
      )
    ),
    at(5, { type: "relations" }),
  ],
};

/**
 * The shapes a type's page is drawn as until it is changed, each leading with
 * something different (`TaskTypeRead.layout_preset`). A shape leaves out what
 * its kind of task rarely needs; nothing is lost by that, and the layout
 * editor puts it back.
 */
const TASK_SHAPES: Record<string, Record<Region, LayoutNode[]>> = {
  plain: PLAIN,
  // Something broken: how urgent it is and what it holds up come first.
  fix: {
    header: TASK_HEADER,
    main: [
      at(1, section(field("description"))),
      at(4, field("checklist")),
      at(5, { type: "case" }),
      at(6, { type: "comments" }),
    ],
    side: [
      at(
        2,
        section(
          field("type"),
          field("priority"),
          { type: "status" },
          field("assignees"),
          { type: "dates" },
          field("tags"),
          { type: "properties" }
        )
      ),
      at(3, { type: "relations" }),
    ],
  },
  // Something to talk over: the idea and the conversation are the page.
  discussion: {
    header: TASK_HEADER,
    main: [
      at(1, section(field("description"))),
      at(3, { type: "comments" }),
      at(5, { type: "case" }),
    ],
    side: [
      at(
        2,
        section(field("type"), { type: "status" }, field("assignees"), field("tags"), {
          type: "properties",
        })
      ),
      at(4, { type: "relations" }),
    ],
  },
  // A date to reach: when, and what is still in the way, come first.
  dates: {
    header: TASK_HEADER,
    main: [
      at(1, section(field("description"))),
      at(3, { type: "relations" }),
      at(4, field("checklist")),
      at(5, { type: "case" }),
      at(6, { type: "comments" }),
    ],
    side: [
      at(
        2,
        section(
          field("type"),
          { type: "dates" },
          { type: "status" },
          field("assignees"),
          field("priority"),
          field("tags"),
          { type: "properties" }
        )
      ),
    ],
  },
  // Something that comes round again: how often comes first.
  repeat: {
    header: TASK_HEADER,
    main: [
      at(1, section(field("description"))),
      at(3, field("checklist")),
      at(4, { type: "case" }),
      at(6, { type: "comments" }),
    ],
    side: [
      at(
        2,
        section(
          field("type"),
          field("recurrence"),
          { type: "dates" },
          { type: "status" },
          field("assignees"),
          field("priority"),
          field("tags"),
          { type: "properties" }
        )
      ),
      at(5, { type: "relations" }),
    ],
  },
  // A list to work through: the checklist is the task.
  checklist: {
    header: TASK_HEADER,
    main: [
      at(1, field("checklist")),
      at(3, section(field("description"))),
      at(4, { type: "case" }),
      at(6, { type: "comments" }),
    ],
    side: [
      at(
        2,
        section(
          field("type"),
          { type: "status" },
          field("assignees"),
          { type: "dates" },
          field("recurrence"),
          field("priority"),
          field("tags"),
          { type: "properties" }
        )
      ),
      at(5, { type: "relations" }),
    ],
  },
};

const shapeSpec = (shipped: Record<Region, LayoutNode[]>) =>
  detailLayoutSpec({
    kind: "task",
    shipped,
    fieldParts: ["field", "status", "dates", "properties"],
    // Its dates are filled in as one: either of them fills them.
    requiredParts: ["dates"],
    // Every shape has every part and field the plain one does, to place.
    knows: PLAIN,
  });

/** A task's detail: its status, dates and properties edit fields as a field does. */
export const TASK_LAYOUT = shapeSpec(PLAIN);

const SHAPE_SPECS = new Map(
  Object.entries(TASK_SHAPES).map(([shape, regions]) => [
    shape,
    shape === "plain" ? TASK_LAYOUT : shapeSpec(regions),
  ])
);

/** The page a type is drawn as until it is changed: its shape's, or the plain
 *  one for a shape this build does not know. */
export const taskLayoutFor = (shape: string | null | undefined) =>
  SHAPE_SPECS.get(shape ?? "plain") ?? TASK_LAYOUT;

/**
 * A type's page as its shape draws it, with these properties placed at the
 * end of the side's first section, as stored: what a ready-made type's fields
 * are given when it is added.
 */
export const taskPageWithFields = (
  shape: string | null | undefined,
  propertyIds: readonly number[]
): DetailLayoutDefinitionInput => {
  const stored = storedLayout(taskLayoutFor(shape).root(null));
  const fields = propertyIds.map((id) => field(propertyFieldId(id)));
  const side = [...((stored.side ?? []) as LayoutNode[])];
  const index = side.findIndex((node) => node.type === "section");
  if (index === -1) {
    side.push(section(...fields));
  } else {
    side[index] = { ...side[index], children: [...(side[index].children ?? []), ...fields] };
  }
  return { ...stored, side } as DetailLayoutDefinitionInput;
};
