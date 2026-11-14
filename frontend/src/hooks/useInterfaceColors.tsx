import { useEffect } from "react";

import { useGetAppConfig } from "@/api/generated/config/config";
import { useServer } from "@/hooks/useServer";
import { setAccentFaviconColors, syncFaviconWithTheme } from "@/lib/favicon";
import { hexToOklch, type Oklch, oklchToString } from "@/lib/oklch";

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

const clampUnit = (value: number) => Math.max(0, Math.min(1, value));

const lighten = (oklch: Oklch, amount: number) => ({
  ...oklch,
  l: clampUnit(oklch.l + amount / 100),
});

const darken = (oklch: Oklch, amount: number) => ({
  ...oklch,
  l: clampUnit(oklch.l - amount / 100),
});

const toReadableForeground = (color: Oklch) => {
  const targetLightness = color.l >= 0.6 ? 0.18 : 0.96;
  return {
    ...color,
    l: targetLightness,
    c: Math.min(color.c, 0.04),
  };
};

const applyInterfaceColors = (settings: InterfaceSettings) => {
  const light = hexToOklch(settings.light_accent_color);
  const dark = hexToOklch(settings.dark_accent_color);
  const lightSurface = lighten(light, 30);
  const darkSurface = darken(dark, 35);
  const lightForeground = toReadableForeground(light);
  const darkForeground = toReadableForeground(dark);

  const root = document.documentElement;
  root.style.setProperty("--accent-light-color", oklchToString(light));
  root.style.setProperty("--accent-light-surface", oklchToString(lightSurface));
  root.style.setProperty("--accent-light-foreground", oklchToString(lightForeground));
  root.style.setProperty("--accent-dark-color", oklchToString(dark));
  root.style.setProperty("--accent-dark-surface", oklchToString(darkSurface));
  root.style.setProperty("--accent-dark-foreground", oklchToString(darkForeground));
};

export const useInterfaceColors = () => {
  const { isServerConfigured, loading: serverLoading } = useServer();

  // The colours are part of the public config the SPA boots with.
  const query = useGetAppConfig({
    query: {
      staleTime: 1000 * 60 * 10,
      // Don't fetch until server is configured (matters on native platforms)
      enabled: isServerConfigured && !serverLoading,
    },
  });

  useEffect(() => {
    if (query.data) {
      applyInterfaceColors(query.data);
      setAccentFaviconColors(query.data.light_accent_color, query.data.dark_accent_color);
      const isDark = document.documentElement.classList.contains("dark");
      syncFaviconWithTheme(isDark ? "dark" : "light");
    }
  }, [query.data]);

  return query;
};
