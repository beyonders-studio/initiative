import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./confirm-dialog";

describe("ConfirmDialog", () => {
  it("offers only its cancel button when there is nothing to confirm", async () => {
    const onOpenChange = vi.fn();
    render(<ConfirmDialog open onOpenChange={onOpenChange} title="Read only" cancelLabel="OK" />);

    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["OK"]);
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the confirm button disabled while the caller's fields are unfilled", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        title="Delete?"
        confirmLabel="Delete"
        confirmDisabled
        onConfirm={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("stays open when the confirm handler prevents its default", async () => {
    const onOpenChange = vi.fn();
    const onConfirm = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Delete?"
        confirmLabel="Delete"
        onConfirm={onConfirm}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("gives focus back to the button that opened it when closed", async () => {
    const Harness = () => {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Remove
          </button>
          <ConfirmDialog
            open={open}
            onOpenChange={setOpen}
            title="Remove it?"
            onConfirm={vi.fn()}
          />
        </>
      );
    };
    render(<Harness />);

    const trigger = screen.getByRole("button", { name: "Remove" });
    await userEvent.click(trigger);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
