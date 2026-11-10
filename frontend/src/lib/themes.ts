/**
 * Color theme definitions for the application.
 *
 * Each theme defines colors for both light and dark modes.
 * Colors are specified in OKLch format (without the oklch() wrapper)
 * as space-separated values: "lightness chroma hue". A published palette is
 * copied in by its hex values through `hex()`.
 *
 * To add a new theme:
 * 1. Add an entry to the THEMES object with a unique id
 * 2. Define all color values for both light and dark modes
 * 3. Describe it under `interface.themeDescriptions.<id>` in every locale's settings.json
 * 4. The theme will automatically appear in the settings dropdown
 *
 * `themes.test.ts` holds every palette to WCAG AA for the text it carries.
 */

import { hex } from "@/lib/oklch";

export interface ThemeColors {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  popover: string;
  popoverForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  accentForeground: string;
  destructive: string;
  border: string;
  input: string;
  ring: string;
  chart1: string;
  chart2: string;
  chart3: string;
  chart4: string;
  chart5: string;
  sidebar: string;
  sidebarForeground: string;
  sidebarPrimary: string;
  sidebarPrimaryForeground: string;
  sidebarAccent: string;
  sidebarAccentForeground: string;
  sidebarBorder: string;
  sidebarRing: string;
}

/**
 * One of a theme's variants: another palette for its dark mode (Catppuccin's
 * flavors) or for both (Elemental's metals). A variant names what it replaces.
 */
export interface ThemeVariant {
  id: string;
  /** A proper name shown as written; without one, `interface.themeVariants.<theme>.<id>` names it. */
  name?: string;
  light?: ThemeColors;
  dark?: ThemeColors;
  /** The color its swatch in the picker shows, when its palette's accent would not tell it apart. */
  swatch?: string;
}

export interface ThemeDefinition {
  id: string;
  name: string;
  /** The palettes the theme wears with no variant chosen (its default variant's). */
  light: ThemeColors;
  dark: ThemeColors;
  /** What the light palette is called, for a theme whose palettes have names. */
  lightName?: string;
  /** The variants, the default first; a choice is stored as `<theme>.<variant>`. */
  variants?: ThemeVariant[];
  /** Which mode the variants change: "dark" (Catppuccin) or "both" (Elemental). */
  variantScope?: "dark" | "both";
  /** A finish laid over the palette across the app (styles.css). */
  finish?: "metallic";
}

/** A stored choice resolved: the theme, the variant chosen (if it has any) and the palettes worn. */
export interface ThemeChoice {
  theme: ThemeDefinition;
  variant?: ThemeVariant;
  light: ThemeColors;
  dark: ThemeColors;
}

/* Catppuccin, https://catppuccin.com/palette — the four flavors, as published. */
interface CatppuccinFlavor {
  text: string;
  subtext1: string;
  overlay0: string;
  surface1: string;
  surface0: string;
  base: string;
  mantle: string;
  crust: string;
  red: string;
  peach: string;
  yellow: string;
  green: string;
  teal: string;
  mauve: string;
  lavender: string;
  blue: string;
}

const LATTE: CatppuccinFlavor = {
  text: "#4c4f69",
  subtext1: "#5c5f77",
  overlay0: "#9ca0b0",
  surface1: "#bcc0cc",
  surface0: "#ccd0da",
  base: "#eff1f5",
  mantle: "#e6e9ef",
  crust: "#dce0e8",
  red: "#d20f39",
  peach: "#fe640b",
  yellow: "#df8e1d",
  green: "#40a02b",
  teal: "#179299",
  mauve: "#8839ef",
  lavender: "#7287fd",
  blue: "#1e66f5",
};

const FRAPPE: CatppuccinFlavor = {
  text: "#c6d0f5",
  subtext1: "#b5bfe2",
  overlay0: "#737994",
  surface1: "#51576d",
  surface0: "#414559",
  base: "#303446",
  mantle: "#292c3c",
  crust: "#232634",
  red: "#e78284",
  peach: "#ef9f76",
  yellow: "#e5c890",
  green: "#a6d189",
  teal: "#81c8be",
  mauve: "#ca9ee6",
  lavender: "#babbf1",
  blue: "#8caaee",
};

const MACCHIATO: CatppuccinFlavor = {
  text: "#cad3f5",
  subtext1: "#b8c0e0",
  overlay0: "#6e738d",
  surface1: "#494d64",
  surface0: "#363a4f",
  base: "#24273a",
  mantle: "#1e2030",
  crust: "#181926",
  red: "#ed8796",
  peach: "#f5a97f",
  yellow: "#eed49f",
  green: "#a6da95",
  teal: "#8bd5ca",
  mauve: "#c6a0f6",
  lavender: "#b7bdf8",
  blue: "#8aadf4",
};

