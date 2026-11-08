import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const openCommandCenter = vi.fn();
vi.mock("@/components/search/CommandCenter", () => ({
  getOpenCommandCenter: () => openCommandCenter,
}));

import { SidebarSearchButton } from "./SidebarSearchButton";

describe("SidebarSearchButton", () => {
  it("names the community it searches and shows the shortcut hint", () => {
    renderWithProviders(<SidebarSearchButton communityName="Wayfarers" />);

    expect(screen.getByText("Search Wayfarers")).toBeInTheDocument();
    // jsdom's user agent isn't a Mac, so the hint is the ctrl form.
    expect(screen.getByText("Ctrl+K")).toBeInTheDocument();
  });

  it("falls back to a plain label with no community selected", () => {
    renderWithProviders(<SidebarSearchButton />);

    expect(screen.getByText("Search")).toBeInTheDocument();
  });

  it("opens the command center when clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SidebarSearchButton communityName="Wayfarers" />);

    await user.click(screen.getByRole("button"));

    expect(openCommandCenter).toHaveBeenCalled();
  });
});
