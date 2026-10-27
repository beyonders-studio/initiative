/**
 * The one place a file dropped from the desktop is taken.
 *
 * A drop skips the file picker, and with it the picker's `accept` filter, so
 * what is worth asserting is that the check the picker would have made is
 * still made — and that a drag which began on the page is not mistaken for
 * files arriving.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FileDropArea } from "./file-drop";

const toastError = vi.fn();
vi.mock("@/lib/mascotToast", () => ({ toast: { error: (m: string) => toastError(m) } }));

const pdf = () => new File(["%PDF"], "brief.pdf", { type: "application/pdf" });
const binary = () => new File(["MZ"], "setup.exe", { type: "application/octet-stream" });

const drag = (files: File[]) => ({ dataTransfer: { types: ["Files"], files } });

const mount = () => {
  const onFile = vi.fn();
  render(<FileDropArea accept=".pdf,.png" onFile={onFile} prompt="Drop a file here, or" />);
  const area = screen.getByText("Drop a file here, or").parentElement as HTMLElement;
  return { onFile, area };
};

beforeEach(() => {
  toastError.mockReset();
});

describe("FileDropArea", () => {
  it("takes a file dropped on it", () => {
    const { onFile, area } = mount();

    fireEvent.dragEnter(area, drag([]));
    expect(screen.getByText("Drop it here")).toBeInTheDocument();
    fireEvent.drop(area, drag([pdf()]));

    expect(onFile).toHaveBeenCalledWith(expect.objectContaining({ name: "brief.pdf" }));
    expect(screen.getByText("Drop a file here, or")).toBeInTheDocument();
  });

  it("says so when nothing dropped is a kind it takes", () => {
    const { onFile, area } = mount();

    fireEvent.drop(area, drag([binary()]));

    expect(onFile).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith("That kind of file can't be uploaded here.");
  });

  it("ignores a drag that started on the page", () => {
    const { onFile, area } = mount();

    fireEvent.dragStart(area);
    fireEvent.dragEnter(area, drag([]));
    expect(screen.queryByText("Drop it here")).not.toBeInTheDocument();
    fireEvent.drop(area, drag([pdf()]));

    expect(onFile).not.toHaveBeenCalled();
  });
});