const MOCHA: CatppuccinFlavor = {
  text: "#cdd6f4",
  subtext1: "#bac2de",
  overlay0: "#6c7086",
  surface1: "#45475a",
  surface0: "#313244",
  base: "#1e1e2e",
  mantle: "#181825",
  crust: "#11111b",
  red: "#f38ba8",
  peach: "#fab387",
  yellow: "#f9e2af",
  green: "#a6e3a1",
  teal: "#94e2d5",
  mauve: "#cba6f7",
  lavender: "#b4befe",
  blue: "#89b4fa",
};

/**
 * A Catppuccin flavor as the app's tokens. Cards sit on Base, set apart by
 * their Surface1 border, and the quieter surfaces are Crust in Latte and
 * Surface0 in the dark flavors: Subtext1, the muted text, reads at AA on
 * those in every flavor and on nothing lighter. Latte's focus ring is Blue,
 * Lavender being too pale to see on Base.
 */
const catppuccin = (f: CatppuccinFlavor, mode: "light" | "dark"): ThemeColors => {
  const light = mode === "light";
  const raised = f.base;
  const surface = light ? f.crust : f.surface0;
  return {
    background: hex(f.base),
    foreground: hex(f.text),
    card: hex(raised),
    cardForeground: hex(f.text),
    popover: hex(raised),
    popoverForeground: hex(f.text),
    secondary: hex(surface),
    secondaryForeground: hex(f.text),
    muted: hex(surface),
    mutedForeground: hex(f.subtext1),
    accent: hex(surface),
    accentForeground: hex(f.text),
    destructive: hex(f.red),
    border: hex(f.surface1),
    input: hex(f.surface1),
    ring: hex(light ? f.blue : f.lavender),
    chart1: hex(f.peach),
    chart2: hex(f.teal),
    chart3: hex(f.mauve),
    chart4: hex(f.yellow),
    chart5: hex(f.green),
    sidebar: hex(f.mantle),
    sidebarForeground: hex(f.text),
    sidebarPrimary: hex(f.mauve),
    sidebarPrimaryForeground: hex(light ? f.base : f.crust),
    sidebarAccent: hex(f.surface0),
    sidebarAccentForeground: hex(f.text),
    sidebarBorder: hex(f.surface1),
    sidebarRing: hex(f.overlay0),
  };
};

/* Nord, https://www.nordtheme.com/docs/colors-and-palettes */
const NORD = {
  nord0: "#2e3440",
  nord1: "#3b4252",
  nord2: "#434c5e",
  nord3: "#4c566a",
  nord4: "#d8dee9",
  nord5: "#e5e9f0",
  nord6: "#eceff4",
  nord7: "#8fbcbb",
  nord8: "#88c0d0",
  nord9: "#81a1c1",
  nord10: "#5e81ac",
  nord11: "#bf616a",
  nord12: "#d08770",
  nord13: "#ebcb8b",
  nord14: "#a3be8c",
  nord15: "#b48ead",
};

/**
 * Elemental's metals: the hue and chroma each palette is tinted with, and for
 * Obsidian a deeper dark. The finish (styles.css) lays the sheen over them.
 */
interface Metal {
  hue: number;
  chroma: number;
  /** How much darker its dark surfaces sit than the other metals'. */
  depth?: number;
  /** Its swatch in the picker, when the accent alone would pass for another metal's. */
  swatch?: string;
}

const METALS: Record<string, Metal> = {
  copper: { hue: 48, chroma: 0.12 },
  silver: { hue: 250, chroma: 0.018 },
  gold: { hue: 85, chroma: 0.13 },
  roseGold: { hue: 5, chroma: 0.08 },
  lapis: { hue: 265, chroma: 0.16 },
  cobalt: { hue: 255, chroma: 0.13, depth: 0.04, swatch: "0.38 0.15 262" },
  emerald: { hue: 160, chroma: 0.14 },
  garnet: { hue: 22, chroma: 0.15, depth: 0.04 },
  amethyst: { hue: 305, chroma: 0.15 },
  obsidian: { hue: 290, chroma: 0.035, depth: 0.06 },
};

const tone = (l: number, c: number, h: number) => `${l.toFixed(3)} ${c.toFixed(3)} ${h.toFixed(1)}`;

