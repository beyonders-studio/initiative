/**
 * The color theme picker: one tile per theme, and for a theme with variants a
 * row of orbs inside its tile that picks one without a second tile.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { ThemePicker } from "./ThemePicker";

const tile = (name: string) => screen.getByRole("radio", { name });

describe("ThemePicker", () => {
  it("shows one tile per theme, the chosen one checked", async () => {
    renderWithProviders(<ThemePicker value="catppuccin.mocha" onChange={vi.fn()} />);

    expect(await screen.findByRole("radio", { name: "Catppuccin" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    expect(tile("Kobold")).toHaveAttribute("aria-checked", "false");
    expect(screen.getAllByRole("radio", { name: "Catppuccin" })).toHaveLength(1);
  });

  it("checks the stored variant's orb", async () => {
    renderWithProviders(<ThemePicker value="catppuccin.mocha" onChange={vi.fn()} />);

    expect(await screen.findByRole("radio", { name: "Use Mocha for dark mode" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    expect(tile("Use Macchiato for dark mode")).toHaveAttribute("aria-checked", "false");
  });

  it("stores a variant as <theme>.<variant>, and the default as the bare theme", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ThemePicker value="kobold" onChange={onChange} />);

    await user.click(await screen.findByRole("radio", { name: "Use Frappé for dark mode" }));
    expect(onChange).toHaveBeenLastCalledWith("catppuccin.frappe");

    await user.click(tile("Use Macchiato for dark mode"));
    expect(onChange).toHaveBeenLastCalledWith("catppuccin");

    await user.click(tile("Use Gold"));
    expect(onChange).toHaveBeenLastCalledWith("elemental.gold");
  });

  it("keeps the chosen variant when its theme's tile is chosen again", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ThemePicker value="elemental.lapis" onChange={onChange} />);

    await user.click(await screen.findByRole("radio", { name: "Elemental" }));
    expect(onChange).toHaveBeenLastCalledWith("elemental.lapis");
  });

  it("chooses another theme in its default variant", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ThemePicker value="catppuccin.mocha" onChange={onChange} />);

    await user.click(await screen.findByRole("radio", { name: "Elemental" }));
    expect(onChange).toHaveBeenLastCalledWith("elemental");

    await user.click(tile("Nord"));
    expect(onChange).toHaveBeenLastCalledWith("nord");
  });
});
