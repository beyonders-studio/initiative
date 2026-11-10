/**
 * The color theme as the document wears it: the chosen variant's tokens, and
 * for a theme with a finish, the root attribute and `--metal` its sheen reads.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { themeCssVariables, useColorTheme } from "@/hooks/useColorTheme";
import { THEMES } from "@/lib/themes";

const auth = vi.hoisted(() => ({ colorTheme: "kobold" }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { color_theme: auth.colorTheme } }),
}));
vi.mock("@/hooks/useTheme", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

afterEach(() => {
  const root = document.documentElement;
  root.removeAttribute("style");
  delete root.dataset.colorFinish;
});

describe("themeCssVariables", () => {
  it("wears the chosen variant's palette", () => {
    const mocha = THEMES.catppuccin.variants?.find((variant) => variant.id === "mocha");
    expect(themeCssVariables("catppuccin.mocha", "dark")["--background"]).toBe(
      `oklch(${mocha?.dark?.background})`
    );
    expect(themeCssVariables("catppuccin.mocha", "light")["--background"]).toBe(
      `oklch(${THEMES.catppuccin.light.background})`
    );
  });

  it("names the metal only for a theme with a finish", () => {
    expect(themeCssVariables("elemental.gold", "light")["--metal"]).toBeDefined();
    expect(themeCssVariables("nord", "light")["--metal"]).toBeUndefined();
  });
});

describe("useColorTheme", () => {
  it("sets the finish on the root and takes it off again", () => {
    const root = document.documentElement;
    auth.colorTheme = "elemental.obsidian";
    const { rerender } = renderHook(() => useColorTheme());
    expect(root.dataset.colorFinish).toBe("metallic");
    expect(root.style.getPropertyValue("--metal")).not.toBe("");

    auth.colorTheme = "nord";
    rerender();
    expect(root.dataset.colorFinish).toBeUndefined();
    expect(root.style.getPropertyValue("--metal")).toBe("");
  });
});
