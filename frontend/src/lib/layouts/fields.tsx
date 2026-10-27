import { Link } from "@tanstack/react-router";
import { CornerLeftUp, type LucideIcon } from "lucide-react";
import { type ComponentType, memo, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  ChecklistProgress,
  FileSummary,
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
  TaskAssigneeSummary,
  TaskListRead,
  TaskParentSummary,
  TaskPriority,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { FileTypeBadge } from "@/components/files/fileColumns";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList, TaskAssigneeStack } from "@/components/projects/TaskAssigneeList";
import { TaskBlockersHoverCard } from "@/components/projects/TaskBlockersHoverCard";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { TaskSubtasksHoverCard } from "@/components/projects/TaskSubtasksHoverCard";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import type { RatingDisplay } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { TaskTypeMark, TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { Badge } from "@/components/ui/badge";
import { MentionText } from "@/components/user/MentionText";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatBytes } from "@/lib/fileUtils";
import { formatDateTime } from "@/lib/formatDate";
import { summarizeStored } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

import { PluginField, type PluginFieldDecl, type PluginOnItems } from "./plugins";

/** What a view draws: tasks, and a collection's files, which its own fields
 *  (`lib/layouts/files.ts`) read. */
export type LayoutItem = TaskListRead;

/** Where a field is drawn. On a detail it is its editor, which the
 *  detail parts draw (`taskLayout.tsx`). */
export type LayoutVariant = "card" | "cell" | "detail";

export type FieldKind =
  | "title"
  | "excerpt"
  | "people"
  | "date"
  | "recurrence"
  | "checklist"
  | "subtasks"
  | "parent"
  | "priority"
  | "count"
  | "tags"
  | "taskType"
  | "property"
  | "plugin"
  | "fileName"
  | "fileType"
  | "fileSize";

/** A property's field, by its definition id: what a view stores, so renaming
 *  the property keeps every view that shows it. */
export const PROPERTY_FIELD_PREFIX = "property:";
export const propertyFieldId = (definitionId: number) => `${PROPERTY_FIELD_PREFIX}${definitionId}`;

/** Anything a view can show about an item. */
export type FieldDef = {
  id: string;
  kind: FieldKind;
  source: "builtin" | "property" | "plugin";
  /** Built-in: an i18n key, in `projects` unless it names its namespace.
   *  Property or plug-in field: its own name, untranslated. */
  label: string;
  /** What the field holds for an item. Nothing (null, "", []) draws nothing on
   *  a card; a cell says so. */
  value: (item: LayoutItem) => unknown;
  /** A title's: the item's type, drawn by its name in a cell, or null where
   *  there is none to tell apart. */
  typeOf?: (item: LayoutItem) => TaskTypeRead | null;
  /** A title cannot be hidden: a card with no title is not a card. */
  hideable: boolean;
  /** A plug-in field's install and declaration, and the install as the
   *  reader meets it on this kind of item. */
  plugin?: { install: number; field: PluginFieldDecl; on: PluginOnItems };
  /** A property field's definition. */
  property?: PropertyDefinitionRead;
  /** How a rating is drawn where the list showing it says. */
  display?: RatingDisplay;
  /** A property drawn on a card as its value alone, not named: a
   *  collection's card under a picture, which reads as a caption or a price
   *  rather than a row of labelled chips. */
  plain?: boolean;
  /** The sentence the value sits in, as an i18n key ("Due: {{date}}"). */
  phrase?: string;
  icon?: LucideIcon;
  tone?: "warning";
  /** How a cell marks a date that has passed: as begun, or as overdue until
   *  the item is done. */
  past?: "primary" | "destructive";
};

/** What renderers share across a view. It changes with the language, the
 *  community and the item links, not with which fields are shown, so a renderer
 *  whose value is unchanged skips redrawing when the Fields menu changes. */
export type LayoutEnv = {
  /** Reads `projects`, and the other {@link LAYOUT_NAMESPACES} by prefix. */
  t: TranslateFn;
  /** A community-relative path, made absolute in the item's community. */
  communityPath: (path: string, item: LayoutItem) => string;
  taskHref: (task: LayoutItem) => string;
  /** What can be done with an item from where it is drawn, beside its title
   *  on a card: a board its reader may change. */
  itemActions?: ComponentType<{ item: LayoutItem }>;
};

