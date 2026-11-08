import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildFileSummary } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { FileType } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";

const file = buildFileSummary({
  name: "Hero",
  file_type: FileType.png,
  thumbnail_url: "/uploads/1/hero-thumb.webp",
});

describe("CollectionFileTile", () => {
  it("opens the file when the wall is not selecting", () => {
    const onActivate = vi.fn();
    renderWithProviders(<CollectionFileTile file={file} onActivate={onActivate} />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }));
    expect(onActivate).toHaveBeenCalledWith({ extend: false });
  });

  it("asks for a range when the click held shift", () => {
    const onActivate = vi.fn();
    renderWithProviders(<CollectionFileTile file={file} onActivate={onActivate} selecting />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }), { shiftKey: true });
    expect(onActivate).toHaveBeenCalledWith({ extend: true });
  });

  it("says whether it is in the selection, and only while selecting", () => {
    const { rerender } = renderWithProviders(
      <CollectionFileTile file={file} onActivate={vi.fn()} selecting selected />
    );
    expect(screen.getByRole("button", { name: "Hero" })).toHaveAttribute("aria-pressed", "true");
    rerender(<CollectionFileTile file={file} onActivate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Hero" })).not.toHaveAttribute("aria-pressed");
  });

  it("shows its thumbnail, and a file without one its name", () => {
    const { rerender } = renderWithProviders(
      <CollectionFileTile file={file} onActivate={vi.fn()} />
    );
    expect(screen.getByRole("img", { name: "Hero" })).toHaveAttribute(
      "src",
      expect.stringContaining("hero-thumb.webp")
    );
    rerender(
      <CollectionFileTile file={buildFileSummary({ name: "Budget" })} onActivate={vi.fn()} />
    );
    expect(screen.getByRole("button", { name: "Budget" })).toHaveTextContent("Budget");
  });
});
