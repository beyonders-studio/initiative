import { ChevronDown } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import {
  ArchiveDoneButton,
  CollapsedHeader,
  type ColumnFill,
  ExpandedHeader,
  KanbanCards,
} from "@/components/projects/KanbanColumn";
import type { Band } from "@/lib/layouts/grouping";
import type { TaskGrouping } from "@/lib/layouts/taskGroupings";
import type { LayoutContext } from "@/lib/layouts/tree";
import { cn } from "@/ui/lib/utils";

interface KanbanBandsProps {
  bands: Band<TaskListRead>[];
  grouping: TaskGrouping;
  statuses: TaskStatusRead[];
  /** How many tasks each column holds, once each, whatever bands they are in. */
  counts: Record<number, number>;
  /** A limited column's open tasks against its limit. */
  fillOf: (statusId: number) => ColumnFill | undefined;
  collapsedStatusIds: Set<number>;
  onToggleCollapse: (statusId: number) => void;
  canWrite: boolean;
  view: LayoutContext;
  /** How wide an open column is. */
  columnBasis: string;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchiving?: boolean;
}

/**
 * A board grouped into bands: one row of the status columns' headers, then a
 * band for each group with a cell in each column. A card goes into a cell:
 * another column changes its status, another band the field the board is
 * grouped by.
 */
export const KanbanBands = ({
  bands,
  grouping,
  statuses,
  counts,
  fillOf,
  collapsedStatusIds,
  onToggleCollapse,
  canWrite,
  view,
  columnBasis,
  onArchiveDoneTasks,
  isArchiving,
}: KanbanBandsProps) => {
  // Which bands are folded is each person's, for as long as they look.
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (key: string) =>
    setFolded((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  const width = (status: TaskStatusRead) =>
    cn("shrink-0", collapsedStatusIds.has(status.id) ? "grow-0 basis-12" : columnBasis);

  return (
    <div className="flex min-w-full flex-col gap-3">
      <div className="sticky top-0 z-30 flex gap-4 bg-background pb-1">
        {statuses.map((status) => {
          const collapsed = collapsedStatusIds.has(status.id);
          const count = counts[status.id] ?? 0;
          return (
            <div
              key={status.id}
              className={cn(
                "overflow-hidden rounded-lg border bg-card shadow-sm",
                collapsed && "text-center",
                width(status)
              )}
            >
              <div
                aria-hidden="true"
                className="h-1 w-full"
                style={{ backgroundColor: status.color }}
              />
              {collapsed ? (
                <CollapsedHeader
                  status={status}
                  taskCount={count}
                  fill={fillOf(status.id)}
                  onToggleCollapse={onToggleCollapse}
                />
              ) : (
                <ExpandedHeader
                  status={status}
                  taskCount={count}
                  fill={fillOf(status.id)}
                  onToggleCollapse={onToggleCollapse}
                />
              )}
              {!collapsed && status.category === "done" && onArchiveDoneTasks ? (
                <ArchiveDoneButton
                  statusId={status.id}
                  onArchiveDoneTasks={onArchiveDoneTasks}
                  isArchiving={isArchiving}
                />
              ) : null}
            </div>
          );
        })}
      </div>
      {bands.map((band) => (
        <BandRow
          key={band.key}
          band={band}
          grouping={grouping}
          folded={folded.has(band.key)}
          onToggle={() => toggle(band.key)}
        >
          {statuses.map((status) => (
            <KanbanCards
              key={status.id}
              statusId={status.id}
              group={band.key}
              tasks={band.items.filter((task) => task.task_status_id === status.id)}
              collapsed={collapsedStatusIds.has(status.id)}
              canWrite={canWrite}
              view={view}
              className={cn(
                "scrollbar-thin max-h-[60vh] min-h-16 space-y-3 overflow-y-auto rounded-lg border border-dashed p-2 transition-colors",
                width(status)
              )}
            />
          ))}
        </BandRow>
      ))}
    </div>
  );
};

/** A band's header, its toggle named by what the header shows, and its cells. */
const BandRow = ({
  band,
  grouping,
  folded,
  onToggle,
  children,
}: {
  band: Band<TaskListRead>;
  grouping: TaskGrouping;
  folded: boolean;
  onToggle: () => void;
  children: ReactNode;
}) => {
  const labelId = useId();
  return (
    <div className="space-y-2">
      <div
        className="sticky left-0 flex w-fit items-center gap-2 rounded-md bg-muted/30 px-2 py-1"
        data-kanban-scroll-lock="true"
      >
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
          aria-expanded={!folded}
          aria-labelledby={labelId}
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", folded && "-rotate-90")} />
        </button>
        <span id={labelId}>{grouping.header(band.key)}</span>
        <span className="text-muted-foreground text-sm tabular-nums">{band.items.length}</span>
      </div>
      {folded ? null : <div className="flex gap-4">{children}</div>}
    </div>
  );
};
