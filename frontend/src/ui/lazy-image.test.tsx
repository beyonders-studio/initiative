import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LazyImage } from "@/ui/lazy-image";

describe("LazyImage", () => {
  it("reserves the picture's shape before the bytes arrive", () => {
    const { container } = render(<LazyImage src="/uploads/1/a.png" alt="A" aspectRatio={2} />);
    const box = container.firstElementChild as HTMLElement;
    // jsdom normalizes the shorthand; a browser keeps it as written.
    expect(["2", "2 / 1"]).toContain(box.style.aspectRatio);
  });

  it("is deferred and decoded off the main thread, invisible until it has loaded", () => {
    // jsdom has no IntersectionObserver, so the picture is asked for at once.
    render(<LazyImage src="/uploads/1/a.png" alt="A" />);
    const img = screen.getByRole("img", { name: "A" });
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("decoding", "async");
    expect(img.className).toContain("opacity-0");
    fireEvent.load(img);
    expect(img.className).toContain("opacity-100");
  });
});
