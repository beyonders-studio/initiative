/**
 * The account row at the foot of the sidebar, and the menu it opens.
 *
 * What is worth asserting is the shape the row was cut down to — one line for
 * the person, the status under the name rather than in a bubble of its own,
 * the dot on the picture — and that the menu it opens leads with who you are
 * and carries everything the row stopped carrying.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { TooltipProvider } from "@/ui/tooltip";

import { SidebarUserFooter } from "./SidebarUserFooter";

const renderFooter = (overrides: Partial<UserRead> = {}) => {
  const user = buildUser({
    username: "admin",
    discriminator: 1234,
    presence: "online",
    ...overrides,
  });
  const Footer = () => (
    <TooltipProvider>
      <SidebarUserFooter
        user={user}
        canManagePlatformConfig={false}
        canAccessOperatorDashboard={false}
        onLogout={vi.fn()}
        refreshUser={vi.fn().mockResolvedValue(undefined)}
      />
    </TooltipProvider>
  );
  return renderPage(Footer);
};

const openMenu = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("button", { name: /admin#1234/ }));
  return screen.findByRole("menu");
};

describe("SidebarUserFooter", () => {
  it("keeps Help under the person", async () => {
    renderFooter();
    expect(await screen.findByRole("button", { name: "Help" })).toBeInTheDocument();
  });

  it("puts the status under the name, in the same row", async () => {
    renderFooter({ custom_status: { emoji: "🌱", text: "Planting things" } });

    const row = await screen.findByRole("button", { name: /admin#1234/ });
    expect(row).toHaveTextContent("admin#1234");
    expect(row).toHaveTextContent("Planting things");
  });

  it("takes an emoji on its own as a status", async () => {
    renderFooter({ custom_status: { emoji: "🌱", text: null } });

    const row = await screen.findByRole("button", { name: /admin#1234/ });
    expect(row).toHaveTextContent("🌱");
    expect(row).not.toHaveTextContent("Say what you're up to");
  });

  it("invites a status that has not been set", async () => {
    renderFooter({ custom_status: { emoji: null, text: null } });

    const row = await screen.findByRole("button", { name: /admin#1234/ });
    expect(row).toHaveTextContent("Say what you're up to");
  });

  it("shows how you appear on the picture rather than beside it", async () => {
    renderFooter();

    expect(await screen.findByRole("img", { name: "Online" })).toBeInTheDocument();
  });

  it("leads the menu with who you are", async () => {
    const user = userEvent.setup();
    renderFooter();

    const menu = await openMenu(user);

    expect(within(menu).getByTitle("admin#1234")).toBeInTheDocument();
    expect(within(menu).getByText("admin")).toBeInTheDocument();
  });

  it("hangs the status bubble over the banner, and it still edits", async () => {
    const user = userEvent.setup();
    renderFooter({ custom_status: { emoji: null, text: "Planting things" } });

    const menu = await openMenu(user);
    const bubble = within(menu).getByRole("menuitem", { name: "Your status" });
    expect(bubble).toHaveTextContent("Planting things");

    await user.click(bubble);

    expect(await screen.findByLabelText("What are you up to?")).toBeInTheDocument();
  });

  it("opens the status editor from the account menu", async () => {
    const user = userEvent.setup();
    renderFooter();

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Set status" }));

    expect(await screen.findByLabelText("What are you up to?")).toBeInTheDocument();
  });

  it("opens the status editor again after one has been dismissed", async () => {
    const user = userEvent.setup();
    renderFooter();

    for (const pass of [1, 2, 3]) {
      await openMenu(user);
      await user.click(await screen.findByRole("menuitem", { name: "Set status" }));

      const field = await screen.findByLabelText("What are you up to?");
      expect(field, `pass ${pass}`).toBeInTheDocument();
      // Still there a tick later: the menu closing behind it must not take it
      // down with it.
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(screen.queryByLabelText("What are you up to?"), `pass ${pass}`).toBeInTheDocument();

      await user.keyboard("{Escape}");
      await waitFor(() =>
        expect(screen.queryByLabelText("What are you up to?")).not.toBeInTheDocument()
      );
    }
  });

  it("names the presence entry by the state you are in", async () => {
    const user = userEvent.setup();
    renderFooter({ presence: "busy" });

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Busy" }));

    expect(await screen.findByRole("menuitem", { name: /Offline/ })).toBeInTheDocument();
  });

  it("keeps the theme in the account menu rather than in the row", async () => {
    const user = userEvent.setup();
    renderFooter();

    expect(screen.queryByRole("button", { name: "Toggle theme" })).not.toBeInTheDocument();

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Theme" }));

    expect(await screen.findByRole("menuitemradio", { name: "Dark" })).toBeInTheDocument();
  });

  it("drills into the fly-outs on a phone, and climbs back out", async () => {
    const wide = window.innerWidth;
    window.innerWidth = 500;
    try {
      const user = userEvent.setup();
      renderFooter();

      await openMenu(user);
      // Nothing to hover into: the entry replaces the menu with its choices.
      await user.click(await screen.findByRole("menuitem", { name: /Theme/ }));

      expect(await screen.findByRole("menuitemradio", { name: "Dark" })).toBeInTheDocument();
      expect(screen.queryByRole("menuitem", { name: "Set status" })).not.toBeInTheDocument();

      await user.click(await screen.findByRole("menuitem", { name: "Back" }));

      expect(await screen.findByRole("menuitem", { name: "Set status" })).toBeInTheDocument();

      await user.click(await screen.findByRole("menuitem", { name: /Online/ }));

      expect(await screen.findByRole("menuitem", { name: /Busy/ })).toBeInTheDocument();
    } finally {
      window.innerWidth = wide;
    }
  });

  it("keeps running the place in a section of its own", async () => {
    const user = userEvent.setup();
    const Footer = () => (
      <TooltipProvider>
        <SidebarUserFooter
          user={buildUser({ username: "admin", discriminator: 1234, presence: "online" })}
          canManagePlatformConfig
          canAccessOperatorDashboard
          onLogout={vi.fn()}
          refreshUser={vi.fn().mockResolvedValue(undefined)}
        />
      </TooltipProvider>
    );
    renderPage(Footer);

    const menu = await openMenu(user);
    const rows = within(menu).getAllByRole("menuitem");
    const labels = rows.map((row) => row.textContent?.trim());
    const operator = labels.indexOf("Operator Dashboard");

    expect(operator).toBeGreaterThan(-1);
    expect(labels[operator + 1]).toBe("Platform Settings");
    // A rule of its own above the pair, not just the one before Sign out.
    const separators = within(menu).getAllByRole("separator");
    expect(separators.some((rule) => rule.nextElementSibling === rows[operator])).toBe(true);
  });

  it("leaves community settings and stats to the places that own them", async () => {
    const user = userEvent.setup();
    renderFooter();

    const menu = await openMenu(user);

    expect(within(menu).queryByRole("menuitem", { name: /My Stats/i })).not.toBeInTheDocument();
    expect(
      within(menu).queryByRole("menuitem", { name: /Community settings/i })
    ).not.toBeInTheDocument();
  });
});
