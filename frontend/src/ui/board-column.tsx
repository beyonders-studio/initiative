/**
 * A board's column: its status's colour along the top, the status's icon,
 * name and count in the header, then its cards. The cards are the caller's,
 * in a stack drawn with `boardStackClass` so it scrolls on its own.
 *
 * Folding is the caller's to offer: give `onToggleCollapse` and the header
 * carries the button; `collapsed` draws the column narrow, its name turned
 * on its side.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Icon, type IconName } from "@/ui/icon-picker";
import { cn } from "@/ui/lib/utils";

/** What a column shows of its status. */
export interface BoardColumnStatus {
  name: string;
  color?: string | null;
  icon?: string | null;
}

/** Attributes for the header, a caller's `data-*` ones among them. */
export type BoardColumnHeaderProps = HTMLAttributes<HTMLDivElement> & {
  [attribute: `data-${string}`]: string;
};

interface HeaderProps {
  status: BoardColumnStatus;
  /** What the header counts, under the name. */
  count: ReactNode;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  /** The name's element: a heading where the column is a list under it. */
  Name?: ElementType;
  /** The name's id, for whatever it labels. */
  nameId?: string;
  headerProps?: BoardColumnHeaderProps;
}

const StatusIcon = ({ status, className }: { status: BoardColumnStatus; className: string }) =>
  status.icon ? (
    <Icon
      name={status.icon as IconName}
      style={status.color ? { color: status.color } : undefined}
      className={className}
      aria-hidden
    />
  ) : null;

/** A column's header, open or folded. */
export const BoardColumnHeader = ({
  status,
  count,
  collapsed = false,
  onToggleCollapse,
  Name = "p",
  nameId,
  headerProps,
}: HeaderProps) => {
  const { t } = useTranslation("ui");
  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-3 py-4" {...headerProps}>
        {onToggleCollapse ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            onClick={onToggleCollapse}
            aria-label={t("boardColumn.expand", { name: status.name })}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        ) : null}
        <StatusIcon status={status} className="h-4 w-4" />
        <div className="flex h-16 items-center justify-center">
          <Name
            id={nameId}
            className="rotate-90 whitespace-nowrap font-semibold text-muted-foreground text-xs tracking-wide"
          >
            {status.name}
          </Name>
        </div>
        {count}
      </div>
    );
  }
  return (
    <div
      className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b bg-card px-3 py-2"
      {...headerProps}
    >
      <div className="flex min-w-0 items-center gap-2">
        <StatusIcon status={status} className="h-6 w-6 shrink-0" />
        <div className="min-w-0">
          <Name id={nameId} className="truncate font-semibold text-lg leading-none">
            {status.name}
          </Name>
          {count}
        </div>
      </div>
      {onToggleCollapse ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 text-muted-foreground"
          onClick={onToggleCollapse}
          aria-label={t("boardColumn.collapse", { name: status.name })}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
};

/** The stack a column's cards sit in: scrolling on its own when open, a
 *  narrow strip when folded. */
export const boardStackClass = (collapsed = false): string =>
  cn(
    "h-full w-full transition-colors",
    collapsed
      ? "flex flex-1 items-center justify-center px-2"
      : "scrollbar-thin flex-1 space-y-3 overflow-y-auto p-3 pr-2"
  );

export const BoardColumn = ({
  status,
  count,
  collapsed = false,
  onToggleCollapse,
  Name,
  nameId,
  headerProps,
  footer,
  className,
  children,
}: HeaderProps & {
  /** Under the cards, where the column is open. */
  footer?: ReactNode;
  className?: string;
  /** The cards, in a stack drawn with `boardStackClass`. */
  children?: ReactNode;
}) => (
  <div
    className={cn(
      "flex h-full flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-colors",
      collapsed && "items-center text-center",
      className
    )}
  >
    <div
      aria-hidden="true"
      className="h-1 w-full shrink-0"
      style={status.color ? { backgroundColor: status.color } : undefined}
    />
    <BoardColumnHeader
      status={status}
      count={count}
      collapsed={collapsed}
      onToggleCollapse={onToggleCollapse}
      Name={Name}
      nameId={nameId}
      headerProps={headerProps}
    />
    {children}
    {collapsed ? null : footer}
  </div>
);
