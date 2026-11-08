import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

/** Tailwind's breakpoints, narrowest first; "base" is below sm. styles.css says where each starts. */
export const WIDTH_CLASSES = ["base", "sm", "md", "lg", "xl"] as const;
export type WidthClass = (typeof WIDTH_CLASSES)[number];

/** Whether `current` is `least` or wider. */
export const atLeast = (current: WidthClass, least: WidthClass): boolean =>
  WIDTH_CLASSES.indexOf(current) >= WIDTH_CLASSES.indexOf(least);

/** Where a class starts, as styles.css declares it: `--breakpoint-<name>` on :root. */
const breakpoint = (name: WidthClass): string => {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(`--breakpoint-${name}`)
    .trim();
  if (!value) throw new Error(`--breakpoint-${name} is not set; styles.css declares it.`);
  return value;
};

/** A breakpoint in pixels, for measuring an element: rem against the root's font size. */
const breakpointPixels = (name: WidthClass): number => {
  const value = breakpoint(name);
  const amount = Number.parseFloat(value);
  if (value.endsWith("rem")) {
    return amount * Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  }
  return amount;
};

const classForWidth = (width: number): WidthClass => {
  let current: WidthClass = "base";
  for (const name of WIDTH_CLASSES.slice(1)) {
    if (width >= breakpointPixels(name)) current = name;
  }
  return current;
};

/** The screen's breakpoint: for the sidebar, navigation and other chrome. */
export const useWidthClass = (): WidthClass => {
  const queries = useMemo(
    () => WIDTH_CLASSES.slice(1).map((name) => window.matchMedia(`(width >= ${breakpoint(name)})`)),
    []
  );
  const subscribe = useCallback(
    (onChange: () => void) => {
      for (const query of queries) query.addEventListener("change", onChange);
      return () => {
        for (const query of queries) query.removeEventListener("change", onChange);
      };
    },
    [queries]
  );
  // The queries are nested, so the number that match is the class's index.
  const getSnapshot = useCallback(
    () => WIDTH_CLASSES[queries.filter((query) => query.matches).length],
    [queries]
  );
  return useSyncExternalStore(subscribe, getSnapshot);
};

/**
 * The breakpoint of an element's content box, which is what `canvas-sm:` and
 * its siblings measure: for a page deciding whether a panel fits beside it.
 * Pass the element from a callback ref (`ref={setRegion}`), so a region that
 * mounts late is still measured. `base` until it is.
 */
export const useRegionWidthClass = (region: HTMLElement | null): WidthClass => {
  const [current, setCurrent] = useState<WidthClass>("base");
  useEffect(() => {
    if (!region || typeof ResizeObserver === "undefined") return;
    // Reports the element's size as soon as it is observed, then on each change.
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setCurrent(classForWidth(entry.contentRect.width));
    });
    observer.observe(region);
    return () => observer.disconnect();
  }, [region]);
  return current;
};
