import { Link } from "@tanstack/react-router";
import { Ban, CornerLeftUp, MessageSquare } from "lucide-react";
import { memo } from "react";

import type {
  ChecklistProgress,
  DetailLayoutDefinitionInput,
  PropertyDefinitionRead,
  TagSummary,
  TaskAssigneeSummary,
  TaskListRead,
  TaskParentSummary,
  TaskPriority,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { TagBadge } from "@/components/tags";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TaskTypeMark, TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { priorityVariant } from "@/components/tools/projects/projectTasksConfig";
import { TaskAssigneeList, TaskAssigneeStack } from "@/components/tools/projects/TaskAssigneeList";
import { TaskBlockersHoverCard } from "@/components/tools/projects/TaskBlockersHoverCard";
import { TaskDescriptionHoverCard } from "@/components/tools/projects/TaskDescriptionHoverCard";
import { TaskSubtasksHoverCard } from "@/components/tools/projects/TaskSubtasksHoverCard";
import { MentionText } from "@/components/user/MentionText";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import {
  ASSIGNEE_ME,
  ASSIGNEE_NONE,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  tableSortFields,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import { summarizeStored } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { entityRefRoute } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { at, detailLayoutSpec, type Region, storedLayout } from "@/ui/layouts/detailLayout";
import type { ListShape } from "@/ui/layouts/draft";
import {
  ExcerptField,
  type FieldDef,
  type FieldRendererProps,
  type LayoutEnv,
  propertyFieldId,
  propertyFields,
  TitleField,
} from "@/ui/layouts/fields";
import type { PresetKind } from "@/ui/layouts/presets";
import type { LayoutNode } from "@/ui/layouts/tree";
import { cn } from "@/ui/lib/utils";
import { listedValue } from "@/ui/properties/propertyHelpers";

// A table's title cell carries what the card shows as fields of their own,
// where the table has no column for it.
const TitleCell = ({
  title,
  task,
  type,
  unread,
  env,
}: {
  title: string;
  task: TaskListRead;
  type: TaskTypeRead | null;
  unread: boolean;
  env: LayoutEnv<TaskListRead>;
}) => {
  const recurrence = task.recurrence
    ? summarizeStored(
        task.recurrence,
        task.due_date || task.start_date,
        {
          strategy: task.recurrence_strategy,
          shift: task.recurrence_shift,
          limit: task.recurrence_limit,
        },
        env.t
      )
    : null;
  return (
    <div className="flex w-full min-w-60 items-center gap-2">
      <div className="flex min-w-0 flex-1 flex-col items-start text-left">
        <div className="flex items-start gap-1.5">
          {/* One line of the title tall, so it sits on the first line's middle. */}
          {type ? <TaskTypeMark type={type} className="h-lh" /> : null}
          <Link
            to={env.itemHref(task)}
            draggable={false}
            className="flex items-center gap-2 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
          >
            {title}
            {unread ? <UnreadDot /> : null}
          </Link>
        </div>
        {recurrence ? (
          <p className="text-muted-foreground text-xs">{truncateText(recurrence, 100)}</p>
        ) : null}
        <TaskChecklistProgress progress={task.checklist_progress} className="mt-2 max-w-[200px]" />
      </div>
      <TaskSubtasksHoverCard task={task} />
      <TaskBlockersHoverCard task={task} />
      <TaskDescriptionHoverCard task={task} />
    </div>
  );
};

// A task's title, marked while it is unread. A project with one type draws
// none in its cells: the type tells nothing apart.
const TaskTitle = ({ typed, ...props }: FieldRendererProps<TaskListRead> & { typed: boolean }) => {
  const { value, item, variant, env } = props;
  const unread = useUnreadTree().hasSubject(item.community_id, "task", item.id);
  if (variant === "cell") {
    return (
      <TitleCell
        title={value as string}
        task={item}
        type={typed ? item.task_type : null}
        unread={unread}
        env={env}
      />
    );
  }
  return (
    <TitleField
      {...props}
      mark={unread ? <UnreadDot className="ml-2 inline-block align-middle" /> : null}
    />
  );
};

const TypedTitle = memo(function TypedTitle(props: FieldRendererProps<TaskListRead>) {
  return <TaskTitle {...props} typed />;
});

const UntypedTitle = memo(function UntypedTitle(props: FieldRendererProps<TaskListRead>) {
  return <TaskTitle {...props} typed={false} />;
});

// The people a task's words mention are drawn as chips.
const DescriptionField = memo(function DescriptionField(props: FieldRendererProps) {
  return (
    <ExcerptField {...props}>
      <MentionText text={props.value as string} />
    </ExcerptField>
  );
});

const AssigneesField = memo(function AssigneesField({ value, variant }: FieldRendererProps) {
  const people = value as TaskAssigneeSummary[];
  if (variant === "cell") {
    return people.length > 0 ? (
      <TaskAssigneeStack assignees={people} />
    ) : (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    );
  }
  return <TaskAssigneeList assignees={people} className="text-xs" />;
});

const RecurrenceField = memo(function RecurrenceField({
  value,
  item,
  env,
}: FieldRendererProps<TaskListRead>) {
  const summary = summarizeStored(
    value as string,
    item.due_date || item.start_date,
    {
      strategy: item.recurrence_strategy,
      shift: item.recurrence_shift,
      limit: item.recurrence_limit,
    },
    env.t
  );
  return summary ? <p>{truncateText(summary, 80)}</p> : null;
});

const ChecklistField = memo(function ChecklistField({ value }: FieldRendererProps) {
  return <TaskChecklistProgress progress={value as ChecklistProgress} className="w-full pt-1" />;
});

const SubtasksField = memo(function SubtasksField({ value }: FieldRendererProps) {
  return (
    <TaskChecklistProgress
      of="subtasks"
      progress={value as ChecklistProgress}
      className="w-full min-w-24 pt-1"
    />
  );
});

// The task this one is part of, as a link to it: on a card a line above what
// the card says, in a cell its name.
const ParentField = memo(function ParentField({ value, item, variant, env }: FieldRendererProps) {
  const parent = value as TaskParentSummary | null;
  if (!parent) {
    return variant === "cell" ? (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    ) : null;
  }
  return (
    <Link
      // By the task alone: a parent may be in another of the initiative's
      // projects, which a project's own task links would name wrongly.
      to={env.communityPath(entityRefRoute("task", parent.id), item)}
      draggable={false}
      title={env.t("tasks:subtasks.partOf", { title: parent.title })}
      className={cn(
        "flex min-w-0 max-w-full items-center gap-1 rounded-sm text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-1 focus-visible:ring-ring",
        variant === "cell" ? "text-sm" : "text-xs"
      )}
    >
      <CornerLeftUp className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="truncate">{parent.title}</span>
    </Link>
  );
});

const PriorityField = memo(function PriorityField({ value, field, env }: FieldRendererProps) {
  const priority = value as TaskPriority;
  const text = priority.replace("_", " ");
  return (
    <Badge variant={priorityVariant[priority]}>
      {field.phrase ? env.t(field.phrase, { priority: text }) : text}
    </Badge>
  );
});

const TagsField = memo(function TagsField({ value, item, variant, env }: FieldRendererProps) {
  const tags = value as TagSummary[];
  const tagHref = (tag: TagSummary) => env.communityPath(`/tags/${tag.id}`, item);
  if (variant === "cell") {
    return tags.length > 0 ? (
      <TagBadgeList tags={tags} tagHref={tagHref} />
    ) : (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    );
  }
  return tags.map((tag) => <TagBadge key={tag.id} tag={tag} size="sm" to={tagHref(tag)} />);
});

// A card shows a type by its icon alone, beside the title and named on hover;
// a cell names it.
const TaskTypeField = memo(function TaskTypeField({ value, variant }: FieldRendererProps) {
  const type = value as TaskTypeRead | null;
  if (!type) {
    return variant === "cell" ? (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    ) : null;
  }
  if (variant === "cell") return <TaskTypeOption type={type} className="text-sm" />;
  // One line of the title tall, so the icon sits on the first line's middle.
  return <TaskTypeMark type={type} className="h-lh" iconClassName="h-4 w-4" />;
});

const builtin = (
  field: Omit<FieldDef<TaskListRead>, "source" | "label" | "hideable" | "requireable"> &
    Partial<FieldDef<TaskListRead>>
): FieldDef<TaskListRead> => ({
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
  plugins: FieldDef<TaskListRead>[] = [],
  { typed = true }: { typed?: boolean } = {}
): Map<string, FieldDef<TaskListRead>> => {
  const fields: FieldDef<TaskListRead>[] = [
    builtin({
      id: "title",
      kind: "title",
      // What a table's column has always been called.
      label: "table.taskColumn",
      hideable: false,
      value: (task) => task.title,
      // A table has no room for the card's icon of its own, so its title
      // cell draws it.
      render: typed ? TypedTitle : UntypedTitle,
    }),
    // A project with one type draws none: the type tells nothing apart.
    builtin({
      id: "type",
      render: TaskTypeField,
      value: (task) => (typed ? task.task_type : null),
    }),
    builtin({
      id: "description",
      kind: "excerpt",
      render: DescriptionField,
      requireable: true,
      value: (task) => task.description_excerpt,
    }),
    builtin({
      id: "assignees",
      render: AssigneesField,
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
      done: (task) => task.task_status?.category === "done",
      value: (task) => task.due_date,
    }),
    builtin({
      id: "recurrence",
      render: RecurrenceField,
      requireable: true,
      value: (task) => task.recurrence,
    }),
    builtin({
      id: "checklist",
      render: ChecklistField,
      requireable: true,
      value: (task) => task.checklist_progress,
    }),
    // How far the tasks that are part of this one have got, and the task
    // this one is part of.
    builtin({ id: "subtasks", render: SubtasksField, value: (task) => task.subtask_progress }),
    builtin({ id: "parent", render: ParentField, value: (task) => task.parent }),
    builtin({
      id: "priority",
      render: PriorityField,
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
    builtin({ id: "tags", render: TagsField, requireable: true, value: (task) => task.tags }),
    ...propertyFields<TaskListRead>(definitions, (task, definition) =>
      listedValue(task.properties, definition)
    ),
    ...plugins,
  ];
  return new Map(fields.map((field) => [field.id, field]));
};

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

// A table's column for a task's field, where its id is not the field's: what
// stored visibility, grouping and sorting are keyed by.
const TASK_COLUMN_OF: Readonly<Record<string, string>> = {
  startDate: "start date",
  dueDate: "due date",
};

/** The id of the table column that draws a task's field. */
export const taskColumnId = (fieldId: string): string => TASK_COLUMN_OF[fieldId] ?? fieldId;

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

/** A project's lists, of its tasks. */
export const TASK_LIST_SHAPE: ListShape = {
  card: TASK_CARD,
  columns: TASK_COLUMNS,
  columnFields: new Set(TASK_COLUMNS),
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

/** A project's lists' presets, which ship three; one a table keeps also
 *  sorts it. */
export const TASK_PRESETS: PresetKind<TaskFilterSpec> = {
  shipped: [
    {
      slug: "incomplete",
      nameKey: "presets.incomplete",
      filters: { status_categories: ["backlog", "todo", "in_progress"] },
    },
    { slug: "unassigned", nameKey: "presets.unassigned", filters: { assignees: [ASSIGNEE_NONE] } },
    { slug: "mine", nameKey: "presets.mine", filters: { assignees: [ASSIGNEE_ME] } },
  ],
  read: (raw) => specFromStored(raw as StoredTaskFilters | undefined),
  sorting: { read: taskTableSorting, stored: tableSortFields },
};
