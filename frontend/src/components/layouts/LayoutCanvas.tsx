import type { GroupingState } from "@tanstack/react-table";
import { GripVertical, Plus } from "lucide-react";
import {
  type ComponentProps,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  LayoutGrouping,
  TaskListRead,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksGanttView } from "@/components/projects/ProjectTasksGanttView";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { columnLimitsOf } from "@/hooks/useColumnLimits";
import type { ProjectTaskTableState } from "@/hooks/useProjectTaskView";
import { useGroupables, useTaskGroupings } from "@/hooks/useTaskGroupings";
import { useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";
import {
  cardOf,
  columnsOf,
  indexPaths,
  type ListLayout,
  type Place,
  pathKey,
  pathOf,
  type Selection,
  sameSelection,
} from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import { viewGrouping, withGroupShown } from "@/lib/layouts/grouping";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

import { CanvasGrouping } from "./LayoutGroupings";

/** How wide the canvas draws the layout: the widths a person might read it at. */
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
  const marked = target instanceof Element ? target.closest("[data-layout-node]") : null;
  const value = marked?.getAttribute("data-layout-node");
  if (value === null || value === undefined) return null;
  return value.startsWith("column:")
    ? { kind: "column", field: value.slice("column:".length) }
    : { kind: "part", path: pathOf(value) };
};

