/**
 * The details the layout editor lays out: a project's task, the initiative
 * calendar's event and a collection's file; and the presets each tool's lists
 * offer, with its own filter controls. Each says what kind of detail it is, what the editor calls
 * it and its parts, what its fields are, whether plug-ins draw on it, and
 * draws itself with one of its own while it is laid out.
 */

import { MoreHorizontal } from "lucide-react";
import { type ReactNode, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useReadCounter } from "@/api/generated/counters/counters";
import {
  type CollectionFileSummary,
  type CollectionRead,
  FileKind,
  type PropertyDefinitionRead,
  type PropertySummary,
  type TaskTypeRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { TaskStatusPriorityFilters } from "@/components/tasks/TaskStatusPriorityFilters";
import { Button } from "@/components/ui/button";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCounterGroup } from "@/hooks/useCounters";
import { usePost, usePostsFeed } from "@/hooks/usePosts";
import { useQueue } from "@/hooks/useQueues";
import { useTask, useTasks } from "@/hooks/useTasks";
import { type CalendarFilters, EMPTY_CALENDAR_FILTERS } from "@/lib/filters/calendarFilters";
import { buildTaskListParams, EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";
import { COUNTER_DETAIL } from "@/lib/layouts/counterLayout";
import { type DetailKind, DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { DetailLayoutSpec, StoredRegions } from "@/lib/layouts/detailLayout";
import { EVENT_DETAIL } from "@/lib/layouts/eventLayout";
import type { FieldDef } from "@/lib/layouts/fields";
import { FILE_DETAIL } from "@/lib/layouts/fileLayout";
import { collectionFileFields } from "@/lib/layouts/files";
import { POST_DETAIL } from "@/lib/layouts/postLayout";
import { CALENDAR_PRESETS, TASK_PRESETS } from "@/lib/layouts/presets";
import { QUEUE_ITEM_DETAIL } from "@/lib/layouts/queueItemLayout";
import { TASK_DETAIL } from "@/lib/layouts/taskLayout";
import { taskLayoutFor } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { TranslateFn } from "@/types/i18n";

import { editablePresets } from "./LayoutPresets";
import type { LayoutProject } from "./LayoutSettingsPanel";

/** A kind of detail, as the editor lays it out. */
export type EditableDetail = {
  spec: DetailLayoutSpec;
  /** For a page laid out per type of item, which type's, and its name, which
   *  `words.name` takes as `{{name}}`. */
  taskTypeId?: number;
  typeName?: string;
  /** What the editor says about it, as keys in `projects`, each naming its
   *  namespace where it is another: its name, what it is, that it is as
   *  shipped, what its title and its fields are, and where its own parts'
   *  names (`parts`) and what each does (`partHelp`) are, as the start of their
   *  keys. */
  words: {
    name: string;
    help: string;
    shipped: string;
    titleHelp: string;
    hiddenHelp: string;
    parts: string;
  };
  /** Its fields, by id: the built-ins, and the plug-ins' where they draw on it. */
  fields: (definitions: PropertyDefinitionRead[], plugins: FieldDef[]) => Map<string, FieldDef>;
  /** The detail drawn with one of its own, laid out as `tree` says. */
  preview: (tree: LayoutNode) => ReactNode;
};

/** A detail's words, kept under `key` in the layouts namespace. */
const wordsOf = (key: string): EditableDetail["words"] => ({
  name: `layouts:${key}.name`,
  help: `layouts:${key}.help`,
  shipped: `layouts:${key}.shipped`,
  titleHelp: `layouts:${key}.titleHelp`,
  hiddenHelp: `layouts:${key}.hiddenHelp`,
  parts: `layouts:${key}.`,
});

/** The detail tree's regions, as a detail draws them. */
const regionsOf = (tree: LayoutNode): StoredRegions => ({
  header: tree.children?.[0]?.children ?? [],
  main: tree.children?.[1]?.children ?? [],
  side: tree.children?.[2]?.children ?? [],
});

/** What a detail's menu is drawn as, where nothing in it is used. */
const ActionsPreview = () => (
  <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
    <MoreHorizontal className="h-4 w-4" />
  </Button>
);

const noop = () => {};

// A preview is never left with a draft open: nothing in it is saved.
const LEFT = { current: true };

/** A detail drawn with `item`, one of its own, laid out as `tree` says; or,
 *  once there is none to draw it with, `empty`. */
const ItemPreview = <I extends { id: number; properties: PropertySummary[] }, C, P>({
  detail,
  tree,
  item,
  none,
  empty,
  context,
}: {
  detail: DetailKind<I, C, P>;
  tree: LayoutNode;
  item: I | undefined;
  none: boolean;
  empty: string;
  context: (item: I) => C;
}) => {
  const t = useTranslation("layouts").t as TranslateFn;
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (item) {
    return (
      <DetailLayoutView
        detail={detail}
        item={item}
        layout={layout}
        editing
        context={context(item)}
      />
    );
  }
  return none ? <p className="text-muted-foreground text-sm">{t(empty)}</p> : null;
};

/** A task type's page drawn with the project's first task of that type, or
 *  its first task, shown as that type, where none is. */
const TaskPreview = ({
  project,
  type,
  tree,
}: {
  project: LayoutProject;
  type: TaskTypeRead;
  tree: LayoutNode;
}) => {
  const { t } = useTranslation("layouts");
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const ofTypeParams = useMemo(
    () => ({
      ...buildTaskListParams(
        { ...EMPTY_TASK_FILTERS, type_ids: [type.id] },
        { projectId: project.id }
      ),
      page_size: 1,
    }),
    [project.id, type.id]
  );
  const anyParams = useMemo(
    () => ({ ...buildTaskListParams(EMPTY_TASK_FILTERS, { projectId: project.id }), page_size: 1 }),
    [project.id]
  );
  const ofType = useTasks(ofTypeParams);
  const any = useTasks(anyParams, {
    enabled: ofType.isSuccess && ofType.data.items.length === 0,
  });
  const listed = ofType.data?.items.length ? ofType : any;
  const first = listed.data?.items[0]?.id ?? null;
  const read = useTask(first).data;
  const item = useMemo(
    () => (read ? { ...read, task_type_id: type.id, task_type: type } : undefined),
    [read, type]
  );
  return (
    <ItemPreview
      detail={TASK_DETAIL}
      tree={tree}
      item={item}
      none={listed.isSuccess && first === null}
      empty="noTasks"
      context={() => ({
        readOnly: false,
        // Drawn here so it can be placed; a reader sees it only when they
        // cannot change the task.
        readOnlyMessage: t("noticePreview"),
        statuses: project.statuses,
        types: project.types,
        initiativeId: project.initiativeId,
        currentUserId: user?.id,
        askScope: scopePrompt.ask,
        actions: <ActionsPreview />,
        leaving: LEFT,
        preview: true,
      })}
    />
  );
};

const YEAR = 365 * 24 * 60 * 60 * 1000;

/** The event's detail drawn with the first of the initiative's events within
 *  a year either side of today. */
const EventPreview = ({ initiativeId, tree }: { initiativeId: number; tree: LayoutNode }) => {
  const params = useMemo(() => {
    const now = Date.now();
    return {
      initiative_id: initiativeId,
      include_tasks: false,
      start_after: new Date(now - YEAR).toISOString(),
      start_before: new Date(now + YEAR).toISOString(),
    };
  }, [initiativeId]);
  const listed = useCalendarEntries(params);
  const first = listed.data?.events[0]?.id ?? null;
  return (
    <ItemPreview
      detail={EVENT_DETAIL}
      tree={tree}
      item={useCalendarEvent(first).data}
      none={listed.isSuccess && first === null}
      empty="noEvents"
      context={(event) => ({
        readOnly: false,
        initiativeId,
        occurrence: undefined,
        occurrenceStart: event.start_at,
        shownStart: event.start_at,
        shownEnd: event.end_at,
        askScope: async () => null,
        onMoved: noop,
        onShifted: noop,
        leaving: LEFT,
        actions: <ActionsPreview />,
        preview: true,
      })}
    />
  );
};

/** The queue's item detail drawn with its first item. */
const QueueItemPreview = ({
  queueId,
  initiativeId,
  tree,
}: {
  queueId: number;
  initiativeId: number;
  tree: LayoutNode;
}) => {
  const queue = useQueue(queueId);
  return (
    <ItemPreview
      detail={QUEUE_ITEM_DETAIL}
      tree={tree}
      item={queue.data?.items[0]}
      none={queue.isSuccess}
      empty="queueItemDetail.noItems"
      context={() => ({
        readOnly: false,
        queueId,
        initiativeId,
        leaving: LEFT,
        actions: <ActionsPreview />,
        preview: true,
      })}
    />
  );
};

/** The group's counter detail drawn with its first counter. */
const CounterPreview = ({
  groupId,
  initiativeId,
  tree,
}: {
  groupId: number;
  initiativeId: number;
  tree: LayoutNode;
}) => {
  const group = useCounterGroup(groupId);
  const listed = group.data?.counters[0];
  // Its own read carries the plug-ins' values, which the group's list does not.
  const read = useReadCounter(useActiveCommunityId(), listed?.id ?? 0, undefined, {
    query: { placeholderData: listed, enabled: listed !== undefined },
  });
  return (
    <ItemPreview
      detail={COUNTER_DETAIL}
      tree={tree}
      item={read.data ?? listed}
      none={group.isSuccess}
      empty="counterDetail.noItems"
      context={() => ({
        readOnly: false,
        groupId,
        initiativeId,
        leaving: LEFT,
        actions: <ActionsPreview />,
      })}
    />
  );
};

/** The notice detail drawn with the initiative's first notice. */
const PostPreview = ({ initiativeId, tree }: { initiativeId: number; tree: LayoutNode }) => {
  const feed = usePostsFeed({ initiative_id: initiativeId });
  const listed = feed.data?.pages[0]?.items[0];
  // Its own read carries the plug-ins' values, which the board's list does not.
  const read = usePost(listed?.id ?? null, { placeholderData: listed });
  return (
    <ItemPreview
      detail={POST_DETAIL}
      tree={tree}
      item={read.data ?? listed}
      none={feed.isSuccess}
      empty="postDetail.noItems"
      context={() => ({ canEdit: true, canPin: false, preview: true })}
    />
  );
};

/** A project's task pages, one per task type, in the types' order, each
 *  drawn as its type's shape until it is changed. */
export const taskDetails = (project: LayoutProject): EditableDetail[] =>
  project.types.map((type) => ({
    spec: taskLayoutFor(type.layout_preset),
    taskTypeId: type.id,
    typeName: type.name,
    words: {
      name: "layouts:typedTaskLayout",
      help: "layouts:detailHelp",
      shipped: "layouts:shipped",
      titleHelp: "layouts:detailTitleHelp",
      hiddenHelp: "layouts:hiddenHelp",
      parts: "layouts:",
    },
    fields: TASK_DETAIL.fields,
    preview: (tree) => <TaskPreview project={project} type={type} tree={tree} />,
  }));

/** The initiative calendar's event detail. */
export const eventDetail = (initiativeId: number): EditableDetail => ({
  spec: EVENT_DETAIL.spec,
  words: wordsOf("eventDetail"),
  fields: EVENT_DETAIL.fields,
  preview: (tree) => <EventPreview initiativeId={initiativeId} tree={tree} />,
});

/** A queue's item detail. */
export const queueItemDetail = (queueId: number, initiativeId: number): EditableDetail => ({
  spec: QUEUE_ITEM_DETAIL.spec,
  words: wordsOf("queueItemDetail"),
  fields: QUEUE_ITEM_DETAIL.fields,
  preview: (tree) => <QueueItemPreview queueId={queueId} initiativeId={initiativeId} tree={tree} />,
});

/** A counter group's counter detail. */
export const counterDetail = (groupId: number, initiativeId: number): EditableDetail => ({
  spec: COUNTER_DETAIL.spec,
  words: wordsOf("counterDetail"),
  fields: COUNTER_DETAIL.fields,
  preview: (tree) => <CounterPreview groupId={groupId} initiativeId={initiativeId} tree={tree} />,
});

/** A file's page in a collection drawn where the collection opens it: a
 *  picture's in the panel beside it, as the lightbox has it, and any other
 *  file's in the sheet beside the wall. */
const FilePreview = ({
  collection,
  file,
  loaded,
  tree,
}: {
  collection: CollectionRead;
  file: CollectionFileSummary | undefined;
  loaded: boolean;
  tree: LayoutNode;
}) => {
  const page = (
    <div className="@container">
      <ItemPreview
        detail={FILE_DETAIL}
        tree={tree}
        item={file}
        none={loaded}
        empty="fileDetail.noItems"
        context={() => ({ collection })}
      />
    </div>
  );
  const picture = file?.kind === FileKind.image ? resolveUploadUrl(file.file_url) : null;
  if (!picture) return <div className="max-w-md">{page}</div>;
  return (
    <div className="flex canvas-md:flex-row flex-col overflow-hidden rounded-md">
      <div className="flex min-h-64 flex-1 items-center justify-center bg-black p-4">
        <img src={picture} alt={file?.name} className="max-h-96 max-w-full object-contain" />
      </div>
      <div className="canvas-md:w-80 shrink-0 border bg-background p-4">{page}</div>
    </div>
  );
};

/** A file opened from a collection, drawn with `first`, the first of its
 *  files, once they are `loaded`. Its fields are the collection's lists'. */
export const fileDetail = (
  collection: CollectionRead,
  first: CollectionFileSummary | undefined,
  loaded: boolean
): EditableDetail => ({
  spec: FILE_DETAIL.spec,
  words: wordsOf("fileDetail"),
  fields: (definitions) => collectionFileFields(collection.metadata, definitions),
  preview: (tree) => (
    <FilePreview collection={collection} file={first} loaded={loaded} tree={tree} />
  ),
});

/** The initiative's notice detail, which every notice in it shares. */
export const postDetail = (initiativeId: number): EditableDetail => ({
  spec: POST_DETAIL.spec,
  words: wordsOf("postDetail"),
  fields: POST_DETAIL.fields,
  preview: (tree) => <PostPreview initiativeId={initiativeId} tree={tree} />,
});

/** The item detail each tool lays out on its own, with no list of its own to
 *  lay out beside it: what its editor offers. */
export const ITEM_DETAILS: Partial<
  Record<Tool, (id: number, initiativeId: number) => EditableDetail>
> = {
  [Tool.queue]: queueItemDetail,
  [Tool.counter_group]: counterDetail,
};

/** A project's lists' presets: its tasks' filters, and a table's sort. */
export const taskPresets = (project: LayoutProject) =>
  editablePresets({
    kind: TASK_PRESETS,
    empty: EMPTY_TASK_FILTERS,
    controls: (value, onChange) => (
      <TaskFilters
        scope={{
          kind: "project",
          memberScope: { type: "canOpen", tool: Tool.project, id: project.id },
          statuses: project.statuses,
          types: project.types,
          initiativeId: project.initiativeId,
          projectId: project.id,
        }}
        value={value}
        onChange={onChange}
      />
    ),
    sortable: (kind) => kind === "table",
  });

/** The initiative calendar's presets: what its tasks are, and the properties
 *  its events and tasks carry, as its page filters them. */
export const calendarPresets = (initiativeId: number) =>
  editablePresets<CalendarFilters>({
    kind: CALENDAR_PRESETS,
    empty: EMPTY_CALENDAR_FILTERS,
    controls: (value, onChange) => (
      <div className="space-y-4">
        <TaskStatusPriorityFilters
          statusFilters={value.status_categories}
          onStatusChange={(status_categories) => onChange({ ...value, status_categories })}
          priorityFilters={value.priorities}
          onPriorityChange={(priorities) => onChange({ ...value, priorities })}
        />
        <PropertyFilter
          value={value.properties}
          onChange={(properties) => onChange({ ...value, properties })}
          initiativeId={initiativeId}
        />
      </div>
    ),
    sortable: () => false,
  });

/** What each tool the whole initiative shares lays out: its item's detail,
 *  and the presets its list offers where it has one. */
export const SHARED_LAYOUTS: Partial<
  Record<
    Tool,
    { detail: (initiativeId: number) => EditableDetail; presets?: typeof calendarPresets }
  >
> = {
  [Tool.calendar]: { detail: eventDetail, presets: calendarPresets },
  [Tool.post]: { detail: postDetail },
};
