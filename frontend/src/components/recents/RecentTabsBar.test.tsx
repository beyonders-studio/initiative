import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  buildRecentCounterGroupItem,
  buildRecentFileItem,
  buildRecentItem,
  buildRecentProjectItem,
} from "@/__tests__/factories/recent.factory";
import { renderWithProviders } from "@/__tests__/helpers/render";

// Mock the TanStack Router ``Link`` to a plain anchor so we don't need a
// router context just to verify the href shape. The component is purely
// presentational; routing semantics belong to integration tests.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, className }: { to: string; children: ReactNode; className?: string }) => (
    <a href={to} className={className}>
      {children}
    </a>
  ),
}));

import { RecentTabsBar } from "./RecentTabsBar";

describe("RecentTabsBar", () => {
  it("renders nothing when there are no items and we're not loading", () => {
    const { container } = renderWithProviders(
      <RecentTabsBar
        items={[]}
        loading={false}
        onClose={() => {}}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders one tab per item with its name and entity-specific icons", () => {
    const items = [
      buildRecentProjectItem({ name: "Lost Mines", icon: "⚒️" }),
      buildRecentFileItem({ name: "Session Notes" }),
      buildRecentCounterGroupItem({ name: "HP Trackers" }),
    ];
    renderWithProviders(
      <RecentTabsBar
        items={items}
        onClose={() => {}}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );

    expect(screen.getByText("Lost Mines")).toBeInTheDocument();
    expect(screen.getByText("Session Notes")).toBeInTheDocument();
    expect(screen.getByText("HP Trackers")).toBeInTheDocument();
    // Project emoji icon should be rendered alongside the name.
    expect(screen.getByText("⚒️")).toBeInTheDocument();
  });

  it("links each item to its community-scoped detail page", () => {
    const items = [
      buildRecentProjectItem({ entity_id: 11, name: "ProjectX" }),
      buildRecentFileItem({ entity_id: 22, name: "DocY" }),
      buildRecentCounterGroupItem({ entity_id: 44, name: "GroupW" }),
    ];
    renderWithProviders(
      <RecentTabsBar
        items={items}
        onClose={() => {}}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );

    expect(screen.getByRole("link", { name: /ProjectX/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/projects/11"
    );
    expect(screen.getByRole("link", { name: /DocY/ })).toHaveAttribute("href", "/c/1/i/5/files/22");
    expect(screen.getByRole("link", { name: /GroupW/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/counter-groups/44"
    );
  });

  // Only calendars can be community-level (a plug-in installs one). Those keep a
  // community address rather than being wedged under an initiative they lack.
  it("links a community-level calendar at its community route", () => {
    renderWithProviders(
      <RecentTabsBar
        items={[
          buildRecentItem({
            entity_type: "calendar",
            entity_id: 12,
            name: "PluginCal",
            initiative_id: null,
          }),
        ]}
        onClose={() => {}}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );

    expect(screen.getByRole("link", { name: /PluginCal/ })).toHaveAttribute(
      "href",
      "/c/1/calendars/12"
    );
  });

  it("dispatches onClose with the item when the X is clicked", async () => {
    const onClose = vi.fn();
    const group = buildRecentCounterGroupItem({ entity_id: 7, name: "Combat" });
    renderWithProviders(
      <RecentTabsBar
        items={[group]}
        onClose={onClose}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );

    const closeButton = screen.getByLabelText(/close combat/i);
    await userEvent.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith(group);
  });

  it("dispatches close / close others / close all from the right-click menu", async () => {
    const onClose = vi.fn();
    const onCloseOthers = vi.fn();
    const onCloseAll = vi.fn();
    const alpha = buildRecentProjectItem({ entity_id: 1, name: "Alpha" });
    const beta = buildRecentProjectItem({ entity_id: 2, name: "Beta" });
    renderWithProviders(
      <RecentTabsBar
        items={[alpha, beta]}
        onClose={onClose}
        onCloseOthers={onCloseOthers}
        onCloseAll={onCloseAll}
      />
    );

    fireEvent.contextMenu(screen.getByText("Alpha"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Close others" }));
    expect(onCloseOthers).toHaveBeenCalledWith(alpha);

    fireEvent.contextMenu(screen.getByText("Alpha"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Close all" }));
    expect(onCloseAll).toHaveBeenCalledTimes(1);
  });

  it("disables 'close others' when only one tab is open", async () => {
    const only = buildRecentProjectItem({ entity_id: 1, name: "Solo" });
    renderWithProviders(
      <RecentTabsBar
        items={[only]}
        onClose={() => {}}
        onCloseOthers={() => {}}
        onCloseAll={() => {}}
      />
    );

    fireEvent.contextMenu(screen.getByText("Solo"));
    const closeOthers = await screen.findByRole("menuitem", { name: "Close others" });
    expect(closeOthers).toHaveAttribute("aria-disabled", "true");
  });
});
