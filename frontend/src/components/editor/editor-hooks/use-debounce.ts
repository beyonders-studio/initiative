import { useMemo, useRef } from "react";

type DebouncedFn<T extends (...args: never[]) => void> = ((...args: Parameters<T>) => void) & {
  cancel: () => void;
};

function debounce<T extends (...args: any[]) => void>(
  func: T,
  wait: number,
  options?: { maxWait?: number }
): DebouncedFn<T> {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let lastCallTime: number | undefined;
  let lastArgs: Parameters<T> | null = null;
  const maxWait = options?.maxWait;

  const invoke = () => {
    if (lastArgs) {
      const args = lastArgs;
      lastArgs = null;
      lastCallTime = undefined;
      func(...args);
    }
  };

  const debounced = (...args: Parameters<T>) => {
    const now = Date.now();
    lastArgs = args;
    if (lastCallTime === undefined) lastCallTime = now;

    if (timeoutId !== null) clearTimeout(timeoutId);

    if (maxWait !== undefined && now - lastCallTime >= maxWait) {
      invoke();
    } else {
      timeoutId = setTimeout(invoke, wait);
    }
  };

  debounced.cancel = () => {
    if (timeoutId !== null) clearTimeout(timeoutId);
    timeoutId = null;
    lastArgs = null;
    lastCallTime = undefined;
  };

  return debounced as DebouncedFn<T>;
}

export function useDebounce<T extends (...args: never[]) => void>(
  fn: T,
  ms: number,
  maxWait?: number
) {
  const funcRef = useRef<T | null>(null);
  funcRef.current = fn;

  return useMemo(
    () =>
      debounce(
        (...args: Parameters<T>) => {
          if (funcRef.current) {
            funcRef.current(...args);
          }
        },
        ms,
        { maxWait }
      ),
    [ms, maxWait]
  );
}