/** A metal's palette for one mode: surfaces tinted with it, its full color on focus and highlights. */
const elemental = (
  { hue: h, chroma: c, depth = 0 }: Metal,
  mode: "light" | "dark"
): ThemeColors => {
  // Charts need color even from the greys, so they keep a floor of chroma.
  const chart = Math.max(c, 0.12);
  if (mode === "light") {
    return {
      background: tone(0.965, c * 0.12, h),
      foreground: tone(0.22, c * 0.25, h),
      card: tone(0.985, c * 0.06, h),
      cardForeground: tone(0.22, c * 0.25, h),
      popover: tone(0.985, c * 0.06, h),
      popoverForeground: tone(0.22, c * 0.25, h),
      secondary: tone(0.92, c * 0.22, h),
      secondaryForeground: tone(0.22, c * 0.25, h),
      muted: tone(0.92, c * 0.22, h),
      mutedForeground: tone(0.47, c * 0.3, h),
      accent: tone(0.9, c * 0.3, h),
      accentForeground: tone(0.22, c * 0.25, h),
      destructive: tone(0.5, 0.2, 27),
      border: tone(0.85, c * 0.3, h),
      input: tone(0.87, c * 0.25, h),
      ring: tone(0.55, c, h),
      chart1: tone(0.58, chart, h),
      chart2: tone(0.6, chart, h + 60),
      chart3: tone(0.52, chart, h - 60),
      chart4: tone(0.66, chart, h + 150),
      chart5: tone(0.45, chart * 0.8, h),
      sidebar: tone(0.94, c * 0.18, h),
      sidebarForeground: tone(0.22, c * 0.25, h),
      sidebarPrimary: tone(0.48, c, h),
      sidebarPrimaryForeground: tone(0.98, c * 0.05, h),
      sidebarAccent: tone(0.89, c * 0.3, h),
      sidebarAccentForeground: tone(0.22, c * 0.25, h),
      sidebarBorder: tone(0.85, c * 0.3, h),
      sidebarRing: tone(0.6, c * 0.6, h),
    };
  }
  return {
    background: tone(0.17 - depth, c * 0.15, h),
    foreground: tone(0.95, c * 0.12, h),
    card: tone(0.21 - depth, c * 0.18, h),
    cardForeground: tone(0.95, c * 0.12, h),
    popover: tone(0.23 - depth, c * 0.2, h),
    popoverForeground: tone(0.95, c * 0.12, h),
    secondary: tone(0.27 - depth, c * 0.2, h),
    secondaryForeground: tone(0.95, c * 0.12, h),
    muted: tone(0.27 - depth, c * 0.2, h),
    mutedForeground: tone(0.75, c * 0.2, h),
    accent: tone(0.3 - depth, c * 0.25, h),
    accentForeground: tone(0.95, c * 0.12, h),
    destructive: tone(0.7, 0.18, 25),
    border: tone(0.33 - depth, c * 0.3, h),
    input: tone(0.3 - depth, c * 0.25, h),
    ring: tone(0.78, c, h),
    chart1: tone(0.75, chart, h),
    chart2: tone(0.78, chart, h + 60),
    chart3: tone(0.7, chart, h - 60),
    chart4: tone(0.82, chart, h + 150),
    chart5: tone(0.62, chart * 0.8, h),
    sidebar: tone(0.14 - depth, c * 0.15, h),
    sidebarForeground: tone(0.95, c * 0.12, h),
    sidebarPrimary: tone(0.78, c, h),
    sidebarPrimaryForeground: tone(0.16, c * 0.2, h),
    sidebarAccent: tone(0.27 - depth, c * 0.22, h),
    sidebarAccentForeground: tone(0.95, c * 0.12, h),
    sidebarBorder: tone(0.3 - depth, c * 0.3, h),
    sidebarRing: tone(0.55, c * 0.6, h),
  };
};

const CATPPUCCIN_DARK: ThemeVariant[] = [
  { id: "macchiato", name: "Macchiato", dark: catppuccin(MACCHIATO, "dark") },
  { id: "frappe", name: "Frappé", dark: catppuccin(FRAPPE, "dark") },
  { id: "mocha", name: "Mocha", dark: catppuccin(MOCHA, "dark") },
];

const ELEMENTAL_METALS: ThemeVariant[] = Object.entries(METALS).map(([id, metal]) => ({
  id,
  light: elemental(metal, "light"),
  dark: elemental(metal, "dark"),
  swatch: metal.swatch,
}));

/**
 * Available color themes.
 * The "kobold" theme is the classic Initiative theme with deep indigo tones.
 */
