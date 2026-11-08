/**
 * Help, in the sidebar or the desktop title bar: one button that opens and
 * closes the Help panel, whatever the server offers.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { currentHelp, updateHelp } from "@/components/help/helpStore";

import { HelpButton } from "./HelpButton";

describe("HelpButton", () => {
  afterEach(() => updateHelp({ open: false }));

  it("opens Help and closes it again", async () => {
    renderWithProviders(<HelpButton />);
    const help = screen.getByRole("button", { name: "Help" });
    expect(help).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(help);
    expect(currentHelp().open).toBe(true);
    expect(help).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(help);
    expect(currentHelp().open).toBe(false);
  });
});
