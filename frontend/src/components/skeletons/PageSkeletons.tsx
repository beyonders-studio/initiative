import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * Placeholder layouts shown while a page or table is still arriving. Each one
 * is shaped like the surface it stands in for — a title where the title will
 * be, rows where the rows will be — so the page settles into place rather
 * than jumping from a spinner to a full layout.
 *
 * Every placeholder is a `role="status"` region carrying a visually hidden
 * label, so assistive tech hears that the page is loading while sighted
 * readers see the shape of what is coming. The bars themselves are hidden
 * from the accessibility tree, so a table placeholder is never announced as
 * an empty table.
 */

/** Stable keys for a placeholder list — an index key is the lint rule this
 *  avoids, and the list never reorders. */
const keysFor = (count: number): string[] =>
  Array.from({ length: count }, (_, index) => `placeholder-${index}`);

/** Line widths cycle through these so a block of text reads as prose rather
 *  than as a stack of identical bars. */
const LINE_WIDTHS = ["w-11/12", "w-4/5", "w-2/3", "w-5/6", "w-3/5"] as const;
const lineWidth = (index: number) => LINE_WIDTHS[index % LINE_WIDTHS.length];

/** Cell widths cycle per column so a table doesn't read as a grid of dashes. */
const CELL_WIDTHS = ["w-40", "w-24", "w-32", "w-20", "w-28", "w-16"] as const;
const cellWidth = (index: number) => CELL_WIDTHS[index % CELL_WIDTHS.length];

export interface SkeletonRegionProps {
  /** Announced to assistive tech. Defaults to the shared "Loading…". */
  label?: string;
  className?: string;
  children: ReactNode;
}

/** The accessible wrapper every placeholder below renders into. */
export const SkeletonRegion = ({ label, className, children }: SkeletonRegionProps) => {
  const { t } = useTranslation("ui");
  return (
    <div role="status" aria-busy="true" data-testid="skeleton-region">
      {/* The bars are decoration: a reader hears the label, not an empty table. */}
      <div aria-hidden="true" className={className}>
        {children}
      </div>
      <span className="sr-only">{label ?? t("loading")}</span>
    </div>
  );
};

export interface SkeletonLinesProps {
  lines?: number;
  className?: string;
  /** Height class of one line. */
  lineClassName?: string;
}

/** A paragraph's worth of text. */
export const SkeletonLines = ({
  lines = 3,
  className,
  lineClassName = "h-4",
}: SkeletonLinesProps) => (
  <div className={cn("space-y-2", className)}>
    {keysFor(lines).map((key, index) => (
      <Skeleton key={key} className={cn(lineClassName, lineWidth(index))} />
    ))}
  </div>
);

/** A row of pill-shaped controls, the shape of a toolbar or a tab strip. */
export const SkeletonPillRow = ({
  count = 3,
  className,
  pillClassName = "h-9 w-24",
}: {
  count?: number;
  className?: string;
  pillClassName?: string;
}) => (
  <div className={cn("flex flex-wrap items-center gap-2", className)}>
    {keysFor(count).map((key) => (
      <Skeleton key={key} className={pillClassName} />
    ))}
  </div>
);

export interface PageHeaderSkeletonProps {
  /** The title row; off where a breadcrumb's last crumb names the page. */
  title?: boolean;
  /** A colour dot before the title, as an initiative or a tag has. */
  dot?: boolean;
  /** A one-line description under the title (hidden on phones, where the
   *  real header folds it into a disclosure). */
  description?: boolean;
  /** A row of counts under the description (hidden on phones, as above). */
  meta?: boolean;
  /** A button at the trailing end of the title row. */
  action?: boolean;
  /** How many tabs to draw under the header; 0 for none. */
  tabs?: number;
  className?: string;
}

/** A page's title block: title, an optional badge, blurb, counts, and tabs. */
export const PageHeaderSkeleton = ({
  title = true,
  dot = false,
  description = false,
  meta = false,
  action = false,
  tabs = 0,
  className,
}: PageHeaderSkeletonProps) => (
  <div className={cn("space-y-4 sm:space-y-6", className)}>
    {title ? (
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2 sm:space-y-4">
          <div className="flex min-w-0 items-center gap-3">
            {dot ? <Skeleton className="h-4 w-4 shrink-0 rounded-full" /> : null}
            <Skeleton className="h-7 w-full max-w-72 sm:h-9 sm:max-w-md" />
          </div>
          {description ? <Skeleton className="hidden h-4 w-full max-w-sm sm:block" /> : null}
          {meta ? (
            <div className="hidden items-center gap-4 sm:flex">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-28" />
            </div>
          ) : null}
        </div>
        {action ? <Skeleton className="h-9 w-9 shrink-0 sm:w-36" /> : null}
      </div>
    ) : null}
    {tabs > 0 ? (
      <div className="flex w-full gap-1 overflow-hidden rounded-lg bg-muted p-1">
        {keysFor(tabs).map((key) => (
          <Skeleton key={key} className="h-8 w-24 shrink-0 rounded-md bg-background/60" />
        ))}
      </div>
    ) : null}
  </div>
);