export const THEMES: Record<string, ThemeDefinition> = {
  kobold: {
    id: "kobold",
    name: "Kobold",
    light: {
      background: "1 0 0",
      foreground: "0.129 0.042 264.695",
      card: "1 0 0",
      cardForeground: "0.129 0.042 264.695",
      popover: "1 0 0",
      popoverForeground: "0.129 0.042 264.695",
      secondary: "0.968 0.007 247.896",
      secondaryForeground: "0.208 0.042 265.755",
      muted: "0.968 0.007 247.896",
      mutedForeground: "0.54 0.046 257.417",
      accent: "0.968 0.007 247.896",
      accentForeground: "0.208 0.042 265.755",
      destructive: "0.577 0.245 27.325",
      border: "0.929 0.013 255.508",
      input: "0.929 0.013 255.508",
      ring: "0.208 0.042 265.755",
      chart1: "0.646 0.222 41.116",
      chart2: "0.6 0.118 184.704",
      chart3: "0.398 0.07 227.392",
      chart4: "0.828 0.189 84.429",
      chart5: "0.769 0.188 70.08",
      sidebar: "0.984 0.003 247.858",
      sidebarForeground: "0.129 0.042 264.695",
      sidebarPrimary: "0.208 0.042 265.755",
      sidebarPrimaryForeground: "0.984 0.003 247.858",
      sidebarAccent: "0.968 0.007 247.896",
      sidebarAccentForeground: "0.208 0.042 265.755",
      sidebarBorder: "0.929 0.013 255.508",
      sidebarRing: "0.704 0.04 256.788",
    },
    dark: {
      background: "0.129 0.042 264.695",
      foreground: "0.984 0.003 247.858",
      card: "0.208 0.042 265.755",
      cardForeground: "0.984 0.003 247.858",
      popover: "0.208 0.042 265.755",
      popoverForeground: "0.984 0.003 247.858",
      secondary: "0.279 0.041 260.031",
      secondaryForeground: "0.984 0.003 247.858",
      muted: "0.279 0.041 260.031",
      mutedForeground: "0.704 0.04 256.788",
      accent: "0.279 0.041 260.031",
      accentForeground: "0.984 0.003 247.858",
      destructive: "0.704 0.191 22.216",
      border: "1 0 0 / 10%",
      input: "1 0 0 / 15%",
      ring: "0.929 0.013 255.508",
      chart1: "0.488 0.243 264.376",
      chart2: "0.696 0.17 162.48",
      chart3: "0.769 0.188 70.08",
      chart4: "0.627 0.265 303.9",
      chart5: "0.645 0.246 16.439",
      sidebar: "0.208 0.042 265.755",
      sidebarForeground: "0.984 0.003 247.858",
      sidebarPrimary: "0.488 0.243 264.376",
      sidebarPrimaryForeground: "0.984 0.003 247.858",
      sidebarAccent: "0.279 0.041 260.031",
      sidebarAccentForeground: "0.984 0.003 247.858",
      sidebarBorder: "1 0 0 / 10%",
      sidebarRing: "0.551 0.027 264.364",
    },
  },
  elemental: {
    id: "elemental",
    name: "Elemental",
    light: ELEMENTAL_METALS[0].light as ThemeColors,
    dark: ELEMENTAL_METALS[0].dark as ThemeColors,
    variants: ELEMENTAL_METALS,
    variantScope: "both",
    finish: "metallic",
  },
  catppuccin: {
    id: "catppuccin",
    name: "Catppuccin",
    lightName: "Latte",
    light: catppuccin(LATTE, "light"),
    dark: CATPPUCCIN_DARK[0].dark as ThemeColors,
    variants: CATPPUCCIN_DARK,
    variantScope: "dark",
  },
  dracula: {
    id: "dracula",
    name: "Dracula",
    light: {
      // Alucard variant
      background: "0.99 0.02 95", // #fffbeb
      foreground: "0.22 0 0", // #1f1f1f
      card: "0.99 0.02 95", // #fffbeb
      cardForeground: "0.22 0 0", // #1f1f1f
      popover: "0.99 0.02 95", // #fffbeb
      popoverForeground: "0.22 0 0", // #1f1f1f
      secondary: "0.94 0.02 95", // slightly darker
      secondaryForeground: "0.22 0 0", // #1f1f1f
      muted: "0.94 0.02 95", // slightly darker
      mutedForeground: "0.52 0.04 260", // muted text
      accent: "0.94 0.02 95", // slightly darker
      accentForeground: "0.22 0 0", // #1f1f1f
      destructive: "0.52 0.19 25", // Red #cb3a2a
      border: "0.90 0.02 95", // border
      input: "0.90 0.02 95", // input
      ring: "0.48 0.19 290", // Purple #644ac9
      chart1: "0.48 0.13 50", // Orange #a34d14
      chart2: "0.47 0.10 230", // Cyan #036a96
      chart3: "0.48 0.19 290", // Purple #644ac9
      chart4: "0.52 0.11 85", // Yellow #846e15
      chart5: "0.44 0.14 140", // Green #14710a
      sidebar: "0.96 0.02 95", // slightly darker than background
      sidebarForeground: "0.22 0 0", // #1f1f1f
      sidebarPrimary: "0.48 0.19 290", // Purple #644ac9
      sidebarPrimaryForeground: "0.99 0.02 95", // light
      sidebarAccent: "0.94 0.02 95", // slightly darker
      sidebarAccentForeground: "0.22 0 0", // #1f1f1f
      sidebarBorder: "0.90 0.02 95", // border
      sidebarRing: "0.52 0.04 260", // muted
    },
    dark: {
      // Dracula
      background: "0.25 0.03 280", // Background #282a36
      foreground: "0.97 0.01 105", // Foreground #f8f8f2
      card: "0.30 0.03 278", // between Background and Current Line
      cardForeground: "0.97 0.01 105", // Foreground #f8f8f2
      popover: "0.30 0.03 278", // between Background and Current Line
      popoverForeground: "0.97 0.01 105", // Foreground #f8f8f2
      secondary: "0.34 0.03 276", // just under Current Line #44475a
      secondaryForeground: "0.97 0.01 105", // Foreground #f8f8f2
      muted: "0.34 0.03 276", // just under Current Line #44475a
      mutedForeground: "0.74 0.07 260", // Comment #6272a4 (lightened for contrast)
      accent: "0.34 0.03 276", // just under Current Line #44475a
      accentForeground: "0.97 0.01 105", // Foreground #f8f8f2
      destructive: "0.73 0.19 23", // Red #ff5555, lifted for contrast on cards
      border: "0.42 0.03 275", // border
      input: "0.42 0.03 275", // input
      ring: "0.72 0.15 300", // Purple #bd93f9
      chart1: "0.73 0.20 350", // Pink #ff79c6
      chart2: "0.88 0.11 205", // Cyan #8be9fd
      chart3: "0.72 0.15 300", // Purple #bd93f9
      chart4: "0.82 0.14 65", // Orange #ffb86c
      chart5: "0.88 0.25 145", // Green #50fa7b
      sidebar: "0.22 0.03 280", // slightly darker than background
      sidebarForeground: "0.97 0.01 105", // Foreground #f8f8f2
      sidebarPrimary: "0.72 0.15 300", // Purple #bd93f9
      sidebarPrimaryForeground: "0.25 0.03 280", // Background
      sidebarAccent: "0.34 0.03 276", // just under Current Line #44475a
      sidebarAccentForeground: "0.97 0.01 105", // Foreground #f8f8f2
      sidebarBorder: "0.42 0.03 275", // border
      sidebarRing: "0.65 0.07 260", // Comment #6272a4 (lightened)
    },
  },
  unicorn: {
    id: "unicorn",
    name: "Unicorn",
    light: {
      background: "1 0 0", // pure white
      foreground: "0.15 0.04 290", // near-black
      card: "1 0 0", // pure white
      cardForeground: "0.15 0.04 290", // near-black
      popover: "1 0 0", // pure white
      popoverForeground: "0.15 0.04 290", // near-black
      secondary: "0.97 0.005 0", // white
      secondaryForeground: "0.53 0.30 340", // hot pink
      muted: "0.97 0.005 0", // white
      mutedForeground: "0.45 0.18 180", // teal
      accent: "0.97 0.005 0", // white
      accentForeground: "0.52 0.28 25", // red
      destructive: "0.55 0.28 25", // red
      border: "0.55 0.30 340", // hot pink border
      input: "0.62 0.24 55", // orange input
      ring: "0.50 0.24 145", // green
      chart1: "0.55 0.30 15", // bold red
      chart2: "0.75 0.18 65", // warm orange
      chart3: "0.45 0.22 155", // deep green
      chart4: "0.65 0.12 230", // soft blue
      chart5: "0.40 0.28 310", // dark violet
      sidebar: "1 0 0", // pure white
      sidebarForeground: "0.15 0.04 290", // near-black
      sidebarPrimary: "0.50 0.30 300", // violet
      sidebarPrimaryForeground: "1 0 0", // pure white
      sidebarAccent: "0.97 0.005 0", // white
      sidebarAccentForeground: "0.50 0.24 145", // green
      sidebarBorder: "0.48 0.22 270", // indigo border
      sidebarRing: "0.62 0.24 55", // orange
    },
    dark: {
      background: "0.1353 0.0444 314.47", // dark purple-black
      foreground: "1 0 0", // pure white
      card: "0.18 0.05 300", // slightly lifted
      cardForeground: "1 0 0", // pure white
      popover: "0.18 0.05 300", // slightly lifted
      popoverForeground: "1 0 0", // pure white
      secondary: "0.16 0.04 300", // dark
      secondaryForeground: "0.85 0.30 145", // neon green
      muted: "0.16 0.04 300", // dark
      mutedForeground: "0.78 0.28 55", // neon orange
      accent: "0.16 0.04 300", // dark
      accentForeground: "0.72 0.30 340", // neon hot pink
      destructive: "0.65 0.30 25", // neon red
      border: "0.90 0.22 90", // neon yellow border
      input: "0.60 0.18 180", // neon teal input
      ring: "0.60 0.28 300", // neon violet
      chart1: "0.65 0.30 15", // neon red
      chart2: "0.82 0.16 65", // bright orange
      chart3: "0.55 0.24 155", // vivid green
      chart4: "0.78 0.10 230", // light blue
      chart5: "0.50 0.30 310", // deep violet
      sidebar: "0.12 0.04 300", // dark
      sidebarForeground: "1 0 0", // pure white
      sidebarPrimary: "0.78 0.28 55", // neon orange
      sidebarPrimaryForeground: "0.10 0.03 300", // near-black
      sidebarAccent: "0.16 0.04 300", // dark
      sidebarAccentForeground: "0.72 0.30 340", // neon hot pink
      sidebarBorder: "0.85 0.30 145", // neon green border
      sidebarRing: "0.65 0.30 25", // neon red
    },
  },
  darkKnight: {
    id: "darkKnight",
    name: "Dark Knight",
    light: {
      background: "0.78 0 0", // medium grey
      foreground: "0.12 0 0", // near-black
      card: "0.82 0 0", // slightly lighter surface
      cardForeground: "0.12 0 0",
      popover: "0.82 0 0",
      popoverForeground: "0.12 0 0",
      secondary: "0.72 0 0", // slightly darker surface
      secondaryForeground: "0.12 0 0",
      muted: "0.72 0 0",
      mutedForeground: "0.32 0 0", // dark grey muted text
      accent: "0.70 0 0",
      accentForeground: "0.12 0 0",
      destructive: "0.40 0.20 27", // dark crimson, legible on the grey
      border: "0.64 0 0",
      input: "0.72 0 0",
      ring: "0.30 0.15 10", // dark maroon focus ring
      chart1: "0.36 0.17 10", // dark maroon
      chart2: "0.72 0.16 85", // golden yellow
      chart3: "0.58 0.19 45", // dark orange
      chart4: "0.25 0.12 8", // deep burgundy
      chart5: "0.62 0.14 70", // amber
      sidebar: "0.74 0 0", // slightly darker than background
      sidebarForeground: "0.12 0 0",
      sidebarPrimary: "0.30 0.15 10", // dark maroon
      sidebarPrimaryForeground: "0.95 0 0",
      sidebarAccent: "0.70 0 0",
      sidebarAccentForeground: "0.12 0 0",
      sidebarBorder: "0.64 0 0",
      sidebarRing: "0.52 0.10 40",
    },
    dark: {
      background: "0 0 0", // true black — AMOLED
      foreground: "0.98 0 0", // near-white
      card: "0.1 0 0", // very dark grey
      cardForeground: "0.98 0 0",
      popover: "0.1 0 0",
      popoverForeground: "0.98 0 0",
      secondary: "0.14 0 0", // slightly elevated surface
      secondaryForeground: "0.98 0 0",
      muted: "0.14 0 0",
      mutedForeground: "0.60 0 0",
      accent: "0.18 0 0",
      accentForeground: "0.98 0 0",
      destructive: "0.68 0.24 25",
      border: "0.18 0 0",
      input: "0.14 0 0",
      ring: "0.85 0.18 90", // bat-signal yellow focus ring
      chart1: "0.40 0.18 10", // dark maroon
      chart2: "0.85 0.18 90", // bat-signal yellow
      chart3: "0.70 0.20 45", // dark orange
      chart4: "0.30 0.14 8", // deep burgundy
      chart5: "0.78 0.15 75", // amber gold
      sidebar: "0 0 0", // true black sidebar
      sidebarForeground: "0.98 0 0",
      sidebarPrimary: "0.85 0.18 90", // bat-signal yellow
      sidebarPrimaryForeground: "0.08 0 0",
      sidebarAccent: "0.14 0 0",
      sidebarAccentForeground: "0.98 0 0",
      sidebarBorder: "0.18 0 0",
      sidebarRing: "0.55 0.12 40",
    },
  },
  orc: {
    id: "orc",
    name: "ORC",
    light: {
      background: "0.93 0.02 115", // light earthy field
      foreground: "0.18 0.05 135", // dark forest green text
      card: "0.96 0.01 110", // off-white card
      cardForeground: "0.18 0.05 135",
      popover: "0.96 0.01 110",
      popoverForeground: "0.18 0.05 135",
      secondary: "0.86 0.03 120", // mossy surface
      secondaryForeground: "0.18 0.05 135",
      muted: "0.86 0.03 120",
      mutedForeground: "0.45 0.05 135", // medium forest muted
      accent: "0.84 0.04 120",
      accentForeground: "0.18 0.05 135",
      destructive: "0.52 0.24 27",
      border: "0.80 0.04 125",
      input: "0.86 0.03 120",
      ring: "0.42 0.20 140", // forest green focus ring
      chart1: "0.42 0.20 140", // forest green
      chart2: "0.60 0.18 115", // yellow-green
      chart3: "0.52 0.16 160", // teal-green
      chart4: "0.55 0.15 80", // olive
      chart5: "0.48 0.14 50", // earthy brown
      sidebar: "0.88 0.03 120", // mossy sidebar
      sidebarForeground: "0.18 0.05 135",
      sidebarPrimary: "0.42 0.20 140", // forest green
      sidebarPrimaryForeground: "0.96 0.01 110",
      sidebarAccent: "0.84 0.04 120",
      sidebarAccentForeground: "0.18 0.05 135",
      sidebarBorder: "0.80 0.04 125",
      sidebarRing: "0.52 0.08 135",
    },
    dark: {
      background: "0.12 0.03 140", // dark cave/swamp
      foreground: "0.90 0.05 105", // warm bone-ivory text
      card: "0.17 0.04 135", // slightly lighter surface
      cardForeground: "0.90 0.05 105",
      popover: "0.17 0.04 135",
      popoverForeground: "0.90 0.05 105",
      secondary: "0.22 0.04 135", // elevated surface
      secondaryForeground: "0.90 0.05 105",
      muted: "0.22 0.04 135",
      mutedForeground: "0.64 0.05 130", // muted green-grey
      accent: "0.26 0.05 135",
      accentForeground: "0.90 0.05 105",
      destructive: "0.68 0.24 25",
      border: "0.26 0.05 135",
      input: "0.22 0.04 135",
      ring: "0.72 0.25 140", // vivid orc-skin green
      chart1: "0.75 0.20 140", // vivid sage/orc green
      chart2: "0.80 0.18 75", // bright amber/honey
      chart3: "0.68 0.22 30", // warm rust/terracotta
      chart4: "0.72 0.16 170", // warm sage teal
      chart5: "0.85 0.15 95", // bright warm yellow
      sidebar: "0.10 0.025 140", // darker cave sidebar
      sidebarForeground: "0.90 0.05 105",
      sidebarPrimary: "0.72 0.25 140", // vivid orc green
      sidebarPrimaryForeground: "0.08 0 0",
      sidebarAccent: "0.22 0.04 135",
      sidebarAccentForeground: "0.90 0.05 105",
      sidebarBorder: "0.26 0.05 135",
      sidebarRing: "0.45 0.10 140",
    },
  },
  monokai: {
    id: "monokai",
    name: "Monokai",
    light: {
      background: "0.97 0.01 95", // warm parchment
      foreground: "0.20 0.02 95", // dark olive text
      card: "0.99 0 0", // near-white card
      cardForeground: "0.20 0.02 95",
      popover: "0.99 0 0",
      popoverForeground: "0.20 0.02 95",
      secondary: "0.91 0.01 95", // slightly tinted surface
      secondaryForeground: "0.20 0.02 95",
      muted: "0.91 0.01 95",
      mutedForeground: "0.47 0.03 95", // olive-grey muted text
      accent: "0.88 0.01 95",
      accentForeground: "0.20 0.02 95",
      destructive: "0.52 0.28 355", // hot pink-red (Monokai red, darkened)
      border: "0.84 0.02 95",
      input: "0.91 0.01 95",
      ring: "0.52 0.18 290", // deep purple focus ring
      chart1: "0.52 0.15 200", // deep cyan
      chart2: "0.52 0.18 290", // deep purple
      chart3: "0.62 0.18 50", // amber orange
      chart4: "0.58 0.28 355", // deep hot pink
      chart5: "0.50 0.22 130", // Monokai lime green #A6E22E
      sidebar: "0.93 0.01 95", // slightly darker parchment
      sidebarForeground: "0.20 0.02 95",
      sidebarPrimary: "0.52 0.18 290", // deep purple
      sidebarPrimaryForeground: "0.97 0.01 95",
      sidebarAccent: "0.88 0.01 95",
      sidebarAccentForeground: "0.20 0.02 95",
      sidebarBorder: "0.84 0.02 95",
      sidebarRing: "0.58 0.08 95",
    },
    dark: {
      background: "0.17 0.01 105", // Monokai bg #272822
      foreground: "0.97 0.01 105", // Monokai fg #F8F8F2
      card: "0.22 0.01 100", // slightly elevated surface
      cardForeground: "0.97 0.01 105",
      popover: "0.22 0.01 100",
      popoverForeground: "0.97 0.01 105",
      secondary: "0.27 0.01 95", // Monokai selection #3E3D32
      secondaryForeground: "0.97 0.01 105",
      muted: "0.27 0.01 95",
      mutedForeground: "0.68 0.03 95", // Monokai comment #75715E, lightened for contrast
      accent: "0.30 0.01 95",
      accentForeground: "0.97 0.01 105",
      destructive: "0.66 0.25 355", // Monokai red #F92672
      border: "0.30 0.02 95",
      input: "0.27 0.01 95",
      ring: "0.70 0.18 290", // Monokai purple #AE81FF
      chart1: "0.85 0.10 200", // Monokai cyan #66D9E8
      chart2: "0.70 0.18 290", // Monokai purple #AE81FF
      chart3: "0.75 0.18 55", // Monokai orange #FD971F
      chart4: "0.62 0.28 355", // Monokai hot pink #F92672
      chart5: "0.82 0.22 130", // Monokai lime green #A6E22E
      sidebar: "0.14 0.01 105", // darker lair — deeper cave
      sidebarForeground: "0.97 0.01 105",
      sidebarPrimary: "0.85 0.10 200", // Monokai cyan
      sidebarPrimaryForeground: "0.10 0.01 105",
      sidebarAccent: "0.22 0.01 100",
      sidebarAccentForeground: "0.97 0.01 105",
      sidebarBorder: "0.30 0.02 95",
      sidebarRing: "0.50 0.08 95",
    },
  },
  nord: {
    id: "nord",
    name: "Nord",
    light: {
      // Snow Storm
      background: hex(NORD.nord5),
      foreground: hex(NORD.nord0),
      card: hex(NORD.nord6),
      cardForeground: hex(NORD.nord0),
      popover: hex(NORD.nord6),
      popoverForeground: hex(NORD.nord0),
      secondary: hex(NORD.nord4),
      secondaryForeground: hex(NORD.nord0),
      muted: hex(NORD.nord4),
      mutedForeground: hex(NORD.nord3),
      accent: hex(NORD.nord4),
      accentForeground: hex(NORD.nord0),
      destructive: "0.50 0.13 18", // nord11, deepened for contrast on Snow Storm
      border: hex(NORD.nord4),
      input: hex(NORD.nord4),
      ring: hex(NORD.nord10),
      chart1: hex(NORD.nord10),
      chart2: hex(NORD.nord7),
      chart3: hex(NORD.nord15),
      chart4: hex(NORD.nord12),
      chart5: hex(NORD.nord14),
      sidebar: hex(NORD.nord6),
      sidebarForeground: hex(NORD.nord0),
      sidebarPrimary: "0.50 0.08 255", // nord10, deepened to carry light text
      sidebarPrimaryForeground: hex(NORD.nord6),
      sidebarAccent: hex(NORD.nord4),
      sidebarAccentForeground: hex(NORD.nord0),
      sidebarBorder: hex(NORD.nord4),
      sidebarRing: hex(NORD.nord9),
    },
    dark: {
      // Polar Night
      background: hex(NORD.nord0),
      foreground: hex(NORD.nord6),
      // Cards sit on nord0 behind their nord3 border: on nord1, no red reads
      // as error text while still carrying a destructive button's white label.
      card: hex(NORD.nord0),
      cardForeground: hex(NORD.nord6),
      popover: hex(NORD.nord1),
      popoverForeground: hex(NORD.nord6),
      secondary: hex(NORD.nord2),
      secondaryForeground: hex(NORD.nord6),
      muted: hex(NORD.nord2),
      mutedForeground: hex(NORD.nord4),
      accent: hex(NORD.nord2),
      accentForeground: hex(NORD.nord6),
      destructive: "0.73 0.14 18", // nord11, lifted for contrast on Polar Night
      border: hex(NORD.nord3),
      input: hex(NORD.nord2),
      ring: hex(NORD.nord8),
      chart1: hex(NORD.nord8),
      chart2: hex(NORD.nord14),
      chart3: hex(NORD.nord15),
      chart4: hex(NORD.nord13),
      chart5: hex(NORD.nord12),
      sidebar: "0.29 0.02 265", // a step below nord0
      sidebarForeground: hex(NORD.nord6),
      sidebarPrimary: hex(NORD.nord8),
      sidebarPrimaryForeground: hex(NORD.nord0),
      sidebarAccent: hex(NORD.nord2),
      sidebarAccentForeground: hex(NORD.nord6),
      sidebarBorder: hex(NORD.nord1),
      sidebarRing: hex(NORD.nord9),
    },
  },
};

