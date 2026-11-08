import { useSyncExternalStore } from "react";

/** Whether the page is drawn dark: the `dark` class on the root element, which
 *  the kit's colours follow. */
const resolvedTheme = (): "light" | "dark" =>
  document.documentElement.classList.contains("dark") ? "dark" : "light";

const subscribe = (onChange: () => void) => {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
};

/** The theme the page is drawn in, re-rendering the caller when it changes. */
export const useResolvedTheme = (): "light" | "dark" =>
  useSyncExternalStore(subscribe, resolvedTheme, () => "light");
