import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatusMessage } from "./status-message";

describe("StatusMessage", () => {
  it("reports a failed read as an alert, and asks again on Try again", async () => {
    const onRetry = vi.fn();
    render(<StatusMessage onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load this.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("says its own title without an alert or a retry", () => {
    render(<StatusMessage title="Nothing here" />);

    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
