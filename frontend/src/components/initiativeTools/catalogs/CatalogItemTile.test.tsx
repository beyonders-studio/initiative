import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildCatalogItem } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { CatalogItemTile } from "@/components/initiativeTools/catalogs/CatalogItemTile";

const image = buildCatalogItem({ title: "Hero" });

describe("CatalogItemTile", () => {
  it("opens the picture when the wall is not selecting", () => {
    const onActivate = vi.fn();
    renderWithProviders(<CatalogItemTile image={image} onActivate={onActivate} />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }));
    expect(onActivate).toHaveBeenCalledWith({ extend: false });
  });

  it("asks for a range when the click held shift", () => {
    const onActivate = vi.fn();
    renderWithProviders(<CatalogItemTile image={image} onActivate={onActivate} selecting />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }), { shiftKey: true });
    expect(onActivate).toHaveBeenCalledWith({ extend: true });
  });

  it("says whether it is in the selection, and only while selecting", () => {
    const { rerender } = renderWithProviders(
      <CatalogItemTile image={image} onActivate={vi.fn()} selecting selected />
    );
    expect(screen.getByRole("button", { name: "Hero" })).toHaveAttribute("aria-pressed", "true");
    rerender(<CatalogItemTile image={image} onActivate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Hero" })).not.toHaveAttribute("aria-pressed");
  });
});