export interface ToolbarSkeletonProps {
  /** Pills at the leading end — status filters, view switches. */
  leading?: number;
  /** Pills at the trailing end — create, filters, the overflow menu. */
  trailing?: number;
  className?: string;
}

/** The control strip above a tool's list. */
export const ToolbarSkeleton = ({ leading = 2, trailing = 3, className }: ToolbarSkeletonProps) => (
  <div className={cn("flex flex-wrap items-center justify-between gap-2", className)}>
    <SkeletonPillRow count={leading} />
    <SkeletonPillRow count={trailing} className="ml-auto" />
  </div>
);

export interface CardGridSkeletonProps {
  count?: number;
  /** Grid classes; defaults to the three-up grid the tool lists use. */
  className?: string;
  cardClassName?: string;
}

/** A grid of cards, each with a title, a couple of lines, and some tags. */
export const CardGridSkeleton = ({
  count = 6,
  className = "grid grid-cols-fill-60/3 gap-4",
  cardClassName,
}: CardGridSkeletonProps) => (
  <div className={className}>
    {keysFor(count).map((key, index) => (
      <div
        key={key}
        className={cn("space-y-3 rounded-2xl border bg-card p-5 shadow-sm", cardClassName)}
      >
        <div className="flex items-start justify-between gap-2">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-14 rounded-full" />
        </div>
        <SkeletonLines lines={2} />
        <div className="flex gap-1.5 pt-1">
          <Skeleton className="h-5 w-14 rounded-full" />
          {index % 2 === 0 ? <Skeleton className="h-5 w-16 rounded-full" /> : null}
        </div>
      </div>
    ))}
  </div>
);

export interface ListSkeletonProps {
  rows?: number;
  /** A round avatar at the start of each row. */
  avatar?: boolean;
  className?: string;
  rowClassName?: string;
}

/** Stacked rows — members, search results, a feed. */
export const ListSkeleton = ({
  rows = 5,
  avatar = true,
  className,
  rowClassName,
}: ListSkeletonProps) => (
  <div className={cn("space-y-3", className)}>
    {keysFor(rows).map((key, index) => (
      <div key={key} className={cn("flex items-center gap-3", rowClassName)}>
        {avatar ? <Skeleton className="h-9 w-9 shrink-0 rounded-full" /> : null}
        <div className="flex-1 space-y-2">
          <Skeleton className={cn("h-4", index % 2 === 0 ? "w-1/3" : "w-1/4")} />
          <Skeleton className={cn("h-3", lineWidth(index))} />
        </div>
      </div>
    ))}
  </div>
);

export interface TableSkeletonProps {
  rows?: number;
  columns?: number;
  /** The search-and-columns strip a data table carries above its header. */
  toolbar?: boolean;
  /** The rows-per-page strip under the body. */
  pagination?: boolean;
  className?: string;
}

