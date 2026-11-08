/**
 * The pill a phone navigates by.
 *
 * My Messages is the one destination here that can be waiting on you, so what
 * is worth asserting is that the count reaches somebody who cannot see a badge:
 * an `aria-label` wins over whatever is inside the button, so a number rendered
 * beside the icon is a number only some people get.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/sidebar/sidebar";

const mocks = vi.hoisted(() => ({
  waiting: vi.fn(),
  mobile: vi.fn(),
  notifications: vi.fn(),
  globalCreate: vi.fn(),
}));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessagesWaiting: () => mocks.waiting(),
}));
vi.mock("@/ui/lib/useWidthClass", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/ui/lib/useWidthClass")>()),
  useWidthClass: () => (mocks.mobile() ? "base" : "lg"),
}));
vi.mock("@/hooks/useNotifications", () => ({ useNotifications: () => mocks.notifications() }));
// Whether the create button is drawn at all is a permissions question with its
// own tests; here it is only the thing the messages button sits beside.
vi.mock("@/hooks/useInitiativeAccess", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useGlobalCreateAccess: () => mocks.globalCreate(),
}));

import { BottomNav } from "./BottomNav";

const setup = () =>
  renderPage(
    () => (
      <SidebarProvider>
        <BottomNav />
      </SidebarProvider>
    ),
    { initialRoute: "/" }
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.waiting.mockReturnValue(0);
  mocks.mobile.mockReturnValue(true);
  mocks.notifications.mockReturnValue({ data: { unread_count: 0 } });
  mocks.globalCreate.mockReturnValue({ tool: true, task: true });
});

describe("the bottom bar", () => {
  it("goes to My Messages", async () => {
    const { router } = setup();

    await userEvent.click(await screen.findByRole("button", { name: "My Messages" }));

    expect(router.state.location.pathname).toBe("/messages");
  });

  it("says how much is waiting, in the name rather than only the badge", async () => {
    mocks.waiting.mockReturnValue(3);
    setup();

    expect(
      await screen.findByRole("button", { name: /My Messages, 3 waiting/ })
    ).toBeInTheDocument();
  });

  it("carries no mark when nothing is waiting", async () => {
    setup();

    const messages = await screen.findByRole("button", { name: "My Messages" });
    expect(messages).toHaveTextContent("");
  });

  it("stands beside the create button where the pill is not drawn", async () => {
    // The pill is the phone's navigation. A wide screen does without it, but
    // not without the one destination that can be waiting on you -- so this
    // moves out of the pill rather than disappearing with it.
    mocks.mobile.mockReturnValue(false);
    mocks.waiting.mockReturnValue(2);
    setup();

    const messages = await screen.findByRole("button", { name: /My Messages, 2 waiting/ });
    expect(screen.queryByRole("button", { name: "Open menu" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Home" })).toBeNull();

    // To the left of it: the quieter of the two, so the primary action stays
    // where it has always been.
    const create = screen.getByRole("button", { name: "Create" });
    expect(
      messages.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });
});
