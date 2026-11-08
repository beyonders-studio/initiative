/**
 * A dialog fits the phone it is opened on.
 *
 * Two rules, both of which were broken and both of which are invisible until
 * somebody opens a dialog on a narrow screen:
 *
 * 1. The content box is a grid, so its children are grid items with
 *    `min-width: auto` — a nowrap row or an editor toolbar sets a content
 *    minimum wider than the dialog and spills out of it rather than shrinking.
 * 2. A caller that sets an unprefixed `max-w-*` replaces the base viewport cap
 *    at *every* width, so the dialog loses its margins on mobile. Widths belong
 *    behind `sm:`, where the base `max-w-[calc(100%-2rem)]` still governs
 *    below it.
 *
 * These are asserted against the classes rather than a layout, because jsdom
 * does no layout — which is exactly why neither was caught by the suite.
 */
import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogFooter, DialogTitle } from "./dialog";

const SRC = path.resolve(__dirname, "../..");

describe("DialogContent", () => {
  it("lets its grid children shrink instead of overflowing", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Anything</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByRole("dialog");
    expect(content.className).toContain("[&>*]:min-w-0");
  });

  // Both sit at the same z-index, so as siblings the later one paints on top,
  // and which is later depends on which mounted last. Inside the overlay, the
  // content is above it whatever the order.
  it("renders its content inside the overlay, so the overlay never covers it", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Anything</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByRole("dialog");
    expect(content.parentElement?.dataset.slot).toBe("dialog-overlay");
  });

  it("keeps the viewport cap when a caller sets its own width", () => {
    render(
      <Dialog open>
        <DialogContent className="sm:max-w-2xl">
          <DialogTitle>Anything</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByRole("dialog");
    // Both survive: the base governs below `sm`, the caller's above it.
    expect(content.className).toContain("max-w-[calc(100%-2rem)]");
    expect(content.className).toContain("sm:max-w-2xl");
  });

  // The class-merge rule the case above relies on, enforced across the app: an
  // unprefixed width silently drops the base cap, and every dialog that did
  // that was edge-to-edge on a phone.
  //
  // What counts as an offender is a *fixed* length — `max-w-lg`, `max-w-md`,
  // `max-w-[32rem]`. A width relative to the viewport (`max-w-[90vw]`) or to
  // the containing block (`max-w-full`, `max-w-[95%]`) still fits the screen it
  // opens on, so it is not this bug even unprefixed.
  //
  // `max-w-none` drops the cap outright, which is only safe when the element
  // bounds itself another way — `w-[min(72rem,95vw)]` is already viewport-
  // bounded, so lifting the max is what makes that width apply. Flagged only
  // when nothing else holds it in.
  it("no dialog sets an unprefixed fixed max width", () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".tsx")) {
          const source = fs.readFileSync(full, "utf-8");
          for (const match of source.matchAll(/<DialogContent\s+className="([^"]*)"/g)) {
            const classes = match[1].split(/\s+/);
            // Does the element bound its own width against the viewport?
            const selfBounded = classes.some(
              (cls) => !cls.includes(":") && /^w-(?:full|\[.*(?:vw|%).*\])$/.test(cls)
            );
            for (const cls of classes) {
              // Anything behind a breakpoint or state is fine — the base cap
              // still governs below it.
              if (cls.includes(":") || !cls.startsWith("max-w-")) continue;
              const value = cls.slice("max-w-".length);
              const fitsAnyway =
                value === "full" || /v[wh]|%/.test(value) || (value === "none" && selfBounded);
              if (!fitsAnyway) {
                offenders.push(`${path.relative(SRC, full)}: ${cls}`);
              }
            }
          }
        }
      }
    };
    walk(SRC);

    expect(offenders, `put these behind sm: — ${offenders.join(", ")}`).toEqual([]);
  });
});

describe("DialogFooter", () => {
  it("draws Cancel, which closes the dialog, and a button that submits its form", async () => {
    const onOpenChange = vi.fn();
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Rename</DialogTitle>
          <form onSubmit={onSubmit}>
            <DialogFooter submitLabel="Save" />
          </form>
        </DialogContent>
      </Dialog>
    );

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("clicks its own handler rather than submitting when given one", async () => {
    const onSubmit = vi.fn();
    const onFormSubmit = vi.fn();
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Delete</DialogTitle>
          <form onSubmit={onFormSubmit}>
            <DialogFooter submitLabel="Delete" cancel="Keep" destructive onSubmit={onSubmit} />
          </form>
        </DialogContent>
      </Dialog>
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onFormSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Keep" })).toBeInTheDocument();
  });

  it("spins the submit button under its pending label and disables both while pending", () => {
    render(
      <Dialog open>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Rename</DialogTitle>
          <DialogFooter submitLabel="Save" pendingLabel="Saving…" pending />
        </DialogContent>
      </Dialog>
    );

    const submit = screen.getByRole("button", { name: "Saving…" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute("aria-busy", "true");
    expect(submit.querySelector("[data-slot='spinner']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("only lays out its children without a submit label", () => {
    render(
      <Dialog open>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Done</DialogTitle>
          <DialogFooter>
            <button type="button">Done</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );

    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Done"]);
  });
});
