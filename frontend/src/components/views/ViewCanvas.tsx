import { GripVertical, MoreHorizontal, Plus } from "lucide-react";
import {
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type SyntheticEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskStatusRead,
  ToolViewWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { type useProjectTaskTableState, viewTableSorting } from "@/hooks/useProjectTaskView";
import { useTask, useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, specFromApi } from "@/lib/filters/taskFilters";
import { cn } from "@/lib/utils";
import {
  cardOf,
  indexPaths,
  type Place,
  pathKey,
  pathOf,
  type Selection,
  sameSelection,
} from "@/lib/views/draft";
import { TaskPageView } from "@/lib/views/taskPage";
import type { ViewNode } from "@/lib/views/tree";

/** How wide the canvas draws the view: the widths a person might read it at. */
export type PreviewWidth = "desktop" | "tablet" | "phone";

const MAX_WIDTH: Record<PreviewWidth, string | undefined> = {
  desktop: undefined,
  tablet: "45rem",
  phone: "24rem",
};

const noop = () => {};
const NO_COLLAPSED = new Set<number>();

/** An attribute selector's quoted value. */
const quoted = (value: string) => `"${value.replace(/["\\]/g, "\\$&")}"`;

/** The part an element is in: the nearest marked one. A table marks its
 *  columns by field, and a tree its parts by path. */
const partAt = (target: EventTarget): Selection | null => {
  const marked = target instanceof Element ? target.closest("[data-view-node]") : null;
  const value = marked?.getAttribute("data-view-node");
  if (value === null || value === undefined) return null;
  return value.startsWith("column:")
    ? { kind: "column", field: value.slice("column:".length) }
    : { kind: "part", path: pathOf(value) };
};

const rule = (of: Selection | null) => {
  if (!of || of.kind === "view") return null;
  const value = of.kind === "column" ? `column:${of.field}` : pathKey(of.path);
  return `[data-view-node=${quoted(value)}] > *`;
};

/** Nothing on the canvas is used: a key, a paste or a drop goes nowhere. */
const refuse = (event: SyntheticEvent) => {
  event.preventDefault();
  event.stopPropagation();
};

/** Tab still moves focus on, so the canvas never holds it. */
const refuseKey = (event: KeyboardEvent) => {
  if (event.key !== "Tab") refuse(event);
};

/** What the canvas does to what is drawn on it, as the editor decides. */
export type CanvasTools = {
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
  /** What a part or a column is called. */
  nameOf: (of: Selection) => string;
  /** Where adding before and after it puts a part, and whether its group
   *  runs across; null where nothing is added beside it. */
  around: (of: Selection) => { before: Place; after: Place; across: boolean } | null;
  /** Whether it holds parts, so a part dropped on it goes in it. */
  holds: (of: Selection) => boolean;
  /** Whether it can be dragged to another place. */
  movable: (of: Selection) => boolean;
  /** Moves `from` before or after `over`, or into it where it holds parts. */
  move: (from: Selection, over: Selection, after: boolean) => void;
  /** The Add picker for `place`, opened by `trigger`. */
  addAt: (place: Place, trigger: ReactNode, onOpenChange: (open: boolean) => void) => ReactNode;
};

type Box = { left: number; top: number; width: number; height: number };

const keyOf = (of: Selection): string | null =>
  of.kind === "column" ? `column:${of.field}` : of.kind === "part" ? pathKey(of.path) : null;

/** The box a marked part takes, against `origin`: its own, or what it draws
 *  where it takes none of its own. */
const boxOf = (marked: Element, origin: Element): Box => {
  const drawn = getComputedStyle(marked).display === "contents" ? [...marked.children] : [marked];
  const rects = drawn.map((element) => element.getBoundingClientRect());
  const seen = rects.filter((rect) => rect.width > 0 || rect.height > 0);
  const taken = seen.length > 0 ? seen : rects.slice(0, 1);
  const at = origin.getBoundingClientRect();
  if (taken.length === 0) return { left: 0, top: 0, width: 0, height: 0 };
  const left = Math.min(...taken.map((rect) => rect.left));
  const top = Math.min(...taken.map((rect) => rect.top));
  return {
    left: left - at.left,
    top: top - at.top,
    width: Math.max(...taken.map((rect) => rect.right)) - left,
    height: Math.max(...taken.map((rect) => rect.bottom)) - top,
  };
};

/** Where a dragged part would go: beside a part, or into a group. */
type Drop = { over: Selection; element: Element; after: boolean; into: boolean };

/**
 * What is being edited, drawn as its readers will see it, at the width
 * chosen. Nothing in it can be changed or opened: a click selects the part it
 * landed on, which the outline and the settings then show, and keys, pastes
 * and drops are refused before what is drawn sees them.
 *
 * Over it, a layer of the editor's own: the name of the part pointed at and
 * of the one selected, points to add a part before or after the one pointed
 * at, and a handle to drag the selected one elsewhere. It measures what is
 * drawn rather than wrapping it, so the view lays out as its readers see it.
 */
const CanvasFrame = ({
  width,
  selection,
  onSelect,
  tools,
  children,
}: {
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  tools: CanvasTools;
  children: ReactNode;
}) => {
  const { t } = useTranslation("projects");
  const content = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  // The element pointed at, and the one last clicked: a board draws a part on
  // every card, and the layer marks the one the pointer is on.
  const [hovered, setHovered] = useState<{ of: Selection; element: Element } | null>(null);
  const [clicked, setClicked] = useState<Element | null>(null);
  // Held while an Add picker is open, so its point stays where it was.
  const [picking, setPicking] = useState(false);
  const [drag, setDrag] = useState<{ from: Selection; drop: Drop | null } | null>(null);
  // Measured again as the canvas lays out or scrolls within itself.
  const [, setLaidOut] = useState(0);

  const selectedRule = rule(selection);
  const hoveredRule = hovered && !sameSelection(hovered.of, selection) ? rule(hovered.of) : null;

  const point = (target: EventTarget | null) => {
    if (picking || drag) return;
    const of = target ? partAt(target) : null;
    const element = target instanceof Element ? target.closest("[data-view-node]") : null;
    if (of && element) setHovered({ of, element });
  };

  // Only what the outline can name is selectable; the rest of the page is
  // the page.
  const select = (event: MouseEvent) => {
    refuse(event);
    const part = partAt(event.target);
    if (!part) return;
    setClicked(event.target instanceof Element ? event.target.closest("[data-view-node]") : null);
    onSelect(part);
  };

  useEffect(() => {
    const holder = content.current;
    if (!holder) return;
    const relayout = () => setLaidOut((count) => count + 1);
    const observer = new ResizeObserver(relayout);
    observer.observe(holder);
    holder.addEventListener("scroll", relayout, true);
    return () => {
      observer.disconnect();
      holder.removeEventListener("scroll", relayout, true);
    };
  }, []);

  // A drag follows the pointer anywhere on the screen, and Esc lets it go.
  useEffect(() => {
    if (!drag) return;
    const dropAt = (x: number, y: number): Drop | null => {
      const holder = content.current;
      const hit = document.elementsFromPoint?.(x, y).find((each) => holder?.contains(each));
      const element = hit?.closest("[data-view-node]");
      const over = hit ? partAt(hit) : null;
      if (!element || !over || !frame.current) return null;
      // Never onto itself or into what it holds.
      const fromKey = keyOf(drag.from) ?? "";
      const overKey = keyOf(over) ?? "";
      if (overKey === fromKey || (drag.from.kind === "part" && overKey.startsWith(`${fromKey}.`))) {
        return null;
      }
      if (over.kind !== drag.from.kind) return null;
      const box = boxOf(element, frame.current);
      const at = frame.current.getBoundingClientRect();
      const across = tools.around(over)?.across ?? false;
      const after = across
        ? x - at.left > box.left + box.width / 2
        : y - at.top > box.top + box.height / 2;
      return { over, element, after, into: tools.holds(over) };
    };
    const onMove = (event: PointerEvent) =>
      setDrag((current) =>
        current ? { ...current, drop: dropAt(event.clientX, event.clientY) } : current
      );
    const onUp = (event: PointerEvent) => {
      const drop = dropAt(event.clientX, event.clientY);
      if (drop) tools.move(drag.from, drop.over, drop.after);
      setDrag(null);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKey);
    };
  }, [drag, tools]);

  // Measured on every draw: what is drawn may have moved. The element held
  // for a part is the one pointed at or clicked while it is still drawn (a
  // board draws a part on every card), and else the part's first.
  const measure = (of: Selection, held: Element | null | undefined): Box | null => {
    const key = keyOf(of);
    if (key === null || !frame.current) return null;
    const element =
      held?.isConnected && held.getAttribute("data-view-node") === key
        ? held
        : content.current?.querySelector(`[data-view-node=${quoted(key)}]`);
    return element ? boxOf(element, frame.current) : null;
  };
  const selectedKey = keyOf(selection);
  const selectedBox = measure(selection, clicked);
  const hoveredBox = hovered ? measure(hovered.of, hovered.element) : null;
  const around = hovered && !tools.locked ? tools.around(hovered.of) : null;
  const dropBox = drag?.drop ? measure(drag.drop.over, drag.drop.element) : null;

  return (
    <div className="h-full overflow-auto bg-muted/40 p-6">
      <style>
        {[
          selectedRule &&
            `${selectedRule} { outline: 2px solid var(--color-primary); outline-offset: 2px; border-radius: 0.25rem; }`,
          hoveredRule &&
            `${hoveredRule} { outline: 1px dashed var(--color-primary); outline-offset: 2px; border-radius: 0.25rem; }`,
        ]
          .filter(Boolean)
          .join("\n")}
      </style>
      <div
        ref={frame}
        className="relative mx-auto"
        style={{ maxWidth: MAX_WIDTH[width] }}
        onMouseLeave={(event) => {
          const to = event.relatedTarget;
          if (picking || (to instanceof Node && frame.current?.contains(to))) return;
          setHovered(null);
        }}
      >
        <div
          ref={content}
          className="@container rounded-lg border bg-background p-4 shadow-sm"
          onClickCapture={select}
          onPointerDownCapture={refuse}
          onKeyDownCapture={refuseKey}
          onBeforeInputCapture={refuse}
          onPasteCapture={refuse}
          onDropCapture={refuse}
          onMouseOver={(event) => point(event.target)}
          onFocus={(event) => point(event.target)}
          aria-label={t("viewEditor.canvas")}
          role="region"
        >
          {children}
        </div>
        <div className="pointer-events-none absolute inset-0">
          {hovered && hoveredBox && !sameSelection(hovered.of, selection) ? (
            <NameTag box={hoveredBox}>{tools.nameOf(hovered.of)}</NameTag>
          ) : null}
          {selectedBox && selectedKey !== null ? (
            <NameTag box={selectedBox} selected>
              {tools.movable(selection) && !tools.locked ? (
                <button
                  type="button"
                  className="pointer-events-auto -ml-0.5 cursor-grab touch-none"
                  aria-label={t("viewEditor.move", { name: tools.nameOf(selection) })}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    setHovered(null);
                    setDrag({ from: selection, drop: null });
                  }}
                >
                  <GripVertical className="h-3 w-3" aria-hidden="true" />
                </button>
              ) : null}
              {tools.nameOf(selection)}
            </NameTag>
          ) : null}
          {hovered && hoveredBox && around && !drag
            ? (["before", "after"] as const).map((side) => {
                const name = tools.nameOf(hovered.of);
                return (
                  <div
                    key={side}
                    className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2"
                    style={addPoint(hoveredBox, side, around.across)}
                  >
                    {tools.addAt(
                      around[side],
                      <button
                        type="button"
                        className="flex h-5 w-5 items-center justify-center rounded-full border border-primary bg-background text-primary shadow-sm hover:bg-primary hover:text-primary-foreground"
                        aria-label={t(
                          side === "before" ? "viewEditor.addBefore" : "viewEditor.addAfter",
                          { name }
                        )}
                      >
                        <Plus className="h-3 w-3" aria-hidden="true" />
                      </button>,
                      setPicking
                    )}
                  </div>
                );
              })
            : null}
          {drag?.drop && dropBox ? <DropMark box={dropBox} drop={drag.drop} tools={tools} /> : null}
        </div>
      </div>
    </div>
  );
};