const rule = (of: Selection | null) => {
  if (!of || of.kind === "layout") return null;
  const value = of.kind === "column" ? `column:${of.field}` : pathKey(of.path);
  return `[data-layout-node=${quoted(value)}] > *`;
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
  /** What is being edited: a drag under way ends when it changes, as an undo
   *  may have put another part where the dragged one was. */
  revision: unknown;
  /** Whether it is a part the editor has. */
  knows: (of: Selection) => boolean;
  /** Where adding into it puts a part: an empty group's first place. */
  inside: (of: Selection) => Place | null;
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

/** A part dragged by one pointer, and where it would go. */
type Drag = { from: Selection; pointer: number; drop: Drop | null };

type Boxes = { selected: Box | null; hovered: Box | null; drop: Box | null };

const NO_BOXES: Boxes = { selected: null, hovered: null, drop: null };

const sameBoxes = (a: Boxes, b: Boxes) => JSON.stringify(a) === JSON.stringify(b);

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
export const CanvasFrame = ({
  width,
  selection,
  onSelect,
  tools,
  bar,
  children,
}: {
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  tools: CanvasTools;
  /** Controls of the editor's own above the layout, which, unlike it, are used. */
  bar?: ReactNode;
  children: ReactNode;
}) => {
  const { t } = useTranslation(["projects", "layouts"]);
  const content = useRef<HTMLElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  // The element pointed at, and the one last clicked: a board draws a part on
  // every card, and the layer marks the one the pointer is on.
  const [hovered, setHovered] = useState<{ of: Selection; element: Element } | null>(null);
  const [clicked, setClicked] = useState<Element | null>(null);
  // Held while an Add picker is open, so its point stays where it was.
  const [picking, setPicking] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  // Measured after each draw, once what is drawn is on the page, and again as
  // the canvas lays out, scrolls within itself, or draws anew underneath.
  const [boxes, setBoxes] = useState<Boxes>(NO_BOXES);
  const [, setLaidOut] = useState(0);

  // The part an element is in, where it is one the editor has.
  const known = (target: EventTarget | null): Selection | null => {
    const of = target ? partAt(target) : null;
    return of && tools.knows(of) ? of : null;
  };

  const selectedRule = rule(selection);
  const hoveredRule = hovered && !sameSelection(hovered.of, selection) ? rule(hovered.of) : null;

  const point = (target: EventTarget | null) => {
    if (picking || drag) return;
    const of = known(target);
    const element = target instanceof Element ? target.closest("[data-layout-node]") : null;
    if (of && element) setHovered({ of, element });
  };

  // Only what the outline can name is selectable; the rest of the page is
  // the page.
  const select = (event: MouseEvent) => {
    refuse(event);
    const part = known(event.target);
    if (!part) return;
    setClicked(event.target instanceof Element ? event.target.closest("[data-layout-node]") : null);
    onSelect(part);
  };

  useEffect(() => {
    const holder = content.current;
    if (!holder) return;
    const relayout = () => setLaidOut((count) => count + 1);
    const resized = new ResizeObserver(relayout);
    resized.observe(holder);
    const redrawn = new MutationObserver(relayout);
    redrawn.observe(holder, { childList: true, subtree: true, attributes: true });
    holder.addEventListener("scroll", relayout, true);
    return () => {
      resized.disconnect();
      redrawn.disconnect();
      holder.removeEventListener("scroll", relayout, true);
    };
  }, []);

  // A change to what is edited ends a drag: its part may be elsewhere now.
  useEffect(() => setDrag(null), [tools.revision]);

  // A drag follows the pointer anywhere on the screen, and Esc lets it go.
  useEffect(() => {
    if (!drag) return;
    const dropAt = (x: number, y: number): Drop | null => {
      const holder = content.current;
      const hit = document.elementsFromPoint?.(x, y).find((each) => holder?.contains(each));
      const element = hit?.closest("[data-layout-node]");
      const part = hit ? partAt(hit) : null;
      const over = part && tools.knows(part) ? part : null;
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
    // Only the pointer that took hold of the part moves it; a cancelled one
    // lets it go.
    const onMove = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointer) return;
      setDrag((current) =>
        current ? { ...current, drop: dropAt(event.clientX, event.clientY) } : current
      );
    };
    const onUp = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointer) return;
      const drop = dropAt(event.clientX, event.clientY);
      if (drop) tools.move(drag.from, drop.over, drop.after);
      setDrag(null);
    };
    const onCancel = (event: PointerEvent) => {
      if (event.pointerId === drag.pointer) setDrag(null);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
    };
  }, [drag, tools]);

  // The element held for a part is the one pointed at or clicked while it is
  // still drawn (a board draws a part on every card), and else its first.
  const measure = (of: Selection, held: Element | null | undefined): Box | null => {
    const key = keyOf(of);
    if (key === null || !frame.current) return null;
    const element =
      held?.isConnected && held.getAttribute("data-layout-node") === key
        ? held
        : content.current?.querySelector(`[data-layout-node=${quoted(key)}]`);
    return element ? boxOf(element, frame.current) : null;
  };
  // Every draw, with no list: what is drawn may have moved.
  useLayoutEffect(() => {
    const next: Boxes = {
      selected: measure(selection, clicked),
      hovered: hovered ? measure(hovered.of, hovered.element) : null,
      drop: drag?.drop ? measure(drag.drop.over, drag.drop.element) : null,
    };
    if (!sameBoxes(next, boxes)) setBoxes(next);
  });
  const selectedKey = keyOf(selection);
  const { selected: selectedBox, hovered: hoveredBox, drop: dropBox } = boxes;
  const around = hovered && !tools.locked ? tools.around(hovered.of) : null;
  const inside = hovered && !tools.locked ? tools.inside(hovered.of) : null;

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
      {bar ? (
        <div className="mx-auto mb-3" style={{ maxWidth: MAX_WIDTH[width] }}>
          {bar}
        </div>
      ) : null}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: it only notes the pointer leaving, to take the hover mark down; the frame takes no input */}
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
        <section
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
          aria-label={t("layouts:canvas")}
        >
          {children}
        </section>
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
                  aria-label={t("layouts:move", { name: tools.nameOf(selection) })}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    setHovered(null);
                    setDrag({ from: selection, pointer: event.pointerId, drop: null });
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
                      <AddPoint
                        label={t(side === "before" ? "layouts:addBefore" : "layouts:addAfter", {
                          name,
                        })}
                      />,
                      setPicking
                    )}
                  </div>
                );
              })
            : null}
          {hovered && hoveredBox && inside && !drag ? (
            <div
              className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2"
              style={{
                left: hoveredBox.left + hoveredBox.width / 2,
                top: hoveredBox.top + hoveredBox.height / 2,
              }}
            >
              {tools.addAt(
                inside,
                <AddPoint label={t("layouts:addInto", { name: tools.nameOf(hovered.of) })} />,
                setPicking
              )}
            </div>
          ) : null}
          {drag?.drop && dropBox ? <DropMark box={dropBox} drop={drag.drop} tools={tools} /> : null}
        </div>
      </div>
    </div>
  );
};

/** A point that opens the Add picker. Its props are the trigger's, as the
 *  picker passes them. */
const AddPoint = ({ label, ...props }: { label: string } & ComponentProps<"button">) => (
  <button
    type="button"
    className="flex h-5 w-5 items-center justify-center rounded-full border border-primary bg-background text-primary shadow-sm hover:bg-primary hover:text-primary-foreground"
    aria-label={label}
    {...props}
  >
    <Plus className="h-3 w-3" aria-hidden="true" />
  </button>
);

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

