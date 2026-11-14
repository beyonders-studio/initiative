/**
 * Where the account is signed in.
 *
 * The person reading the page is owed the devices, one row each, then the
 * browsers, where the row they are sitting at is obvious and is not offered a
 * button that would sign them out of the page they are on. A device is
 * removed; a browser is signed out.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { SignedInSection } from "./SignedInSection";

const mocks = vi.hoisted(() => ({
  sessions: vi.fn(),
  endSignedIn: vi.fn(),
  revokeOthers: vi.fn(),
}));

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useSecurity", () => ({
  useMySessions: () => mocks.sessions(),
  useEndSignedIn: () => ({ mutate: mocks.endSignedIn, isPending: false }),
  useRevokeOtherSessions: () => ({ mutate: mocks.revokeOthers, isPending: false }),
}));

const HOUR = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const thisBrowser = {
  id: "11111111-1111-1111-1111-111111111111",
  message_device_id: null,
  device: false,
  label: "Chrome on macOS",
  kind: "desktop" as const,
  ip: "192.168.1.14",
  started_at: ago(30 * 24 * HOUR),
  last_used_at: ago(60_000),
  is_current: true,
};

const otherBrowser = {
  id: "22222222-2222-2222-2222-222222222222",
  message_device_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  device: false,
  label: "Firefox on Windows",
  kind: "desktop" as const,
  ip: "86.20.4.11",
  started_at: ago(5 * 24 * HOUR),
  last_used_at: ago(3 * HOUR),
  is_current: false,
};

const phone = {
  id: "33333333-3333-3333-3333-333333333333",
  message_device_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  device: true,
  label: "Lee's iPhone",
  kind: "mobile" as const,
  ip: "86.20.4.12",
  started_at: ago(10 * 24 * HOUR),
  last_used_at: null,
  is_current: false,
};

/** A message device left behind by a sign-in that has ended. */
const oldPhone = {
  id: null,
  message_device_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  device: false,
  label: "Android",
  kind: "mobile" as const,
  ip: null,
  started_at: ago(60 * 24 * HOUR),
  last_used_at: ago(40 * 24 * HOUR),
  is_current: false,
};

const loaded = <T,>(data: T) => ({ data, isLoading: false, isError: false });

/** The row a label sits in. */
const row = (label: string) => screen.getByText(label).closest("div.rounded-lg") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sessions.mockReturnValue(loaded([phone, oldPhone, thisBrowser, otherBrowser]));
});

describe("SignedInSection", () => {
  it("shows the app and a device that is not signed in, then the browsers", () => {
    renderWithProviders(<SignedInSection />);

    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
    expect(screen.getByText("Firefox on Windows")).toBeInTheDocument();
    expect(screen.getByText("Lee's iPhone")).toBeInTheDocument();
    expect(within(row("Android")).getByText(/not signed in/)).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)
    ).toEqual(["Devices", "Browsers"]);
  });

  it("marks the session doing the reading and offers it no way out", () => {
    // Signing the current session out is what the sign-out button is for; a
    // row that did it here would be a second, stranger way to do the same.
    renderWithProviders(<SignedInSection />);

    const current = row("Chrome on macOS");
    expect(within(current).getByText("This browser")).toBeInTheDocument();
    expect(within(current).queryByRole("button")).toBeNull();

    // Every other row keeps one: a browser is signed out, a device removed.
    expect(screen.getAllByRole("button", { name: "Sign out" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Remove device" })).toHaveLength(2);
  });

  it("puts the current session first in its group, then the most recently active", () => {
    renderWithProviders(<SignedInSection />);

    const labels = screen
      .getAllByText(/Chrome on macOS|Firefox on Windows|Lee's iPhone|Android/)
      .map((node) => node.textContent?.replace("This browser", "").trim());
    expect(labels).toEqual(["Lee's iPhone", "Android", "Chrome on macOS", "Firefox on Windows"]);
  });

  it("signs a browser out and removes a device, each by its own row", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignedInSection />);

    await user.click(within(row("Firefox on Windows")).getByRole("button", { name: "Sign out" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Sign out" })
    );
    expect(mocks.endSignedIn).toHaveBeenCalledWith(otherBrowser);

    await user.click(within(row("Lee's iPhone")).getByRole("button", { name: "Remove device" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Remove this device?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Remove device" }));
    expect(mocks.endSignedIn).toHaveBeenCalledWith(phone);
  });

  it("offers the sweep only when there is somewhere else to sweep", () => {
    mocks.sessions.mockReturnValue(loaded([thisBrowser]));
    renderWithProviders(<SignedInSection />);

    expect(screen.queryByRole("button", { name: /everywhere else/i })).toBeNull();
  });

  it("sweeps everywhere else on confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignedInSection />);

    await user.click(screen.getByRole("button", { name: "Sign out everywhere else" }));
    // The dialog names how many go.
    expect(screen.getByText(/ends all 2 other sessions/i)).toBeInTheDocument();

    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Sign out everywhere else" }));
    expect(mocks.revokeOthers).toHaveBeenCalled();
  });

  it("says so when the account is signed in nowhere else", () => {
    mocks.sessions.mockReturnValue(loaded([]));
    renderWithProviders(<SignedInSection />);

    expect(screen.getByText("Nowhere else")).toBeInTheDocument();
  });
});
