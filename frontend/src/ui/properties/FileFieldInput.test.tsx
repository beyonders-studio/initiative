import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type FileFieldFiles, FileFieldInput } from "./FileFieldInput";

describe("FileFieldInput", () => {
  it("offers what find answers once opened, and takes the file picked", async () => {
    const user = userEvent.setup();
    const find = vi.fn(async (query: string) =>
      query ? [{ id: 7, label: "Budget" }] : [{ id: 3, label: "Notes" }]
    );
    const files: FileFieldFiles = {
      find,
      href: (fileId) => `/files/${fileId}`,
      preview: () => null,
      newFile: () => null,
    };
    const onChange = vi.fn();
    render(<FileFieldInput value={null} shown={null} onChange={onChange} files={files} />);

    expect(find).not.toHaveBeenCalled();
    await user.click(screen.getByRole("combobox", { name: "Thing" }));
    expect(await screen.findByText("Notes")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search by name…"), "bud");
    await user.click(await screen.findByText("Budget"));

    expect(find).toHaveBeenCalledWith("bud");
    expect(onChange).toHaveBeenCalledWith(7);
  });

  it("asks again when the window comes back while it is open", async () => {
    const user = userEvent.setup();
    let latest = "Notes";
    const find = vi.fn(async () => [{ id: 3, label: latest }]);
    const files: FileFieldFiles = {
      find,
      href: (fileId) => `/files/${fileId}`,
      preview: () => null,
      newFile: () => null,
    };
    render(<FileFieldInput value={null} shown={null} onChange={vi.fn()} files={files} />);

    await user.click(screen.getByRole("combobox", { name: "Thing" }));
    expect(await screen.findByText("Notes")).toBeInTheDocument();

    latest = "Notes, renamed";
    fireEvent.focus(window);

    expect(await screen.findByText("Notes, renamed")).toBeInTheDocument();
  });
});
