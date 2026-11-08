import { useEffect } from "react";

import { useGetAppConfig } from "@/api/generated/config/config";
import { useServer } from "@/hooks/useServer";
import { setAccentFaviconColors, syncFaviconWithTheme } from "@/lib/favicon";

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

const clampUnit = (value: number) => Math.max(0, Math.min(1, value));

const srgbToLinear = (value: number) => {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
};

const hexToOklch = (hex: string | undefined | null) => {
  if (!hex) {
    // Default to a neutral gray if no hex provided
    return { l: 0.5, c: 0, h: 0 };
  }
  let normalized = hex.replace("#", "");
  if (normalized.length === 3) {
    normalized = normalized
      .split("")
      .map((char) => `${char}${char}`)
      .join("");
  }

  const r = srgbToLinear(parseInt(normalized.slice(0, 2), 16));
  const g = srgbToLinear(parseInt(normalized.slice(2, 4), 16));
  const b = srgbToLinear(parseInt(normalized.slice(4, 6), 16));

  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;

  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);

  const okL = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const okA = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const okB = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;

  const chroma = Math.sqrt(okA * okA + okB * okB);
  let hue = (Math.atan2(okB, okA) * 180) / Math.PI;
  if (hue < 0) {
    hue += 360;
  }

  return {
    l: clampUnit(okL),
    c: Math.max(0, chroma),
    h: hue,
  };
};

const oklchToString = ({ l, c, h }: { l: number; c: number; h: number }) =>
  `${l.toFixed(3)} ${c.toFixed(3)} ${h.toFixed(2)}`;

const lighten = (oklch: { l: number; c: number; h: number }, amount: number) => ({
  ...oklch,
  l: clampUnit(oklch.l + amount / 100),
});

const darken = (oklch: { l: number; c: number; h: number }, amount: number) => ({
  ...oklch,
  l: clampUnit(oklch.l - amount / 100),
});

const toReadableForeground = (color: { l: number; c: number; h: number }) => {
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