/** Where a part's add point sits: at the middle of the edge it adds on. */
const addPoint = (box: Box, side: "before" | "after", across: boolean) =>
  across
    ? { left: side === "before" ? box.left : box.left + box.width, top: box.top + box.height / 2 }
    : { left: box.left + box.width / 2, top: side === "before" ? box.top : box.top + box.height };

const NameTag = ({
  box,
  selected = false,
  children,
}: {
  box: Box;
  selected?: boolean;
  children: ReactNode;
}) => (
  <div
    className={cn(
      "absolute flex max-w-60 -translate-y-full items-center gap-1 truncate rounded-t px-1.5 py-0.5 text-2xs",
      selected ? "bg-primary text-primary-foreground" : "bg-primary/80 text-primary-foreground"
    )}
    style={{ left: box.left, top: box.top - 2 }}
  >
    {children}
  </div>
);

/** Where a dragged part would land: a line beside a part, or a group lit up. */
const DropMark = ({ box, drop, tools }: { box: Box; drop: Drop; tools: CanvasTools }) => {
  if (drop.into) {
    return (
      <div
        className="absolute rounded border-2 border-primary border-dashed bg-primary/5"
        style={box}
      />
    );
  }
  const across = tools.around(drop.over)?.across ?? false;
  const edge = across
    ? {
        left: drop.after ? box.left + box.width : box.left,
        top: box.top,
        width: 2,
        height: box.height,
      }
    : {
        left: box.left,
        top: drop.after ? box.top + box.height : box.top,
        width: box.width,
        height: 2,
      };
  return <div className="absolute bg-primary" style={edge} />;
};

