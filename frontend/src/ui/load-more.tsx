import { Loader2 } from "lucide-react";
import { useEffect, useEffectEvent, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

export interface LoadMoreProps {
  /** Whether there is another page. Without one, nothing is drawn. */
  hasMore: boolean;
  /** Whether a page is on its way. */
  loading: boolean;
  onLoadMore: () => void;
  /** Ask for the next page as the end of the list scrolls into view, rather than on a click. */
  auto?: boolean;
  /** How far ahead of the reader `auto` asks, as an `IntersectionObserver` root margin. */
  rootMargin?: string;
  className?: string;
}

/**
 * The end of a list that grows a page at a time.
 *
 * As a button it asks for the next page on a click, and is disabled while a
 * page is coming. With `auto` it asks as it scrolls into view, and shows only
 * that a page is coming.
 */
export const LoadMore = ({
  hasMore,
  loading,
  onLoadMore,
  auto = false,
  rootMargin,
  className,
}: LoadMoreProps) => {
  const { t } = useTranslation("ui");
  const end = useRef<HTMLDivElement>(null);
  const loadNext = useEffectEvent(onLoadMore);

  // Watched again each time a page lands, so a page too short to push the end
  // out of view asks for the one after it.
  useEffect(() => {
    const element = end.current;
    if (!auto || !element || !hasMore || loading || typeof IntersectionObserver === "undefined") {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) loadNext();
      },
      { rootMargin }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [auto, hasMore, loading, rootMargin]);

  const pending = (
    <>
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {t("loading")}
    </>
  );
  if (auto) {
    return hasMore || loading ? (
      <div
        ref={end}
        className={cn(
          "flex items-center justify-center gap-2 py-2 text-muted-foreground text-sm",
          className
        )}
      >
        {loading ? pending : null}
      </div>
    ) : null;
  }
  return hasMore ? (
    <div className={cn("flex justify-center", className)}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={loading}
        onClick={() => onLoadMore()}
      >
        {loading ? pending : t("loadMore")}
      </Button>
    </div>
  ) : null;
};
