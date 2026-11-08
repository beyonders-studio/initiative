import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sheet, SheetContent, SheetTitle } from "./sheet";

describe("SheetContent", () => {
  it("draws inside its overlay when the sheet is modal", () => {
    render(
      <Sheet open>
        <SheetContent>
          <SheetTitle>Anything</SheetTitle>
        </SheetContent>
      </Sheet>
    );

    const content = screen.getByRole("dialog");
    expect(content.parentElement?.className).toContain("bg-black/80");
  });

  it("draws with no overlay when the sheet is not modal", () => {
    // Radix renders no overlay for a non-modal dialog, so content inside one
    // would never be drawn: the mobile sidebar opened to its backdrop alone.
    render(
      <Sheet open modal={false}>
        <SheetContent>
          <SheetTitle>Sidebar</SheetTitle>
        </SheetContent>
      </Sheet>
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Sidebar")).toBeInTheDocument();
  });
});
