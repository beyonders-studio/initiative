import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./icon-picker";

const svgIn = (container: HTMLElement) => container.querySelector("svg");

describe("Icon", () => {
  it("keeps the room it takes while it loads, then draws", async () => {
    const { container } = render(<Icon name="list-tree" className="size-4" />);

    expect(container.querySelector("span.size-4")).not.toBeNull();
    await waitFor(() => expect(svgIn(container)).not.toBeNull());
  });

  it("draws at once when it is mounted again", async () => {
    const first = render(<Icon name="shapes" />);
    await waitFor(() => expect(svgIn(first.container)).not.toBeNull());
    first.unmount();

    const again = render(<Icon name="shapes" data-testid="again" />);

    expect(svgIn(again.container)).not.toBeNull();
    expect(screen.getByTestId("again").tagName.toLowerCase()).toBe("svg");
  });

  it("draws nothing for a name lucide does not have", () => {
    const { container } = render(<Icon name={"no-such-icon" as never} />);

    expect(svgIn(container)).toBeNull();
  });
});