/** The list layout being edited, with the project's own tasks. */
export const LayoutCanvas = ({
  projectId,
  initiativeId,
  statuses,
  layout: open,
  fields,
  width,
  selection,
  onSelect,
  tools,
  onGroupingsChange,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  layout: ListLayout;
  fields: ReadonlyMap<string, FieldDef>;
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  tools: CanvasTools;
  /** The list's groupings, with a group hidden or shown on the canvas. */
  onGroupingsChange: (groupings: LayoutGrouping[]) => void;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const { definition, kind: layout } = open;
  // Every task, in the project's order: filters and sorts are each person's.
  const params = useMemo(() => buildTaskListParams(EMPTY_TASK_FILTERS, { projectId }), [projectId]);
  const tasks = useTasks(params).data?.items ?? NO_TASKS;

  const card = cardOf(definition, fields);
  const paths = useMemo(() => indexPaths(card), [card]);
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    for (const status of statuses) groups[status.id] = [];
    for (const task of tasks) {
      groups[task.task_status_id] ??= [];
      groups[task.task_status_id].push(task);
    }
    return groups;
  }, [tasks, statuses]);
  // The limits being set, against the open tasks the preview holds.
  const columnLimits = useMemo(
    () =>
      columnLimitsOf(
        (definition.limits ?? []).map(({ status_id, limit }) => ({
          status_id,
          limit,
          count: groupedTasks[status_id]?.length ?? 0,
        }))
      ),
    [definition.limits, groupedTasks]
  );
  // Each list's preview is grouped as the list starts until a grouping is
  // picked here, as a person's list is, so the groups of it can be hidden.
  const [picks, setPicks] = useState<Partial<Record<string, GroupingState>>>({});
  const picked = picks[layout] ?? null;
  const setGrouping = useCallback(
    (next: GroupingState) => setPicks((all) => ({ ...all, [layout]: next })),
    [layout]
  );
  const all = useGroupables(fields, t as TranslateFn);
  const grouping = useMemo(
    () => viewGrouping(definition, layout, picked, all),
    [definition, layout, picked, all]
  );
  const { offered, active } = useTaskGroupings({
    fields,
    statuses,
    tasks,
    groupings: definition.groupings,
    kind: layout,
    grouping,
    params,
    t: t as TranslateFn,
  });
  const tableState = useMemo<ProjectTaskTableState>(
    () => [
      { grouping, sorting: [] },
      { setGrouping, setSorting: noop },
    ],
    [grouping, setGrouping]
  );

  return (
    <CanvasFrame
      width={width}
      selection={selection}
      onSelect={onSelect}
      tools={tools}
      bar={
        layout !== "calendar" && offered.length > 0 ? (
          <CanvasGrouping
            offered={offered}
            active={active}
            grouping={grouping}
            onGroupingChange={setGrouping}
            disabled={tools.locked}
            onToggle={(id, key, shown) =>
              onGroupingsChange(withGroupShown(definition.groupings, layout, all, id, key, shown))
            }
          />
        ) : undefined
      }
    >
      {layout === "board" ? (
        <ProjectTasksKanbanView
          projectId={projectId}
          initiativeId={initiativeId}
          taskStatuses={statuses}
          groupedTasks={groupedTasks}
          listParams={params}
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
          displays={definition.displays}
          columnLimits={columnLimits}
          grouping={grouping}
          viewGroupings={definition.groupings}
          editing={paths}
        />
      ) : null}
      {layout === "table" ? (
        <ProjectTasksTableView
          projectId={projectId}
          initiativeId={initiativeId}
          tasks={tasks}
          listParams={params}
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
          viewColumns={columnsOf(definition, fields)}
          displays={definition.displays}
          viewGroupings={definition.groupings}
          editing
        />
      ) : null}
      {layout === "calendar" ? (
        <p className="text-muted-foreground text-sm">{t("layouts:calendarNote")}</p>
      ) : null}
      {layout === "gantt" ? (
        <ProjectTasksGanttView
          initiativeId={initiativeId}
          projectId={projectId}
          tasks={tasks}
          taskStatuses={statuses}
          listParams={params}
          scale="week"
          grouping={grouping}
          viewGroupings={definition.groupings}
          taskHref={taskHref}
          editing
        />
      ) : null}
    </CanvasFrame>
  );
};

const NO_TASKS: TaskListRead[] = [];
const taskHref = () => "#";
