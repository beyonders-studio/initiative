/**
 * The one control at the end of a table row.
 *
 * Two things about it are load-bearing rather than cosmetic. A row whose
 * actions are all gated away must draw nothing — an empty trigger promises
 * something is there — and every trigger in a column of identical buttons has
 * to say which row it belongs to, or a screen reader hears "Actions" a page
 * at a time.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DropdownMenuItem } from "./dropdown-menu";
import { RowActionsMenu } from "./row-actions-menu";

describe("RowActionsMenu", () => {
  it("names the row it acts on", () => {
    render(
      <RowActionsMenu subject="jordan#1234">
        <DropdownMenuItem>Suspend</DropdownMenuItem>
      </RowActionsMenu>
    );

    expect(screen.getByRole("button", { name: "Actions for jordan#1234" })).toBeInTheDocument();
  });

  it("keeps its actions behind the trigger until asked", async () => {
    render(
      <RowActionsMenu subject="jordan#1234">
        <DropdownMenuItem>Suspend</DropdownMenuItem>
        <DropdownMenuItem>Delete</DropdownMenuItem>
      </RowActionsMenu>
    );

    expect(screen.queryByText("Suspend")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Actions for/ }));

    expect(await screen.findByText("Suspend")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("draws nothing when every action is gated away", () => {
    // The shape a caller actually produces: an array of `cond && <Item/>`,
    // all false. `Children.count` would call that two items.
    const { container } = render(
      <RowActionsMenu subject="jordan#1234">
        {false && <DropdownMenuItem>Suspend</DropdownMenuItem>}
        {null}
      </RowActionsMenu>
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
