import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UpdateReadyToast } from "./UpdateReadyToast";

type Shown = {
  message: string;
  options: {
    action: { onClick: () => void };
    onClose: () => void;
  };
};

const toasts = vi.hoisted(() => ({ shown: [] as Shown[], dismiss: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: {
    info: (message: string, options: Shown["options"]) => toasts.shown.push({ message, options }),
    dismiss: toasts.dismiss,
  },
}));

const last = () => toasts.shown[toasts.shown.length - 1];

describe("UpdateReadyToast", () => {
  beforeEach(() => {
    toasts.shown = [];
    toasts.dismiss.mockClear();
  });

  it("shows nothing until an update is ready", () => {
    render(<UpdateReadyToast open={false} version="" onClose={vi.fn()} />);
    expect(toasts.shown).toHaveLength(0);
  });

  it("asks only for a reload", () => {
    render(<UpdateReadyToast open version="2.0.0" onClose={vi.fn()} />);
    expect(toasts.shown).toHaveLength(1);
    expect(last().message).toContain("2.0.0");
  });

  it("reports the reader closing it", () => {
    const onClose = vi.fn();
    render(<UpdateReadyToast open version="2.0.0" onClose={onClose} />);
    last().options.onClose();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not count reloading as closing, and comes back if the reload did not happen", async () => {
    const onClose = vi.fn();
    const onReload = vi.fn().mockResolvedValue(undefined);
    render(<UpdateReadyToast open version="2.0.0" onClose={onClose} onReload={onReload} />);

    last().options.action.onClick();
    last().options.onClose();
    expect(onReload).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();

    await vi.waitFor(() => expect(toasts.shown).toHaveLength(2));
  });

  it("takes the toast away when the update is no longer offered", () => {
    const onClose = vi.fn();
    const { rerender } = render(<UpdateReadyToast open version="2.0.0" onClose={onClose} />);
    rerender(<UpdateReadyToast open={false} version="" onClose={onClose} />);
    expect(toasts.dismiss).toHaveBeenCalled();
    last().options.onClose();
    expect(onClose).not.toHaveBeenCalled();
  });
});
