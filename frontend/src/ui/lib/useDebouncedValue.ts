import { useEffect, useState } from "react";

/**
 * Returns ``value`` after it has remained unchanged for ``delay`` ms.
 *
 * Useful for driving search/typeahead queries: the input updates state on
 * every keystroke, but downstream effects (refetches, expensive memos) only
 * see the latest value once the user pauses. Reset the timer on every
 * change so rapid typing collapses to a single fire.
 */
export function useDebouncedValue<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
