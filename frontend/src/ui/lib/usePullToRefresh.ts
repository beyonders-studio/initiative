import { Capacitor } from "@capacitor/core";
import { useCallback, useEffect, useRef, useState } from "react";

interface UsePullToRefreshOptions {
  /** Threshold in pixels to trigger refresh (default: 80) */
  threshold?: number;
  /** Maximum pull distance in pixels (default: 120) */
  maxPull?: number;
  /** Callback when refresh is triggered */
  onRefresh: () => Promise<void>;
  /** Whether the feature is enabled (default: true) */
  enabled?: boolean;
}

interface UsePullToRefreshReturn {
  /** Whether the user is currently pulling */
  isPulling: boolean;
  /** Current pull distance in pixels */
  pullDistance: number;
  /** Whether a refresh is currently in progress */
  isRefreshing: boolean;
  /** Props to spread on the container element */
  containerProps: {
    onTouchStart: (e: React.TouchEvent) => void;
    onTouchMove: (e: React.TouchEvent) => void;
    onTouchEnd: () => void;
  };
  /** Ref to attach to the scrollable container (optional, defaults to document) */
  scrollRef: React.RefObject<HTMLElement | null>;
}

export function usePullToRefresh({
  threshold = 80,
  maxPull = 120,
  onRefresh,
  enabled = true,
}: UsePullToRefreshOptions): UsePullToRefreshReturn {
  const [isPulling, setIsPulling] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const startYRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLElement | null>(null);

  // Only enable on native platforms
  const isNative = Capacitor.isNativePlatform();
  const isEnabled = enabled && isNative;

  const getScrollTop = useCallback(() => {
    if (scrollRef.current) {
      return scrollRef.current.scrollTop;
    }
    // The app scrolls inside its own element rather than the document, so the
    // window's offset is always zero and would read as "already at the top".
    const scroller = document.querySelector("[data-app-scroll]");
    if (scroller) {
      return scroller.scrollTop;
    }
    return window.scrollY || document.documentElement.scrollTop;
  }, []);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (!isEnabled || isRefreshing) {
        return;
      }
      // Only start tracking if at the top of scroll
      if (getScrollTop() === 0) {
        startYRef.current = e.touches[0].clientY;
        setIsPulling(true);
      }
    },
    [isEnabled, isRefreshing, getScrollTop]
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!isEnabled || startYRef.current === null || isRefreshing) {
        return;
      }

      const currentY = e.touches[0].clientY;
      const diff = currentY - startYRef.current;

      if (diff > 0 && getScrollTop() === 0) {
        // Pulling down while at top
        const distance = Math.min(diff * 0.5, maxPull); // Apply resistance
        setPullDistance(distance);

        // Prevent default scroll behavior when pulling
        if (distance > 10) {
          e.preventDefault();
        }
      } else {
        // User scrolled up or not at top, reset
        setPullDistance(0);
        startYRef.current = null;
        setIsPulling(false);
      }
    },
    [isEnabled, isRefreshing, maxPull, getScrollTop]
  );

  const handleTouchEnd = useCallback(async () => {
    if (!isEnabled) {
      return;
    }

    const shouldRefresh = pullDistance >= threshold;

    if (shouldRefresh && !isRefreshing) {
      setIsRefreshing(true);
      try {
        await onRefresh();
      } finally {
        setIsRefreshing(false);
      }
    }

    // Reset state
    setPullDistance(0);
    startYRef.current = null;
    setIsPulling(false);
  }, [isEnabled, pullDistance, threshold, isRefreshing, onRefresh]);

  // Reset state when disabled
  useEffect(() => {
    if (!isEnabled) {
      setPullDistance(0);
      setIsPulling(false);
      startYRef.current = null;
    }
  }, [isEnabled]);

  const containerProps = {
    onTouchStart: handleTouchStart,
    onTouchMove: handleTouchMove,
    onTouchEnd: handleTouchEnd,
  };

  return {
    isPulling,
    pullDistance,
    isRefreshing,
    containerProps,
    scrollRef,
  };
}
