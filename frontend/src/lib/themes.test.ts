import { describe, expect, it } from "vitest";

import { contrastRatio } from "@/lib/oklch";
import {
  DEFAULT_THEME,
  getThemeList,
  resolveThemeChoice,
  THEMES,
  type ThemeColors,
  themeChoiceId,
  variantPalettes,
} from "@/lib/themes";

/** Text the app sets on each surface, held to WCAG AA for body text (4.5:1). */
const TEXT_PAIRS: [keyof ThemeColors, keyof ThemeColors][] = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["foreground", "popover"],
  ["foreground", "secondary"],
  ["foreground", "muted"],
  ["foreground", "accent"],
  ["cardForeground", "card"],
  ["popoverForeground", "popover"],
  ["secondaryForeground", "secondary"],
  ["accentForeground", "accent"],
  ["mutedForeground", "background"],
  ["mutedForeground", "card"],
  ["mutedForeground", "popover"],
  ["mutedForeground", "muted"],
  // A hovered row keeps its muted line.
  ["mutedForeground", "accent"],
  ["sidebarForeground", "sidebar"],
  ["sidebarAccentForeground", "sidebarAccent"],
  ["sidebarPrimaryForeground", "sidebarPrimary"],
  // Error messages.
  ["destructive", "background"],
  ["destructive", "card"],
];

/** Focus rings, held to the 3:1 WCAG asks of a control's outline. */
const OUTLINE_PAIRS: [keyof ThemeColors, keyof ThemeColors][] = [
  ["ring", "background"],
  ["ring", "card"],
];

/**
 * Every palette a person can wear: each theme in each of its variants, both
 * modes, once each (Catppuccin's flavors share one Latte).
 */
const seen = new Set<ThemeColors>();
const palettes = getThemeList().flatMap((theme) =>
  (theme.variants ?? [undefined]).flatMap((variant) => {
    const { light, dark } = variantPalettes(theme, variant);
    const name = variant ? `${theme.id}.${variant.id}` : theme.id;
    return [
      { name: `${name} light`, mode: "light" as const, colors: light },
      { name: `${name} dark`, mode: "dark" as const, colors: dark },
    ].filter(({ colors }) => !seen.has(colors) && seen.add(colors));
  })
);

describe("theme contrast", () => {
  it.each(palettes)("$name carries readable text", ({ colors }) => {
    const failing = TEXT_PAIRS.map(([text, surface]) => ({
      pair: `${text} on ${surface}`,
      ratio: contrastRatio(colors[text], colors[surface], colors.background),
    })).filter(({ ratio }) => ratio < 4.5);
    expect(failing).toEqual([]);
  });

  it.each(palettes)("$name shows its focus ring", ({ colors }) => {
    const failing = OUTLINE_PAIRS.map(([outline, surface]) => ({
      pair: `${outline} on ${surface}`,
      ratio: contrastRatio(colors[outline], colors[surface], colors.background),
    })).filter(({ ratio }) => ratio < 3);
    expect(failing).toEqual([]);
  });

  it.each(palettes)(
    "$name keeps a destructive button's white label readable",
    ({ mode, colors }) => {
      // The button is solid in light mode and 60% over the page in dark (ui/button.tsx).
      const ratio =
        mode === "light"
          ? contrastRatio("1 0 0", colors.destructive)
          : contrastRatio("1 0 0", `${colors.destructive} / 60%`, colors.background);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    }
  );
});

describe("resolveThemeChoice", () => {
  it("wears a theme's default variant for its bare id", () => {
    const choice = resolveThemeChoice("catppuccin");
    expect(choice.variant?.id).toBe("macchiato");
    expect(choice.dark).toBe(THEMES.catppuccin.dark);
  });

  it("swaps only the palette a variant replaces", () => {
    const choice = resolveThemeChoice("catppuccin.mocha");
    expect(choice.variant?.id).toBe("mocha");
    expect(choice.light).toBe(THEMES.catppuccin.light);
    expect(choice.dark).not.toEqual(THEMES.catppuccin.dark);
  });

  it("swaps both palettes for a variant that names both", () => {
    const gold = resolveThemeChoice("elemental.gold");
    const copper = resolveThemeChoice("elemental");
    expect(gold.light).not.toEqual(copper.light);
    expect(gold.dark).not.toEqual(copper.dark);
  });

  it("falls back to the theme's default for an unknown variant", () => {
    expect(resolveThemeChoice("elemental.tin").variant?.id).toBe("copper");
  });

  it("falls back to the default theme for an unknown id", () => {
    expect(resolveThemeChoice("displacer").theme.id).toBe(DEFAULT_THEME);
    expect(resolveThemeChoice(null).theme.id).toBe(DEFAULT_THEME);
  });
});

describe("themeChoiceId", () => {
  it("stores the default variant as the bare theme id", () => {
    expect(themeChoiceId(THEMES.catppuccin, "macchiato")).toBe("catppuccin");
    expect(themeChoiceId(THEMES.kobold)).toBe("kobold");
  });

  it("stores another variant after a dot, within the column's 50 characters", () => {
    expect(themeChoiceId(THEMES.elemental, "obsidian")).toBe("elemental.obsidian");
    for (const theme of getThemeList()) {
      for (const variant of theme.variants ?? []) {
        expect(themeChoiceId(theme, variant.id).length).toBeLessThanOrEqual(50);
      }
    }
  });
});
