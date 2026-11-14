import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { syncFaviconWithTheme } from "@/lib/favicon";
import { getItem, setFirstPaintHint, setItem } from "@/lib/storage";

export type Theme = "light" | "dark" | "system";
type ResolvedTheme = Exclude<Theme, "system">;

interface ThemeState {
  preference: Theme;
  resolved: ResolvedTheme;
}

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

// Also read by public/theme-boot.js, which paints the first frame in the
// right theme before this provider mounts; keep the two in step. On native
// the value is mirrored into localStorage for it (see setFirstPaintHint).
const THEME_STORAGE_KEY = "initiative-theme";
const THEME_CYCLE: Theme[] = ["system", "light", "dark"];

const getPreferredTheme = (): Theme => {
  const stored = getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
};

const resolveThemePreference = (theme: Theme): ResolvedTheme => {
  if (theme === "system") {
    if (typeof window !== "undefined" && window.matchMedia) {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      return prefersDark ? "dark" : "light";
    }
    return "light";
  }
  return theme;
};

const getInitialThemeState = (): ThemeState => {
  const preference = getPreferredTheme();
  return {
    preference,
    resolved: resolveThemePreference(preference),
  };
};

const applyThemeClass = (theme: ResolvedTheme) => {
  if (typeof document === "undefined") {
    return;
  }
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
};

export const ThemeProvider = ({ children }: { children: React.ReactNode }) => {
  const [themeState, setThemeState] = useState<ThemeState>(() => getInitialThemeState());
  const { preference: theme, resolved: resolvedTheme } = themeState;

  useEffect(() => {
    applyThemeClass(resolvedTheme);
    syncFaviconWithTheme(resolvedTheme);
  }, [resolvedTheme]);

  useEffect(() => {
    setItem(THEME_STORAGE_KEY, theme);
    setFirstPaintHint(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const handler = (event: MediaQueryListEvent) => {
      setThemeState((current) => {
        if (current.preference !== "system") {
          return current;
        }
        const nextResolved = event.matches ? "dark" : "light";
        if (current.resolved === nextResolved) {
          return current;
        }
        return { ...current, resolved: nextResolved };
      });
    };

    mediaQuery.addEventListener("change", handler);
    return () => mediaQuery.removeEventListener("change", handler);
  }, []);

  const setTheme = useCallback((nextTheme: Theme) => {
    setThemeState((current) => {
      if (current.preference === nextTheme) {
        const nextResolved = resolveThemePreference(nextTheme);
        if (current.resolved === nextResolved) {
          return current;
        }
        return { ...current, resolved: nextResolved };
      }
      return {
        preference: nextTheme,
        resolved: resolveThemePreference(nextTheme),
      };
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => {
      const currentIndex = THEME_CYCLE.indexOf(current.preference);
      const nextTheme = THEME_CYCLE[(currentIndex + 1) % THEME_CYCLE.length];
      return {
        preference: nextTheme,
        resolved: resolveThemePreference(nextTheme),
      };
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};
