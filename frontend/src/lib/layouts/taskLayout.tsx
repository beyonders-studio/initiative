import { format } from "date-fns";
import {
  type ReactNode,
  type RefObject,
  useContext,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  type TaskPriority,
  type TaskRead,
  type TaskStatusRead,
  type TaskTypeRead,
  type TaskUpdate,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentSection } from "@/components/comments/CommentSection";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import type { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { PART_MARK, SmartTitleParts } from "@/components/tasks/SmartTitleParts";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { CasePanel } from "@/components/tickets/CasePanel";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useComments, useCommentsCache, useCommentThreadState } from "@/hooks/useComments";
import { useDateLocale } from "@/hooks/useDateLocale";
import { ItemDraftContext, type ItemEdit } from "@/hooks/useFieldSave";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useSmartTitle, useSmartTitlesOn } from "@/hooks/useSmartTitle";
import {
  TASK_SAVES,
  type TaskEdit,
  useGenerateTaskDescription,
  useTaskFieldSave,
  useTaskSaveOptions,
} from "@/hooks/useTasks";
import { dateRangeBounds } from "@/lib/dateRange";
import { toast } from "@/lib/mascotToast";
import {
  fromStored,
  isHourlyRule,
  isValidTaskRecurrence,
  rulePayload,
  type TaskRecurrenceValue,
} from "@/lib/recurrence";
import { referenceRef } from "@/lib/smartChips";
import { type Applied, NOTHING_APPLIED, readingEdit } from "@/lib/smartTaskTitle";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { dateTimePattern } from "@/lib/timeFormat";
import { taskRoute } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { FieldFrame, sameIds, sameJson, useFieldDraft } from "./editing";
import { DescriptionField, TagsField, TitleField } from "./fieldEditors";
import { TASK_LAYOUT, taskFields, taskLayoutFor } from "./tasks";

/** What the task's detail shares with its parts, beside the task itself. */
export interface TaskLayoutContext {
  /** The server says the reader cannot change the task. */
  readOnly: boolean;
  /** Why, when it does. */
  readOnlyMessage: string | null;
  /** The project's statuses, which the task's own joins when the project dropped it. */
  statuses: TaskStatusRead[];
  /** The project's task types. One alone is not shown: it tells nothing apart. */
  types: TaskTypeRead[];
  /** Whether a column takes one more task; left out where none is limited. */
  isFull?: (taskStatusId: number) => boolean;
  initiativeId: number | null;
  currentUserId?: number;
  askScope: ReturnType<typeof useScopePrompt>["ask"];
  /** The overflow menu of what else can be done with the task. */
  actions: ReactNode;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Drawn in the layout editor, where nothing is changed: a description
   *  draft kept on the device stays there. */
  preview?: boolean;
}

const useTaskLayout = useItemContext<TaskLayoutContext>;

type EditorProps = { item: TaskRead; label: string };

/** The task's title, which is the detail's heading. One being added is read
 *  for its details where the reader has that on. */
const TitleEditor = (props: EditorProps) => {
  const adding = useContext(ItemDraftContext) !== null;
  const smart = useSmartTitlesOn();
  return adding && smart ? <SmartTitleEditor {...props} /> : <PlainTitleEditor {...props} />;
};

const PlainTitleEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  return (
    <TitleField
      id="task-title"
      label={label}
      value={task.title}
      save={useTaskFieldSave(task, label, askScope)}
      readOnly={readOnly}
      placeholder={t("taskForm.titlePlaceholder")}
    />
  );
};

/**
 * The title of a task being added, read as it is typed: the due date, repeat,
 * priority, tags and people it names are set on the task's own fields, marked
 * in the title and listed under it, and the title is added without them.
 */
const SmartTitleEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  const drafting = useContext(ItemDraftContext);
  const save = useTaskFieldSave(task, label, askScope);
  // The field shows the title as typed; the task is added as it reads.
  const smart = useSmartTitle({
    text: task.title,
    communityId: useActiveCommunityId(),
    projectId: task.project_id,
    enabled: true,
  });
  const applied = useRef<Applied>({ ...NOTHING_APPLIED, title: task.title });
  const latest = useRef(task);
  latest.current = task;
  // A reading that moved — the title typed on, a name looked up, a part kept —
  // sets what it says on the task's fields.
  useEffect(() => {
    if (!smart.reading || !drafting) return;
    const { edit, applied: next } = readingEdit(latest.current, smart.reading, applied.current);
    applied.current = next;
    if (edit) drafting.edit(edit as ItemEdit<unknown, unknown>);
  }, [smart.reading, drafting]);
  // Add can follow a change in the same event (Enter), before the reading
  // above has run, so each change already sends the title as it reads.
  const titleSave: typeof save = {
    ...save,
    save: (edit, undo) => {
      if (!("patch" in edit) || typeof edit.patch.title !== "string") return save.save(edit, undo);
      const title = smart.read(edit.patch.title).title;
      applied.current = { ...applied.current, title };
      return save.save({ patch: { ...edit.patch, title }, shows: edit.shows }, undo);
    },
  };
  const parts = smart.reading?.parts ?? [];
  return (
    <TitleField
      id="task-title"
      label={label}
      value={task.title}
      save={titleSave}
      readOnly={readOnly}
      placeholder={t("taskForm.titlePlaceholder")}
      marks={parts.map((part) => ({ ...part, className: PART_MARK[part.type] }))}
      below={<SmartTitleParts reading={smart.reading} onKeep={smart.keep} className="px-3 pt-1" />}
      mention={{
        members: { type: "canOpen", tool: Tool.project, id: task.project_id },
        onPick: smart.picked,
      }}
    />
  );
};

/** The description ({@link DescriptionField}), which AI can write a first
 *  draft of where it is on. */
const DescriptionEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, initiativeId, leaving, askScope, preview } = useTaskLayout();
  const { isEnabled: aiEnabled } = useAIEnabled();
  const generate = useGenerateTaskDescription();
  // A task being added has nothing yet for AI to write from.
  const adding = useContext(ItemDraftContext) !== null;
  return (
    <DescriptionField
      kind={TASK_SAVES}
      id={task.id}
      options={useTaskSaveOptions(task, askScope)}
      label={label}
      htmlId="task-description"
      value={task.description}
      readOnly={readOnly}
      preview={preview}
      initiativeId={initiativeId}
      subject={referenceRef(SearchEntityType.task, task.id)}
      leaving={leaving}
      placeholder={t("edit.descriptionPlaceholder")}
      suggest={
        aiEnabled && !adding
          ? {
              label: t("edit.aiGenerate"),
              run: async () => {
                const written = await generate.mutateAsync(task.id);
                toast.success(t("edit.descriptionGenerated"), {
                  description:
                    written.comments_read < written.comments_total
                      ? t("ai.fromComments", {
                          read: written.comments_read,
                          count: written.comments_total,
                        })
                      : undefined,
                });
                return written.description;
              },
            }
          : undefined
      }
    />
  );
};

const StatusEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation(["tasks", "projects"]);
  const { readOnly, statuses, isFull, askScope } = useTaskLayout();
  const label = t("taskForm.statusLabel");
  const save = useTaskFieldSave(task, label, askScope);
  // A task keeps the status it was given after the project drops it, and the
  // select can only name a status it lists.
  const options = statuses.some((status) => status.id === task.task_status_id)
    ? statuses
    : [...statuses, task.task_status];
  const edit = (status: TaskStatusRead): TaskEdit => ({
    patch: { task_status_id: status.id },
    shows: { task_status_id: status.id, task_status: status },
  });
  return (
    <FieldFrame label={label} htmlFor="task-status" save={save}>
      <Select
        value={String(task.task_status_id)}
        onValueChange={(selected) => {
          const next = options.find((status) => String(status.id) === selected);
          if (next && next.id !== task.task_status_id) {
            void save.save(edit(next), edit(task.task_status));
          }
        }}
        disabled={readOnly}
      >
        <SelectTrigger
          id="task-status"
          className="border-2"
          style={statusTriggerStyle(task.task_status)}
        >
          <TaskStatusOption status={task.task_status} />
        </SelectTrigger>
        <SelectContent>
          {options.map((status) => {
            const full = status.id !== task.task_status_id && isFull?.(status.id) === true;
            return (
              <SelectItem key={status.id} value={String(status.id)} disabled={full}>
                <TaskStatusOption status={status} />
                {full ? (
                  <span className="text-muted-foreground text-xs">{t("projects:kanban.full")}</span>
                ) : null}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

/** What a new task of `type` starts with where it is drawn: its description
 *  outline and its priority. (Its checklist lines and repeat are added by the
 *  server when it is made.) */
const startsWith = (type: TaskTypeRead) => ({
  description: type.starting_values?.description ?? null,
  priority: type.starting_values?.priority ?? "medium",
});

/** What a task being added takes from `type` in place of what it took from
 *  `was`: each of the fields above the person has left as it started. */
const startedFrom = (task: TaskRead, was: TaskTypeRead, type: TaskTypeRead) => {
  const before = startsWith(was);
  const after = startsWith(type);
  return {
    ...((task.description ?? "") === (before.description ?? "")
      ? { description: after.description }
      : {}),
    ...(task.priority === before.priority ? { priority: after.priority } : {}),
  };
};

/** Which of the project's types the task is. Changing it redraws the page as
 *  the new type lays it out; nothing the task holds is lost, only what the new
 *  page leaves out is not shown. While the task is being added, what it starts
 *  with follows the type, until the person changes it. */
const TypeEditor = ({ item: task, label }: EditorProps) => {
  const { readOnly, types, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  const adding = useContext(ItemDraftContext) !== null;
  if (types.length < 2) return null;
  const options = types.some((type) => type.id === task.task_type_id)
    ? types
    : [...types, task.task_type];
  const edit = (type: TaskTypeRead): TaskEdit => {
    const started = adding ? startedFrom(task, task.task_type, type) : {};
    return {
      patch: { task_type_id: type.id, ...started },
      shows: { task_type_id: type.id, task_type: type, ...started },
    };
  };
  return (
    <FieldFrame label={label} htmlFor="task-type" save={save}>
      <Select
        value={String(task.task_type_id)}
        onValueChange={(selected) => {
          const next = options.find((type) => String(type.id) === selected);
          if (next && next.id !== task.task_type_id) {
            void save.save(edit(next), edit(task.task_type));
          }
        }}
        disabled={readOnly}
      >
        <SelectTrigger id="task-type">
          <TaskTypeOption type={task.task_type} />
        </SelectTrigger>
        <SelectContent>
          {options.map((type) => (
            <SelectItem key={type.id} value={String(type.id)}>
              <TaskTypeOption type={type} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const PriorityEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  return (
    <FieldFrame label={label} htmlFor="task-priority" save={save}>
      <Select
        value={task.priority}
        onValueChange={(selected) => {
          const priority = selected as TaskPriority;
          void save.save({ patch: { priority }, shows: { priority } });
        }}
        disabled={readOnly}
      >
        <SelectTrigger id="task-priority">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRIORITY_ORDER.map((option) => (
            <SelectItem key={option} value={option}>
              <TaskPriorityOption priority={option} label={t(`priority.${option}` as never)} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const AssigneesEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, currentUserId, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  const saved = task.assignees.map((assignee) => assignee.id);
  // Who is added shows from the draft until the task comes back naming them.
  const edit = (ids: number[]): TaskEdit => ({
    patch: { assignee_ids: ids },
    shows: { assignees: task.assignees.filter((assignee) => ids.includes(assignee.id)) },
  });
  const draft = useFieldDraft(
    saved,
    (ids) =>
      save.save(
        edit(ids),
        ids.length === 0
          ? { patch: { assignee_ids: saved }, shows: { assignees: task.assignees } }
          : undefined
      ),
    sameIds
  );
  return (
    <FieldFrame label={label} save={save}>
      <MemberMultiSelect
        scope={{ type: "canOpen", tool: Tool.project, id: task.project_id }}
        selectedIds={draft.value}
        selectedUsers={task.assignees}
        onChange={draft.edit}
        disabled={readOnly}
        emptyMessage={t("taskForm.assigneesEmptyMessage")}
        currentUserId={currentUserId}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  return (
    <TagsField
      label={label}
      tags={task.tags}
      save={useTaskFieldSave(task, label, askScope)}
      readOnly={readOnly}
      placeholder={t("taskForm.tagsPlaceholder")}
    />
  );
};

/** A stored date as the pickers hold it: local, to the minute. */
const toLocalInputValue = (value: string | null) => {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const pad = (segment: number) => segment.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const DATE_FIELDS = [
  { key: "start", field: "start_date", label: "taskForm.startDateLabel", id: "task-start-date" },
  { key: "due", field: "due_date", label: "taskForm.dueDateLabel", id: "task-due-date" },
] as const;

type DatePair = Record<(typeof DATE_FIELDS)[number]["key"], string>;

/** The start and due dates, as one control: checked and saved as a pair. */
const DatesEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, t("taskForm.sections.schedule"), askScope);
  const saved: DatePair = {
    start: toLocalInputValue(task.start_date),
    due: toLocalInputValue(task.due_date),
  };
  const inverted = (pair: DatePair) => dateRangeBounds(pair.start, pair.due).isInverted;
  // Only the dates that moved are sent; Undo puts back what was stored.
  const draft = useFieldDraft(
    saved,
    (pair) => {
      const moved = DATE_FIELDS.filter(({ key }) => pair[key] !== saved[key]);
      const at = (local: string) => (local ? new Date(local).toISOString() : null);
      const edit: TaskEdit = { patch: {}, shows: {} };
      const undo: TaskEdit = { patch: {}, shows: {} };
      for (const { key, field } of moved) {
        edit.patch[field] = at(pair[key]);
        edit.shows[field] = at(pair[key]);
        undo.patch[field] = task[field];
        undo.shows[field] = task[field];
      }
      return save.save(edit, moved.some(({ key }) => !pair[key]) ? undo : undefined);
    },
    sameJson,
    (pair) => !inverted(pair)
  );
  const range = dateRangeBounds(draft.value.start, draft.value.due);
  const calendarProps = { start: range.startCalendarProps, due: range.endCalendarProps };
  return (
    <FieldFrame
      label={t("taskForm.sections.schedule")}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <div className="grid grid-cols-pair gap-4">
        {DATE_FIELDS.map(({ key, label, id }) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={id} className="font-normal text-muted-foreground text-xs">
              {t(label)}
            </Label>
            <DateTimePicker
              id={id}
              value={draft.value[key]}
              onChange={(next) => draft.edit({ ...draft.value, [key]: next })}
              disabled={readOnly}
              placeholder={t("common:optional")}
              calendarProps={calendarProps[key]}
            />
          </div>
        ))}
      </div>
      {range.isInverted ? (
        <p className="text-destructive text-sm" role="alert">
          {t("dates:invalidRange")}
        </p>
      ) : null}
    </FieldFrame>
  );
};

type Repeat = TaskRecurrenceValue;

const TaskRecurrenceEditor = ({ item: task, label }: EditorProps) => {
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  const start = task.due_date ?? task.start_date;
  const saved: Repeat = {
    rule: fromStored(
      task.recurrence,
      start,
      task.recurrence_shift,
      false,
      task.recurrence_strategy === "rolling"
    ),
    strategy: task.recurrence_strategy ?? "fixed",
    limit: task.recurrence_limit ?? null,
  };
  const edit = ({ rule, strategy, limit }: Repeat): TaskEdit => ({
    patch: {
      ...rulePayload(rule),
      recurrence_strategy: rule ? strategy : "fixed",
      recurrence_limit: rule && strategy === "rolling" && isHourlyRule(rule) ? limit : null,
    },
    // The stored rule is the server's to work out from the zone it is sent with.
    shows: rule
      ? { recurrence_strategy: strategy, recurrence_limit: limit }
      : { recurrence: null, recurrence_strategy: "fixed", recurrence_limit: null },
  });
  // A rule this editor cannot show cannot be sent back, so only a rule it can
  // is offered back after it is removed.
  const draft = useFieldDraft(
    saved,
    (repeat) =>
      save.save(
        edit(repeat),
        repeat.rule === null && saved.rule !== "custom"
          ? {
              ...edit(saved),
              shows: {
                recurrence: task.recurrence,
                recurrence_strategy: saved.strategy,
                recurrence_limit: saved.limit,
              },
            }
          : undefined
      ),
    sameJson,
    (repeat) =>
      isValidTaskRecurrence(repeat) && (!isHourlyRule(repeat.rule) || Boolean(task.due_date))
  );
  // Adding the first due date also releases an hourly repeat held until then.
  const revalidateDueDate = useEffectEvent(() => {
    if (isHourlyRule(draft.value.rule)) {
      draft.change(draft.value);
      draft.finish();
    }
  });
  useEffect(() => {
    revalidateDueDate();
  }, [task.due_date]);
  return (
    <FieldFrame label={label} hideLabel save={save} changed={draft.changed} keys={draft.keys}>
      <RecurrenceEditor
        kind="task"
        value={draft.value.rule}
        onChange={(rule) => draft.edit({ ...draft.value, rule })}
        strategy={draft.value.strategy}
        limit={draft.value.limit}
        onTaskChange={draft.edit}
        hasDueDate={Boolean(task.due_date)}
        disabled={readOnly}
        referenceDate={start}
        stored={task.recurrence ? { rule: task.recurrence, shift: task.recurrence_shift } : null}
      />
    </FieldFrame>
  );
};

const Checklist = ({ item: task }: EditorProps) => {
  const { readOnly } = useTaskLayout();
  // Its items are each saved on a task that exists.
  if (useContext(ItemDraftContext) !== null) return null;
  return <TaskChecklist taskId={task.id} items={task.checklist ?? []} canEdit={!readOnly} />;
};

/** Who made the task and when. */
const Byline = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const dateLocale = useDateLocale();
  const createdAt = useMemo(() => new Date(task.created_at), [task.created_at]);
  const relative = useRelativeTime(createdAt);
  const creator = task.creator;
  const anonymized = isAnonymizedUser(creator);
  // A creator who has since left the community is named by id.
  const name =
    creator || task.created_by != null
      ? getUserDisplayName(creator ?? { id: task.created_by })
      : null;
  const avatarSrc = creator && !anonymized ? getAvatarSrc(creator) : undefined;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex w-fit items-center gap-2 text-muted-foreground text-xs">
            {name ? (
              <Avatar className="h-5 w-5 border text-3xs">
                {avatarSrc ? <AvatarImage src={avatarSrc} alt={name} /> : null}
                <AvatarFallback userId={anonymized ? null : (creator?.id ?? null)}>
                  {getInitialsForUser(creator)}
                </AvatarFallback>
              </Avatar>
            ) : null}
            <span>
              {name
                ? t("edit.createdBy", { name, time: relative })
                : t("edit.createdAt", { time: relative })}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          {format(createdAt, dateTimePattern("PP", { seconds: true }), { locale: dateLocale })}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

const Notice = () => {
  const { readOnlyMessage } = useTaskLayout();
  return readOnlyMessage ? (
    <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
      {readOnlyMessage}
    </p>
  ) : null;
};

const Case = ({ task }: { task: TaskRead }) => (
  <CasePanel
    taskId={task.id}
    canEdit={!useTaskLayout().readOnly}
    assigneeIds={task.assignees.map((assignee) => assignee.id)}
  />
);

const Comments = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const { initiativeId } = useTaskLayout();
  const params = { task_id: task.id };
  const query = useComments(params);
  const cache = useCommentsCache(params);
  const thread = useCommentThreadState(params);
  return (
    <>
      {query.isError ? <p className="text-destructive text-sm">{t("edit.commentsError")}</p> : null}
      <CommentSection
        entityType="task"
        entityId={task.id}
        comments={query.data ?? []}
        isLoading={query.isLoading}
        hasOlder={query.hasNextPage}
        isLoadingOlder={query.isFetchingNextPage}
        onLoadOlder={() => void query.fetchNextPage()}
        onCommentCreated={cache.putComment}
        onCommentDeleted={cache.removeComment}
        onCommentUpdated={cache.putComment}
        initiativeId={initiativeId ?? 0}
        locked={thread.data?.locked ?? false}
        canModerate={thread.data?.canModerate ?? false}
      />
    </>
  );
};

/** A task's detail: its fields, its own parts and where it lives. A task is
 *  addressed inside its project, so that is the tool its links refresh. */
export const TASK_DETAIL: DetailKind<TaskRead, TaskLayoutContext, TaskUpdate> = {
  spec: TASK_LAYOUT,
  // Each type of task has its own page, drawn as its shape until it is changed.
  typed: {
    typeOf: (task) => task.task_type_id,
    spec: (task) => taskLayoutFor(task.task_type?.layout_preset),
  },
  fields: taskFields,
  namespaces: ["projects"],
  editors: {
    title: TitleEditor,
    type: TypeEditor,
    description: DescriptionEditor,
    assignees: AssigneesEditor,
    priority: PriorityEditor,
    recurrence: TaskRecurrenceEditor,
    tags: TagsEditor,
    checklist: Checklist,
  },
  parts: {
    status: (_node, task) => <StatusEditor task={task} />,
    dates: (_node, task) => <DatesEditor task={task} />,
    byline: (_node, task) => <Byline task={task} />,
    notice: () => <Notice />,
    case: (_node, task) => <Case task={task} />,
    comments: (_node, task) => <Comments task={task} />,
  },
  home: (task, context) => ({
    saves: TASK_SAVES,
    readOnly: context.readOnly,
    initiativeId: context.initiativeId,
    canOpen: { tool: Tool.project, id: task.project_id },
    links: {
      entity: { id: task.project_id, initiative_id: task.project?.initiative_id ?? null },
      target: { type: SearchEntityType.task, id: task.id },
      title: task.title,
      layout: "rows",
    },
    actions: context.actions,
  }),
  taskRoute: (task, context, taskId) => taskRoute(context.initiativeId, task.project_id, taskId),
  addingParts: ["status", "dates"],
  // The type picks the page the rest is laid out as.
  addingUpFront: ["type"],
};

/** A task not yet added to `projectId`, in `status` and of `type`, as its
 *  detail draws it while it is. */
export const blankTask = (
  projectId: number,
  status: TaskStatusRead,
  type: TaskTypeRead
): TaskRead => ({
  id: 0,
  project_id: projectId,
  title: "",
  ...startsWith(type),
  start_date: null,
  due_date: null,
  recurrence: null,
  recurrence_strategy: "fixed",
  recurrence_limit: null,
  recurrence_occurrence_count: 0,
  recurrence_shift: 0,
  recurrence_anchor: null,
  recurrence_anchor_count: 0,
  recurrence_until: null,
  series_id: null,
  series_size: 0,
  task_status_id: status.id,
  task_status: status,
  task_type_id: type.id,
  task_type: type,
  created_at: "",
  updated_at: "",
  completed_at: null,
  position: 0,
  archived_at: null,
  created_by: null,
  creator: null,
  assignees: [],
  comment_count: 0,
  blocked_by_open_count: 0,
  project: null,
  checklist: [],
  checklist_progress: null,
  parent: null,
  subtask_progress: null,
  tags: [],
  properties: [],
  plugin_values: [],
});