/** The view being edited, with the project's own tasks. */
export const ViewCanvas = ({
  projectId,
  initiativeId,
  statuses,
  view,
  width,
  selection,
  onSelect,
  tools,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  view: ToolViewWrite;
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  tools: CanvasTools;
}) => {
  const { t } = useTranslation("projects");
  const { definition } = view;
  const layout = definition.layout.type;
  const sorting = useMemo(() => viewTableSorting(view), [view]);
  const params = useMemo(
    () => buildTaskListParams(specFromApi(definition.filters), { projectId }),
    [definition.filters, projectId]
  );
  const tasks = useTasks(params).data?.items ?? NO_TASKS;

  const card = cardOf(definition);
  const paths = useMemo(() => indexPaths(card), [card]);
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    for (const status of statuses) groups[status.id] = [];
    for (const task of tasks) (groups[task.task_status_id] ??= []).push(task);
    return groups;
  }, [tasks, statuses]);
  // Sorted as the view is, and not remembered: the reader's own sort is theirs.
  const tableState = useMemo<ReturnType<typeof useProjectTaskTableState>>(
    () => [
      { grouping: [], sorting },
      { setGrouping: noop, setSorting: noop },
    ],
    [sorting]
  );

  return (
    <CanvasFrame width={width} selection={selection} onSelect={onSelect} tools={tools}>
      {layout === "board" ? (
        <ProjectTasksKanbanView
          projectId={projectId}
          initiativeId={initiativeId}
          taskStatuses={statuses}
          groupedTasks={groupedTasks}
          collapsedStatusIds={NO_COLLAPSED}
          canReorderTasks={false}
          taskHref={taskHref}
          sensors={undefined}
          activeTask={null}
          onDragStart={noop}
          onDragOver={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onToggleCollapse={noop}
          card={card}
          editing={paths}
        />
      ) : null}
      {layout === "table" ? (
        <ProjectTasksTableView
          key={JSON.stringify(sorting)}
          projectId={projectId}
          initiativeId={initiativeId}
          tasks={tasks}
          taskStatuses={statuses}
          sensors={undefined}
          canReorderTasks={false}
          canEditTaskDetails={false}
          taskActionsDisabled
          onDragStart={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onStatusChange={noop}
          taskHref={taskHref}
          tableState={tableState}
          viewColumns={definition.columns}
          editing
        />
      ) : null}
      {layout === "calendar" ? (
        <p className="text-muted-foreground text-sm">{t("viewEditor.calendarNote")}</p>
      ) : null}
    </CanvasFrame>
  );
};

/** The task page being laid out, drawn with one of the project's tasks. */
export const PageCanvas = ({
  projectId,
  initiativeId,
  statuses,
  page,
  width,
  selection,
  onSelect,
  tools,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** The page as one tree: the page, holding its header, main and side. */
  page: ViewNode;
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  tools: CanvasTools;
}) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const leaving = useRef(true);
  // One task to draw the page with: the project's first.
  const params = useMemo(
    () => ({ ...buildTaskListParams(specFromApi(null), { projectId }), page_size: 1 }),
    [projectId]
  );
  const listed = useTasks(params);
  const first = listed.data?.items[0]?.id ?? null;
  const task = useTask(first).data;
  const paths = useMemo(() => indexPaths(page), [page]);
  const layout = useMemo(
    () => ({
      header: page.children?.[0]?.children ?? [],
      main: page.children?.[1]?.children ?? [],
      side: page.children?.[2]?.children ?? [],
    }),
    [page]
  );

  return (
    <CanvasFrame width={width} selection={selection} onSelect={onSelect} tools={tools}>
      {task ? (
        <TaskPageView
          task={task}
          layout={layout}
          editing={paths}
          page={{
            readOnly: false,
            // Drawn here so it can be placed; a reader sees it only when they
            // cannot change the task.
            readOnlyMessage: t("viewEditor.noticePreview"),
            statuses,
            initiativeId,
            currentUserId: user?.id,
            askScope: scopePrompt.ask,
            actions: (
              <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            ),
            leaving,
            preview: true,
          }}
        />
      ) : listed.isSuccess && first === null ? (
        <p className="text-muted-foreground text-sm">{t("viewEditor.noTasks")}</p>
      ) : null}
    </CanvasFrame>
  );
};

const NO_TASKS: TaskListRead[] = [];
const taskHref = () => "#";
