import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildLibraryItem } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { LibraryItemTile } from "@/components/initiativeTools/libraries/LibraryItemTile";

const image = buildLibraryItem({ title: "Hero" });

describe("LibraryItemTile", () => {
  it("opens the picture when the wall is not selecting", () => {
    const onActivate = vi.fn();
    renderWithProviders(<LibraryItemTile image={image} onActivate={onActivate} />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }));
    expect(onActivate).toHaveBeenCalledWith({ extend: false });
  });

  it("asks for a range when the click held shift", () => {
    const onActivate = vi.fn();
    renderWithProviders(<LibraryItemTile image={image} onActivate={onActivate} selecting />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }), { shiftKey: true });
    expect(onActivate).toHaveBeenCalledWith({ extend: true });
  });

  it("says whether it is in the selection, and only while selecting", () => {
    const { rerender } = renderWithProviders(
      <LibraryItemTile image={image} onActivate={vi.fn()} selecting selected />
    );
    expect(screen.getByRole("button", { name: "Hero" })).toHaveAttribute("aria-pressed", "true");
    rerender(<LibraryItemTile image={image} onActivate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Hero" })).not.toHaveAttribute("aria-pressed");
  });
});
