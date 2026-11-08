import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LoadMore } from "./load-more";

describe("LoadMore", () => {
  it("asks for the next page on a click, and holds still while it comes", async () => {
    const onLoadMore = vi.fn();
    const { rerender } = render(<LoadMore hasMore loading={false} onLoadMore={onLoadMore} />);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    rerender(<LoadMore hasMore loading onLoadMore={onLoadMore} />);
    expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled();

    rerender(<LoadMore hasMore={false} loading={false} onLoadMore={onLoadMore} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  // The test setup's IntersectionObserver reports everything as on screen.
  it("asks as it scrolls into view with `auto`, once per page", () => {
    const onLoadMore = vi.fn();
    const { rerender } = render(<LoadMore auto hasMore loading={false} onLoadMore={onLoadMore} />);
    expect(onLoadMore).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<LoadMore auto hasMore loading onLoadMore={onLoadMore} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    rerender(<LoadMore auto hasMore={false} loading={false} onLoadMore={onLoadMore} />);
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });
});