/** A data table: its toolbar, header row, and a page of rows. */
export const TableSkeleton = ({
  rows = 5,
  columns = 5,
  toolbar = true,
  pagination = false,
  className,
}: TableSkeletonProps) => {
  const columnKeys = keysFor(columns);
  return (
    <div className={cn("overflow-hidden rounded-md border bg-card", className)}>
      {toolbar ? (
        <div className="flex items-center justify-between gap-2 p-4">
          <Skeleton className="h-9 min-w-16 flex-1" />
          <Skeleton className="h-9 w-24 shrink-0" />
        </div>
      ) : null}
      <Table>
        <TableHeader>
          <TableRow>
            {columnKeys.map((key) => (
              <TableHead key={key}>
                <Skeleton className="h-4 w-20" />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {keysFor(rows).map((rowKey) => (
            <TableRow key={rowKey}>
              {columnKeys.map((columnKey, columnIndex) => (
                <TableCell key={columnKey}>
                  <Skeleton className={cn("h-4", cellWidth(columnIndex))} />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {pagination ? (
        <div className="flex items-center justify-between gap-3 p-4">
          <Skeleton className="h-9 w-40" />
          <Skeleton className="h-9 w-32" />
        </div>
      ) : null}
    </div>
  );
};

export interface FormSkeletonProps {
  fields?: number;
  /** Draw the form inside a card with a title block, as settings pages do. */
  card?: boolean;
  /** A submit button after the fields. */
  action?: boolean;
  className?: string;
}

/** A settings form: labelled fields and a submit button. */
export const FormSkeleton = ({
  fields = 4,
  card = true,
  action = true,
  className,
}: FormSkeletonProps) => {
  const body = (
    <div className="space-y-6">
      {keysFor(fields).map((key) => (
        <div key={key} className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-10 w-full max-w-md" />
        </div>
      ))}
      {action ? <Skeleton className="h-10 w-28" /> : null}
    </div>
  );
  if (!card) return <div className={className}>{body}</div>;
  return (
    <Card className={className}>
      <CardHeader className="space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-full max-w-sm" />
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
};

export interface DetailPageSkeletonProps {
  /** The tool breadcrumb over the title. */
  breadcrumb?: boolean;
  /** Controls at the trailing end of the breadcrumb row. */
  actions?: number;
  /** A visible title under the breadcrumb; off where the last crumb names the page. */
  title?: boolean;
  description?: boolean;
  /** What stands in for the body; defaults to one content card. */
  children?: ReactNode;
  className?: string;
}

/** A tool entity's header alone — breadcrumb, actions, title — for a page that
 *  draws its own body while the entity loads. */
export const DetailHeaderSkeleton = ({
  breadcrumb = true,
  actions = 2,
  title = true,
  description = true,
  className,
}: Omit<DetailPageSkeletonProps, "children">) => (
  <div className={cn("space-y-6", className)}>
    {breadcrumb || actions > 0 ? (
      <div className="flex flex-wrap items-center justify-between gap-3">
        {breadcrumb ? (
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-3" />
            <Skeleton className="h-4 w-32" />
          </div>
        ) : (
          <span />
        )}
        {actions > 0 ? <SkeletonPillRow count={actions} pillClassName="h-9 w-24" /> : null}
      </div>
    ) : null}
    {title || description ? (
      <div className="space-y-2">
        {title ? <Skeleton className="h-8 w-full max-w-md" /> : null}
        {description ? <Skeleton className="h-4 w-full max-w-lg" /> : null}
      </div>
    ) : null}
  </div>
);

/** A tool entity's page: breadcrumb, actions, title, and its body. */
export const DetailPageSkeleton = ({ children, className, ...header }: DetailPageSkeletonProps) => (
  <div className={cn("space-y-6", className)}>
    <DetailHeaderSkeleton {...header} />
    {children ?? (
      <Card>
        <CardContent className="space-y-3 pt-6">
          <SkeletonLines lines={4} />
        </CardContent>
      </Card>
    )}
  </div>
);

export interface ToolListSkeletonProps {
  /** Cards in a grid, or rows down the page. */
  view?: "grid" | "list";
  toolbar?: boolean;
  count?: number;
  className?: string;
}

/** A tool's list view: its toolbar and a grid (or list) of entities. */
export const ToolListSkeleton = ({
  view = "grid",
  toolbar = true,
  count = 6,
  className,
}: ToolListSkeletonProps) => (
  <div className={cn("space-y-4", className)}>
    {toolbar ? <ToolbarSkeleton /> : null}
    {view === "grid" ? (
      <CardGridSkeleton count={count} />
    ) : (
      <ListSkeleton rows={count} avatar={false} rowClassName="rounded-lg border bg-card p-4" />
    )}
  </div>
);

/** A whole page with nothing known about it yet — the router's stand-in while
 *  a route's data is on its way. Title, then a block of content. */
export const PageSkeleton = ({ label, className }: { label?: string; className?: string }) => (
  <SkeletonRegion label={label} className={className}>
    <div className="space-y-6">
      <PageHeaderSkeleton />
      <CardGridSkeleton count={3} />
    </div>
  </SkeletonRegion>
);

/** One card of prose — a description, an overview, a settings blurb. */
export const ContentCardSkeleton = ({
  lines = 4,
  className,
}: {
  lines?: number;
  className?: string;
}) => (
  <Card className={className}>
    <CardContent className="pt-6">
      <SkeletonLines lines={lines} />
    </CardContent>
  </Card>
);

/** The writing surface of a file or a task. */
export const EditorSkeleton = ({
  lines = 10,
  className,
}: {
  lines?: number;
  className?: string;
}) => (
  <div className={cn("min-h-96 rounded-lg border bg-card p-6", className)}>
    <SkeletonLines lines={lines} />
  </div>
);

/** A month of calendar: its heading, view switches, and a grid of days. */
export const CalendarGridSkeleton = ({ className }: { className?: string }) => (
  <div className={cn("space-y-4", className)}>
    <div className="flex items-center justify-between gap-2">
      <Skeleton className="h-7 w-40" />
      <SkeletonPillRow count={3} pillClassName="h-9 w-20" />
    </div>
    <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border bg-border">
      {keysFor(7).map((key) => (
        <div key={key} className="bg-card p-2">
          <Skeleton className="mx-auto h-3 w-8" />
        </div>
      ))}
      {keysFor(35).map((key, index) => (
        <div key={key} className="min-h-16 space-y-1 bg-card p-2 sm:min-h-20">
          <Skeleton className="h-3 w-4" />
          {index % 3 === 0 ? <Skeleton className="h-4 w-full" /> : null}
        </div>
      ))}
    </div>
  </div>
);

interface LabelledSkeletonProps {
  /** Announced to assistive tech. Defaults to the shared "Loading…". */
  label?: string;
}

/** A calendar's page: breadcrumb, controls, and the month grid. */
export const CalendarPageSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label}>
    <DetailPageSkeleton actions={2} description={false}>
      <CalendarGridSkeleton />
    </DetailPageSkeleton>
  </SkeletonRegion>
);

/** A project's page: breadcrumb, the overview card, and its task table. */
export const ProjectDetailSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label}>
    <DetailPageSkeleton actions={1} description={false}>
      <ContentCardSkeleton lines={3} />
      <ToolbarSkeleton />
      <TableSkeleton rows={6} columns={5} toolbar={false} />
    </DetailPageSkeleton>
  </SkeletonRegion>
);

/** A file's page: breadcrumb, toolbar, title, and the editor. */
export const FileDetailSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label}>
    <DetailPageSkeleton actions={3} description={false}>
      <EditorSkeleton lines={14} />
    </DetailPageSkeleton>
  </SkeletonRegion>
);

/** A task's page: breadcrumb, title, the description, and the detail rail. */
export const TaskEditSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label}>
    <DetailPageSkeleton actions={2} description={false}>
      <div className="grid canvas-md:grid-cols-[minmax(0,1fr)_20rem] gap-6">
        <EditorSkeleton lines={8} />
        <FormSkeleton card={false} fields={5} action={false} />
      </div>
    </DetailPageSkeleton>
  </SkeletonRegion>
);

/** A tag's page: its name and counts, then everything that carries it. */
export const TagDetailSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label} className="space-y-6">
    <PageHeaderSkeleton dot meta action />
    <ToolbarSkeleton />
    <TableSkeleton rows={6} columns={5} toolbar={false} />
  </SkeletonRegion>
);