// The namespaces a layout's names are in, loaded together so none shows as a
// key: an event's fields are named in `calendars`, whether or not an event is
// drawn beside them.
export const LAYOUT_NAMESPACES = [
  "projects",
  "layouts",
  "tasks",
  "dates",
  "relations",
  "calendars",
] as const;

/** The env of a project's views: one community, and its tasks' pages. */
export const useProjectLayoutEnv = (taskHref: (taskId: number) => string): LayoutEnv => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, taskHref: (task) => taskHref(task.id) }),
    [t, communityPath, taskHref]
  );
};

export type FieldRendererProps = {
  value: unknown;
  item: LayoutItem;
  field: FieldDef;
  variant: LayoutVariant;
  env: LayoutEnv;
};

/** Whether a value has nothing to show. A count of none is null by then. */
export const isEmptyValue = (value: unknown): boolean =>
  value == null || value === "" || (Array.isArray(value) && value.length === 0);

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
  task: LayoutItem;
  type: TaskTypeRead | null;
  unread: boolean;
  env: LayoutEnv;
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
            to={env.taskHref(task)}
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

// Only the title opens the task: the rest of the card is the card, and a real
// link means middle-click and "open in new tab" work.
const TitleField = ({ value, item, field, variant, env }: FieldRendererProps) => {
  const unread = useUnreadTree().hasSubject(item.community_id, "task", item.id);
  if (variant === "cell") {
    return (
      <TitleCell
        title={value as string}
        task={item}
        type={field.typeOf?.(item) ?? null}
        unread={unread}
        env={env}
      />
    );
  }
  const Actions = variant === "card" ? env.itemActions : undefined;
  const link = (
    <Link
      to={env.taskHref(item)}
      draggable={false}
      className="wrap-break-word w-full min-w-0 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
    >
      {value as string}
      {unread ? <UnreadDot className="ml-2 inline-block align-middle" /> : null}
    </Link>
  );
  if (!Actions) return link;
  return (
    <div className="flex w-full min-w-0 items-start gap-1">
      {link}
      <Actions item={item} />
    </div>
  );
};

// Two lines of words, not a picture that fills the card.
const ExcerptField = ({ value }: FieldRendererProps) => (
  <p className="wrap-break-word line-clamp-2 w-full min-w-0 text-muted-foreground text-sm">
    <MentionText text={value as string} />
  </p>
);

const PeopleField = ({ value, variant }: FieldRendererProps) => {
  const people = value as TaskAssigneeSummary[];
  if (variant === "cell") {
    return people.length > 0 ? (
      <TaskAssigneeStack assignees={people} />
    ) : (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    );
  }
  return <TaskAssigneeList assignees={people} className="text-xs" />;
};

// `formatDateTime`, as every timestamp in the app: it honours the reader's
// 12/24-hour choice. A cell says how far off the date is instead.
const DateField = ({ value, item, field, variant, env }: FieldRendererProps) => {
  if (variant === "cell") {
    return (
      <DateCell
        date={value as string | null}
        isPastVariant={field.past}
        isDone={item.task_status?.category === "done"}
      />
    );
  }
  const date = formatDateTime(value as string);
  if (!date) return null;
  return <p>{field.phrase ? env.t(field.phrase, { date }) : date}</p>;
};

const RecurrenceField = ({ value, item, env }: FieldRendererProps) => {
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
};

const ChecklistField = ({ value }: FieldRendererProps) => (
  <TaskChecklistProgress progress={value as ChecklistProgress} className="w-full pt-1" />
);

const SubtasksField = ({ value }: FieldRendererProps) => (
  <TaskChecklistProgress
    of="subtasks"
    progress={value as ChecklistProgress}
    className="w-full min-w-24 pt-1"
  />
);

// The task this one is part of, as a link to it: on a card a line above what
// the card says, in a cell its name.
const ParentField = ({ value, item, variant, env }: FieldRendererProps) => {
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
};

