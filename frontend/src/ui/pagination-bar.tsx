import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export interface PaginationBarProps {
  /** The page on screen, counted from 1. */
  page: number;
  pageSize: number;
  totalCount: number;
  hasNext: boolean;
  onPageChange: (page: number) => void;
  /** Offer a page size. Left out where the size is the surface's own decision. */
  onPageSizeChange?: (size: number) => void;
  /** The sizes offered. The size in use is offered too, whether or not it is one of them. */
  pageSizeOptions?: readonly number[];
  /** Warm the page a button would land on, on hover. */
  onPrefetchPage?: (page: number) => void;
  /** Names the control where more than one pager shares a screen. */
  label?: string;
  className?: string;
}

/**
 * Prev/next over a paged list, with the range it is showing.
 *
 * Both buttons are always on screen and disabled at the ends, rather than
 * appearing and disappearing with the list: the control keeps its place, so
 * paging through does not shift everything under it. A list that fits on one
 * page, with no page size to choose, draws no bar at all.
 */
export const PaginationBar = ({
  page,
  pageSize,
  totalCount,
  hasNext,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  onPrefetchPage,
  label,
  className,
}: PaginationBarProps) => {
  const { t } = useTranslation("ui");
  const sizes = pageSizeOptions.includes(pageSize)
    ? pageSizeOptions
    : [...pageSizeOptions, pageSize].sort((a, b) => a - b);
  // One size is no choice, so it isn't offered.
  const choosesSize = onPageSizeChange !== undefined && sizes.length > 1;
  if (page <= 1 && !hasNext && !choosesSize) return null;
  const start = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  return (
    <nav
      aria-label={label}
      className={cn("flex flex-wrap items-center justify-between gap-3", className)}
    >
      <div className="flex items-center gap-2">
        {choosesSize ? (
          <>
            <span className="text-muted-foreground text-sm">{t("pagination.perPage")}</span>
            <Select
              value={String(pageSize)}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger className="h-8 w-20" aria-label={t("pagination.perPage")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                {sizes.map((opt) => (
                  <SelectItem key={opt} value={String(opt)}>
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        ) : null}
        <span className="text-muted-foreground text-sm tabular-nums">
          {t("pagination.rangeOf", { start, end, total: totalCount })}
        </span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          onMouseEnter={() => page > 1 && onPrefetchPage?.(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
          {t("previous")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
          onMouseEnter={() => hasNext && onPrefetchPage?.(page + 1)}
        >
          {t("next")}
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </nav>
  );
};