/** A person's profile: the picture, their name, and the tray under it. */
export const ProfilePageSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label} className="space-y-6">
    <div className="flex flex-wrap items-end gap-4">
      <Skeleton className="size-24 shrink-0 rounded-full sm:size-28" />
      <Skeleton className="mb-1 h-8 w-56" />
      <Skeleton className="ms-auto mb-1 h-4 w-32" />
    </div>
    <Skeleton className="h-64 w-full rounded-2xl" />
  </SkeletonRegion>
);

/** A counter in focus mode: its name, the big number, and its controls. */
export const CounterFocusSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label} className="flex w-full max-w-sm flex-col items-center gap-8 p-6">
    <Skeleton className="h-8 w-48" />
    <Skeleton className="size-40 rounded-full" />
    <SkeletonPillRow count={3} pillClassName="h-12 w-20" className="justify-center" />
  </SkeletonRegion>
);

/** A settings pane while its route is still arriving: the layout keeps its
 *  own title and tab strip, and only the pane under them is drawn in. */
export const SettingsPaneSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label}>
    <FormSkeleton />
  </SkeletonRegion>
);

/** The community front page: its banner, the comments circle rising out of
 *  the tray with the comments in it, the initiative directory, and what is
 *  coming up. */
export const CommunityHomeSkeleton = ({ label }: LabelledSkeletonProps) => (
  <SkeletonRegion label={label} className="space-y-6">
    {/* Full-bleed like the banner it stands in for. */}
    <div className="-mx-4 -mt-4 md:-mx-8 md:-mt-8">
      <div className="flex h-56 flex-col items-center justify-center gap-3 bg-accent px-6 sm:h-64">
        <Skeleton className="h-10 w-full max-w-sm bg-background/40" />
        <Skeleton className="h-5 w-full max-w-md bg-background/40" />
      </div>
    </div>
    <div className="relative z-10 space-y-6">
      <div>
        <div className="relative z-10 flex justify-center px-3">
          <Skeleton className="size-16 shrink-0 rounded-full bg-muted" />
        </div>
        <div className="-mt-8 rounded-2xl bg-muted px-3 pt-11 pb-3 sm:px-4 sm:pb-4">
          <Card>
            <CardContent className="pt-6">
              <ListSkeleton rows={4} />
            </CardContent>
          </Card>
        </div>
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-4 w-64" />
        </div>
        <Skeleton className="h-9 w-32" />
      </div>
      <CardGridSkeleton count={3} />
      <Card>
        <CardHeader className="space-y-2">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-64" />
        </CardHeader>
        <CardContent>
          <ListSkeleton rows={3} />
        </CardContent>
      </Card>
    </div>
  </SkeletonRegion>
);