const PriorityField = ({ value, field, env }: FieldRendererProps) => {
  const priority = value as TaskPriority;
  const text = priority.replace("_", " ");
  return (
    <Badge variant={priorityVariant[priority]}>
      {field.phrase ? env.t(field.phrase, { priority: text }) : text}
    </Badge>
  );
};

const CountField = ({ value, field, variant, env }: FieldRendererProps) => {
  const count = value as number | null;
  const Icon = field.icon;
  if (variant === "cell") {
    return count ? (
      <span className="inline-flex items-center gap-1 text-sm">
        {Icon ? <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" /> : null}
        {count}
      </span>
    ) : (
      <span className="text-muted-foreground text-sm">0</span>
    );
  }
  return (
    <Badge
      variant="outline"
      className={cn(
        "inline-flex items-center gap-1 text-xs",
        field.tone === "warning" && "border-warning/40 text-warning"
      )}
      title={field.phrase ? env.t(field.phrase, { count }) : undefined}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null}
      {count}
    </Badge>
  );
};

const TagsField = ({ value, item, variant, env }: FieldRendererProps) => {
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
};

// A card shows a type by its icon alone, beside the title and named on hover;
// a cell names it.
const TaskTypeField = ({ value, variant }: FieldRendererProps) => {
  const type = value as TaskTypeRead | null;
  if (!type) {
    return variant === "cell" ? (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    ) : null;
  }
  if (variant === "cell") return <TaskTypeOption type={type} className="text-sm" />;
  // One line of the title tall, so the icon sits on the first line's middle.
  return <TaskTypeMark type={type} className="h-lh" iconClassName="h-4 w-4" />;
};

const PropertyField = ({ value, field, variant }: FieldRendererProps) => (
  <PropertyValueCell
    summary={(value as PropertySummary | null) ?? undefined}
    variant={variant === "cell" || field.plain ? "cell" : "chip"}
    display={field.display}
  />
);

/** `fields`, each rating drawn as a list's `displays` say. */
export const withDisplays = <F extends Pick<FieldDef, "display">>(
  fields: ReadonlyMap<string, F>,
  displays: Readonly<Record<string, RatingDisplay>> | null | undefined
): ReadonlyMap<string, F> =>
  displays && Object.keys(displays).length > 0
    ? new Map(
        [...fields].map(([id, field]) => [
          id,
          id in displays ? { ...field, display: displays[id] } : field,
        ])
      )
    : fields;

// A file's own fields hold the file, or its size, as their value.
const FileNameField = ({ value, variant }: FieldRendererProps) => (
  <p className={cn("min-w-0 truncate", variant === "card" ? "font-medium text-sm" : "text-sm")}>
    {(value as FileSummary).name}
  </p>
);

const FileTypeField = ({ value }: FieldRendererProps) => (
  <FileTypeBadge file={value as FileSummary} />
);

// A file of the app's own has no size; a cell says so.
const FileSizeField = ({ value, variant }: FieldRendererProps) =>
  typeof value === "number" ? (
    <span
      className={cn(
        "tabular-nums",
        variant === "card" ? "text-muted-foreground text-xs" : "text-sm"
      )}
    >
      {formatBytes(value)}
    </span>
  ) : variant === "cell" ? (
    <span className="text-muted-foreground text-sm">&mdash;</span>
  ) : null;

/** One renderer per kind of field, each skipping a redraw its props don't call
 *  for. */
export const FIELD_RENDERERS: Record<FieldKind, ComponentType<FieldRendererProps>> = {
  title: memo(TitleField),
  excerpt: memo(ExcerptField),
  people: memo(PeopleField),
  date: memo(DateField),
  recurrence: memo(RecurrenceField),
  checklist: memo(ChecklistField),
  subtasks: memo(SubtasksField),
  parent: memo(ParentField),
  priority: memo(PriorityField),
  count: memo(CountField),
  tags: memo(TagsField),
  taskType: memo(TaskTypeField),
  property: memo(PropertyField),
  plugin: memo(PluginField),
  fileName: memo(FileNameField),
  fileType: memo(FileTypeField),
  fileSize: memo(FileSizeField),
};