export const DEFAULT_THEME = "kobold";

export const getThemeList = (): ThemeDefinition[] => Object.values(THEMES);

export const getTheme = (id: string): ThemeDefinition | undefined => THEMES[id];

/** A theme's default variant, the first it lists. */
export const defaultVariant = (theme: ThemeDefinition): ThemeVariant | undefined =>
  theme.variants?.[0];

/**
 * The palettes a theme wears in one of its variants: what the variant
 * replaces, and the theme's own for the rest.
 */
export const variantPalettes = (
  theme: ThemeDefinition,
  variant: ThemeVariant | undefined
): { light: ThemeColors; dark: ThemeColors } => ({
  light: variant?.light ?? theme.light,
  dark: variant?.dark ?? theme.dark,
});

/**
 * What a stored `color_theme` names: `<theme>` or `<theme>.<variant>`. An
 * unknown theme is the default one, and an unknown variant the theme's default.
 */
export const resolveThemeChoice = (value: string | null | undefined): ThemeChoice => {
  const [themeId, variantId] = (value ?? DEFAULT_THEME).split(".");
  const theme = THEMES[themeId] ?? THEMES[DEFAULT_THEME];
  const variant =
    theme.variants?.find((candidate) => candidate.id === variantId) ?? defaultVariant(theme);
  return { theme, variant, ...variantPalettes(theme, variant) };
};

/** The `color_theme` a choice is stored as; a theme's default variant is its bare id. */
export const themeChoiceId = (theme: ThemeDefinition, variantId?: string): string =>
  !variantId || variantId === defaultVariant(theme)?.id ? theme.id : `${theme.id}.${variantId}`;
