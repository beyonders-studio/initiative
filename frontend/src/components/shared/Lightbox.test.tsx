import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";

const items: LightboxItem[] = [
  { id: 1, src: "/uploads/1/a.png", alt: "First" },
  { id: 2, src: "/uploads/1/b.png", alt: "Second" },
  { id: 3, src: "/uploads/1/c.png", alt: "Third" },
];

describe("Lightbox", () => {
  it("shows the picture at the index and where it is in the set", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    expect(screen.getByRole("img", { name: "Second" })).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("draws its panel beside the picture, and leaves keys typed there to it", () => {
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={1}
        onIndexChange={onIndexChange}
        panel={<input aria-label="Caption" />}
      />
    );
    const caption = screen.getByRole("textbox", { name: "Caption" });
    fireEvent.keyDown(caption, { key: "ArrowRight" });
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("pages with the arrow keys and the chevrons", () => {
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={1}
        onIndexChange={onIndexChange}
      />
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
  });

  it("offers no way past either end", () => {
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={0}
        onIndexChange={onIndexChange}
      />
    );
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("a single picture is just a picture", () => {
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={[items[0]]}
        index={0}
        onIndexChange={() => {}}
      />
    );
    expect(screen.queryByText(/\/ 1/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("closes on a click beside the picture, not on the picture itself", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <Lightbox open onOpenChange={onOpenChange} items={items} index={1} onIndexChange={vi.fn()} />
    );
    // The content fills the overlay, so the dark around the picture is the
    // only backdrop there is — clicking it dismisses, the way clicking
    // outside any other dialog does.
    const picture = screen.getByRole("img", { name: "Second" });
    fireEvent.click(picture);
    expect(onOpenChange).not.toHaveBeenCalled();

    const stage = picture.parentElement as HTMLElement;
    fireEvent.click(stage);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("asks for more as the reader nears the end", () => {
    const onNearEnd = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={2}
        onIndexChange={() => {}}
        onNearEnd={onNearEnd}
      />
    );
    expect(onNearEnd).toHaveBeenCalled();
  });

  it("zooms in and back out from the toolbar", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    const picture = screen.getByRole("img", { name: "Second" });

    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    expect(picture).toHaveStyle({ transform: "translate3d(0px, 0px, 0) scale(1)" });

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(picture.style.transform).toContain("scale(1.5)");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(picture.style.transform).toContain("scale(1)");
  });

  it("zooms with the keyboard and resets with 0", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    const picture = screen.getByRole("img", { name: "Second" });

    fireEvent.keyDown(window, { key: "+" });
    expect(picture.style.transform).toContain("scale(1.5)");

    fireEvent.keyDown(window, { key: "0" });
    expect(picture.style.transform).toContain("scale(1)");
  });

  it("pages with the arrow keys only while the picture fits", async () => {
    const user = userEvent.setup();
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={1}
        onIndexChange={onIndexChange}
      />
    );

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).not.toHaveBeenCalled();

    // The chevrons go too — a zoomed picture is being read, not paged.
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "0" });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
  });

  it("a double tap zooms in, and the next one comes back out", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    const picture = screen.getByRole("img", { name: "Second" });
    const stage = picture.parentElement as HTMLElement;

    fireEvent.doubleClick(stage, { clientX: 100, clientY: 100 });
    expect(picture.style.transform).toContain("scale(2.5)");

    fireEvent.doubleClick(stage, { clientX: 100, clientY: 100 });
    expect(picture.style.transform).toContain("scale(1)");
  });

  it("a new picture is shown at its own size", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("img", { name: "Second" }).style.transform).toContain("scale(1.5)");

    rerender(
      <Lightbox open onOpenChange={() => {}} items={items} index={2} onIndexChange={() => {}} />
    );

    expect(screen.getByRole("img", { name: "Third" }).style.transform).toContain("scale(1)");
  });

  it("two fingers pinch the picture larger, and back", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={vi.fn()} />
    );
    const picture = screen.getByRole("img", { name: "Second" });
    const stage = picture.parentElement as HTMLElement;
    const touch = { pointerType: "touch", clientY: 100 };

    // Two fingers 100 apart, spread to 200: twice the size.
    fireEvent.pointerDown(stage, { ...touch, pointerId: 1, clientX: 100 });
    fireEvent.pointerDown(stage, { ...touch, pointerId: 2, clientX: 200 });
    fireEvent.pointerMove(stage, { ...touch, pointerId: 2, clientX: 300 });
    expect(picture.style.transform).toContain("scale(2)");

    // Brought back together past fit-to-screen, it settles at fit-to-screen.
    fireEvent.pointerMove(stage, { ...touch, pointerId: 2, clientX: 120 });
    fireEvent.pointerUp(stage, { ...touch, pointerId: 2, clientX: 120 });
    fireEvent.pointerUp(stage, { ...touch, pointerId: 1, clientX: 100 });
    expect(picture.style.transform).toContain("scale(1)");
  });

  it("a press that began on the picture never closes it", () => {
    // A drag captures the pointer, and the browser then delivers the click to
    // the capture target — so a tap on the picture arrives looking exactly
    // like a tap on the dark around it. Where the press landed is what counts.
    const onOpenChange = vi.fn();
    renderWithProviders(
      <Lightbox open onOpenChange={onOpenChange} items={items} index={1} onIndexChange={vi.fn()} />
    );
    const picture = screen.getByRole("img", { name: "Second" });
    const stage = picture.parentElement as HTMLElement;
    const touch = { pointerType: "touch", pointerId: 1, clientX: 100, clientY: 100 };

    fireEvent.pointerDown(picture, touch);
    fireEvent.pointerUp(picture, touch);
    fireEvent.click(stage);
    expect(onOpenChange).not.toHaveBeenCalled();

    // The same tap beside it still dismisses.
    fireEvent.pointerDown(stage, { ...touch, clientX: 5, clientY: 5 });
    fireEvent.pointerUp(stage, { ...touch, clientX: 5, clientY: 5 });
    fireEvent.click(stage);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("a mouse press with nothing to drag captures nothing", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={vi.fn()} items={items} index={1} onIndexChange={vi.fn()} />
    );
    const picture = screen.getByRole("img", { name: "Second" });
    const stage = picture.parentElement as HTMLElement;
    const capture = vi.spyOn(stage, "setPointerCapture");

    // An unzoomed mouse press has no gesture to follow, and capturing the
    // pointer anyway is what used to retarget its click onto the stage and
    // dismiss the viewer.
    fireEvent.pointerDown(picture, { pointerType: "mouse", pointerId: 1, clientX: 100 });
    fireEvent.pointerUp(picture, { pointerType: "mouse", pointerId: 1, clientX: 100 });
    expect(capture).not.toHaveBeenCalled();

    // Zoomed there is a pan to follow, so it does capture.
    fireEvent.keyDown(window, { key: "+" });
    fireEvent.pointerDown(picture, { pointerType: "mouse", pointerId: 1, clientX: 100 });
    expect(capture).toHaveBeenCalled();
  });
});
