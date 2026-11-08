/**
 * The frame every home widget draws in: a card with a title row and a body that
 * scrolls inside the tile.
 *
 * On a wide screen a tile is the size its grid cell says, so a long list
 * scrolls within it rather than pushing the page. Stacked on a narrow screen a
 * tile has no fixed height and the body simply grows.
 */

import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Card } from "@/ui/card";
import { cn } from "@/ui/lib/utils";

export interface HomeWidgetCardProps {
  icon: LucideIcon;
  title: ReactNode;
  /** Where the title goes when there is a full page for what the widget shows. */
  to?: string;
  search?: Record<string, string>;
  /** Controls on the right of the title row. */
  actions?: ReactNode;
  children: ReactNode;
  /** For a body that lays itself out edge to edge (a table, a calendar). */
  bodyClassName?: string;
}

export const HomeWidgetCard = ({
  icon: Icon,
  title,
  to,
  search,
  actions,
  children,
  bodyClassName,
}: HomeWidgetCardProps) => (
  <Card className="flex h-full min-h-0 flex-col overflow-hidden">
    <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b px-4 py-2">
      <h2 className="flex min-w-0 items-center gap-2 font-semibold text-base">
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        {to ? (
          <Link to={to} search={search} className="truncate hover:underline">
            {title}
          </Link>
        ) : (
          <span className="truncate">{title}</span>
        )}
      </h2>
      {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
    </div>
    <div className={cn("min-h-0 flex-1 overflow-auto p-4", bodyClassName)}>{children}</div>
  </Card>
);

/** A centred line for a widget with nothing to show yet, and what to do about it. */
export const HomeWidgetNotice = ({
  icon: Icon,
  children,
  action,
}: {
  icon?: LucideIcon;
  children: ReactNode;
  /** The one thing to do about it. */
  action?: ReactNode;
}) => (
  <div className="flex h-full min-h-24 flex-col items-center justify-center gap-3 text-center text-muted-foreground text-sm">
    {Icon ? <Icon className="size-6 opacity-50" aria-hidden="true" /> : null}
    <span className="max-w-sm">{children}</span>
    {action}
  </div>
);
