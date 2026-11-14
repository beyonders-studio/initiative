import { Capacitor } from "@capacitor/core";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { usePullToRefresh } from "@/ui/lib/usePullToRefresh";
import { cn } from "@/ui/lib/utils";

interface PullToRefreshProps {
  /** Content to wrap with pull-to-refresh behavior */
  children: ReactNode;
  /** Callback when refresh is triggered - should return a promise */
  onRefresh: () => Promise<void>;
  /** Threshold in pixels to trigger refresh (default: 80) */
  threshold?: number;
  /** Maximum pull distance in pixels (default: 120) */
  maxPull?: number;
  /** Whether pull-to-refresh is enabled (default: true) */
  enabled?: boolean;
  /** Optional className for the container */
  className?: string;
}

export function PullToRefresh({
  children,
  onRefresh,
  threshold = 80,
  maxPull = 120,
  enabled = true,
  className,
}: PullToRefreshProps) {
  const { t } = useTranslation("ui");
  const { pullDistance, isRefreshing, containerProps } = usePullToRefresh({
    threshold,
    maxPull,
    onRefresh,
    enabled,
  });

  // On web platforms, just render children without any pull behavior
  if (!Capacitor.isNativePlatform()) {
    return <div className={className}>{children}</div>;
  }

  const progress = Math.min(pullDistance / threshold, 1);
  const showIndicator = pullDistance > 10 || isRefreshing;
  const readyToRefresh = pullDistance >= threshold;

  return (
    <div {...containerProps} className={cn("relative", className)}>
      {/* Pull indicator */}
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 z-50 flex items-center justify-center overflow-hidden transition-opacity",
          showIndicator ? "opacity-100" : "opacity-0"
        )}
        style={{
          height: isRefreshing ? 48 : Math.max(pullDistance, 0),
        }}
      >
        <div
          className={cn(
            "flex items-center gap-2 rounded-full border border-border bg-background/95 px-4 py-2 shadow-sm backdrop-blur-sm transition-transform",
            isRefreshing && "animate-pulse"
          )}
          style={{
            transform: `scale(${0.6 + progress * 0.4})`,
          }}
        >
          <Loader2
            className={cn("h-4 w-4 text-muted-foreground", isRefreshing && "animate-spin")}
            style={{
              transform: isRefreshing ? undefined : `rotate(${progress * 360}deg)`,
            }}
          />
          <span className="font-medium text-muted-foreground text-xs">
            {isRefreshing
              ? t("pullToRefresh.refreshing")
              : readyToRefresh
                ? t("pullToRefresh.release")
                : t("pullToRefresh.pull")}
          </span>
        </div>
      </div>

      {/* Content container with transform */}
      <div
        style={{
          transform: isRefreshing
            ? "translateY(48px)"
            : pullDistance > 0
              ? `translateY(${pullDistance}px)`
              : undefined,
          transition: pullDistance === 0 && !isRefreshing ? "transform 0.2s ease-out" : undefined,
        }}
      >
        {children}
      </div>
    </div>
  );
}
