import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export interface PaginationBarProps {
  page: number;
  pageSize: number;
  totalCount: number;
  hasNext: boolean;
  onPageChange: (updater: number | ((prev: number) => number)) => void;
  /** Offer a page size. Left out where the size is the surface's own decision. */
  onPageSizeChange?: (size: number) => void;
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
 * paging through does not shift everything under it.
 */
export const PaginationBar = ({
  page,
  pageSize,
  totalCount,
  hasNext,
  onPageChange,
  onPageSizeChange,
  onPrefetchPage,
  label,
  className,
}: PaginationBarProps) => {
  const { t } = useTranslation("ui");
  const start = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  return (
    <nav
      aria-label={label}
      className={cn("flex flex-wrap items-center justify-between gap-3", className)}
    >
      <div className="flex items-center gap-2">
        {onPageSizeChange ? (
          <>
            <span className="text-muted-foreground text-sm">{t("pagination.perPage")}</span>
            <Select
              value={String(pageSize)}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger className="h-8 w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                {PAGE_SIZE_OPTIONS.map((opt) => (
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
          variant="outline"
          size="sm"
          onClick={() => onPageChange((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          onMouseEnter={() => page > 1 && onPrefetchPage?.(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
          {t("previous")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange((p) => p + 1)}
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
