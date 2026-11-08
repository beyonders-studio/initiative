import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "./carousel";

const shelf = (
  <Carousel>
    <CarouselContent>
      {["One", "Two", "Three"].map((name) => (
        <CarouselItem key={name}>{name}</CarouselItem>
      ))}
    </CarouselContent>
    <CarouselPrevious />
    <CarouselNext />
  </Carousel>
);

const isItem = (element: HTMLElement) => element.getAttribute("aria-roledescription") === "slide";

describe("Carousel", () => {
  it("shows its arrows only when its items run past its edge", async () => {
    // jsdom lays nothing out, so every item fits in a shelf that measures zero.
    const { unmount } = render(shelf);
    expect(screen.getByRole("button", { name: "Previous slide" })).toHaveClass("hidden");
    expect(screen.getByRole("button", { name: "Next slide" })).toHaveClass("hidden");
    unmount();

    // Three items 100px wide, side by side, on a shelf 250px wide.
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (
      this: HTMLElement
    ) {
      return isItem(this) ? 100 : 250;
    });
    vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (
      this: HTMLElement
    ) {
      return isItem(this) ? [...(this.parentElement?.children ?? [])].indexOf(this) * 100 : 0;
    });
    render(shelf);
    const previous = screen.getByRole("button", { name: "Previous slide" });
    const next = screen.getByRole("button", { name: "Next slide" });
    await waitFor(() => expect(next).not.toHaveClass("hidden"));
    expect(next).toBeEnabled();
    expect(previous).not.toHaveClass("hidden");
    expect(previous).toBeDisabled();
  });
});
