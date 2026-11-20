/**
 * The account row at the foot of the sidebar, and the menu it opens.
 *
 * What is worth asserting is the shape the row was cut down to — one line for
 * the person, the status under the name rather than in a bubble of its own,
 * the dot on the picture, each of those set in one click — and that the menu it opens leads with who you are
 * and carries everything the row stopped carrying.
 */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { currentHelp, updateHelp } from "@/components/help/helpStore";
import { setPendingUpdate } from "@/lib/pendingUpdate";
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
  afterEach(() => {
    updateHelp({ open: false });
    setPendingUpdate(null);
  });

  it("opens Help from the account menu rather than from a row of its own", async () => {
    const user = userEvent.setup();
    renderFooter();

    expect(screen.queryByRole("button", { name: "Help" })).not.toBeInTheDocument();

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Help" }));

    expect(currentHelp().open).toBe(true);
  });

  it("offers an update beside the bell while one waits", async () => {
    const user = userEvent.setup();
    const run = vi.fn();
    renderFooter();
    await screen.findByRole("button", { name: /admin#1234/ });
    expect(screen.queryByRole("button", { name: "Update" })).not.toBeInTheDocument();

    act(() => setPendingUpdate({ action: "reload", run }));
    await user.click(await screen.findByRole("button", { name: "Update" }));

    expect(run).toHaveBeenCalled();
  });

  it("puts the status under the name, and opens its editor in one click", async () => {
    const user = userEvent.setup();
    renderFooter({ custom_status: { emoji: "🌱", text: "Planting things", clear_at: null } });

    const status = await screen.findByRole("button", { name: "Your status" });
    expect(status).toHaveTextContent("Planting things");

    await user.click(status);

    expect(await screen.findByLabelText("What are you up to?")).toHaveValue("Planting things");
  });

  it("takes an emoji on its own as a status, and an ended one as none", async () => {
    const { unmount } = renderFooter({
      custom_status: { emoji: "🌱", text: null, clear_at: null },
    });
    const status = await screen.findByRole("button", { name: "Your status" });
    expect(status).toHaveTextContent("🌱");
    expect(status).not.toHaveTextContent("Say what you're up to");
    unmount();

    // Gone the moment it ends, with nothing fetched again.
    renderFooter({
      custom_status: {
        emoji: "🌱",
        text: "Leaving soon",
        clear_at: new Date(Date.now() + 300).toISOString(),
      },
    });
    const ending = await screen.findByRole("button", { name: "Your status" });
    expect(ending).toHaveTextContent("Leaving soon");
    await waitFor(() => expect(ending).toHaveTextContent("Say what you're up to"));
  });

  it("sets a suggestion with the time it usually ends, paused until then", async () => {
    const user = userEvent.setup();
    let sent: Record<string, unknown> | undefined;
    let paused: Record<string, unknown> | undefined;
    server.use(
      http.patch("*/api/v1/me", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(buildUser());
      }),
      http.put("*/api/v1/me/notification-preferences", async ({ request }) => {
        paused = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({});
      })
    );
    renderFooter();

    await user.click(await screen.findByRole("button", { name: "Your status" }));
    await user.click(await screen.findByRole("button", { name: /In a meeting/ }));
    expect(screen.getByRole("combobox")).toHaveTextContent("1 hour");
    await user.click(screen.getByRole("switch", { name: /Pause notifications/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent).toBeDefined());
    const status = sent?.custom_status as { emoji: string; text: string; clear_at: string };
    expect([status.emoji, status.text]).toEqual(["📅", "In a meeting"]);
    const hour = Date.parse(status.clear_at) - Date.now();
    expect(hour).toBeGreaterThan(59 * 60_000);
    expect(hour).toBeLessThanOrEqual(60 * 60_000);
    expect(paused).toEqual({ pause_until: status.clear_at });
  });

  it("holds Save for an end it cannot keep, and not for an erased draft", async () => {
    const user = userEvent.setup();
    const far = new Date(Date.now() + 200 * 86_400_000).toISOString();
    const { unmount } = renderFooter({
      custom_status: { emoji: "🌴", text: "Away", clear_at: far },
    });

    await user.click(await screen.findByRole("button", { name: "Your status" }));
    const pause = await screen.findByRole("switch", { name: /Pause notifications/ });
    expect(await screen.findByText(/A pause runs at most 90 days/)).toBeInTheDocument();
    expect(pause).toBeDisabled();
    unmount();

    renderFooter();
    await user.click(await screen.findByRole("button", { name: "Your status" }));
    await user.type(await screen.findByLabelText("What are you up to?"), "Out");
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Choose a date and time" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Erase" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("sets how you appear from the dot on the picture", async () => {
    const user = userEvent.setup();
    renderFooter();

    await user.click(
      await screen.findByRole("button", { name: "Presence: Online. Change how you appear." })
    );

    expect(await screen.findByRole("menuitem", { name: /Busy/ })).toBeInTheDocument();
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
    renderFooter({ custom_status: { emoji: null, text: "Planting things", clear_at: null } });

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
