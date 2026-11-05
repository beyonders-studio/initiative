/**
 * The home column, and the one route it drills into.
 *
 * Climbing out of the conversations is a look rather than a move — the thread
 * stays open behind it — so the address cannot be what puts the list back.
 * That makes "picking My Messages again drills back in" a thing only this
 * component can be asked about.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";

const mocks = vi.hoisted(() => ({
  conversations: vi.fn(),
  unread: vi.fn(),
  messageRequests: vi.fn(),
  pending: vi.fn(),
  dmEnabled: vi.fn(),
  hasTickets: vi.fn(),
}));

vi.mock("@/hooks/useTickets", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useHasFiledTickets: () => mocks.hasTickets(),
}));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useConversations: () => mocks.conversations(),
  useUnreadMessages: () => mocks.unread(),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
  usePendingConnectionRequests: () => mocks.pending(),
  useDirectMessagesEnabled: () => mocks.dmEnabled(),
  useAcceptMessageRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { HomeSidebarContent } from "./HomeSidebarContent";

const setup = (initialRoute: string) =>
  renderPage(
    () => (
      <SidebarProvider>
        <HomeSidebarContent />
      </SidebarProvider>
    ),
    { initialRoute }
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.conversations.mockReturnValue({ data: { conversations: [] }, isLoading: false });
  mocks.unread.mockReturnValue({ data: new Map() });
  mocks.messageRequests.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.pending.mockReturnValue(0);
  mocks.dmEnabled.mockReturnValue(true);
  mocks.hasTickets.mockReturnValue(false);
});

describe("the home sidebar", () => {
  it("offers My Tickets only to somebody who has filed one", async () => {
    setup("/");
    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.queryByText("My Tickets")).toBeNull();
  });

  it("leads to the tickets somebody filed", async () => {
    mocks.hasTickets.mockReturnValue(true);
    setup("/");
    const item = await screen.findByRole("link", { name: "My Tickets" });
    expect(item).toHaveAttribute("href", "/my-tickets");
  });

  it("shows the navigation away from My Messages", async () => {
    setup("/");

    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to navigation/i })).toBeNull();
  });

  it("marks My Messages as alpha, and nothing else", async () => {
    // Encrypted messaging is new and moving. The nav item is where somebody
    // is told that before they rely on it.
    setup("/");

    const badges = await screen.findAllByText("ALPHA");
    expect(badges).toHaveLength(1);
    expect(badges[0].closest("a")).toHaveTextContent("My Messages");
  });

  it("drills into the conversations on My Messages", async () => {
    setup("/messages");

    expect(await screen.findByRole("button", { name: /back to navigation/i })).toBeInTheDocument();
    expect(screen.queryByText("Home")).toBeNull();
  });

  it("offers no My Messages where the deployment does not run it", async () => {
    mocks.dmEnabled.mockReturnValue(false);
    setup("/");

    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.queryByText("My Messages")).toBeNull();
  });

  it("does not drill into conversations on the messages route with it off", async () => {
    // Somebody who had the page open, or who arrived by address. The column
    // stays the column rather than becoming a list of conversations that the
    // deployment has nothing to fill.
    mocks.dmEnabled.mockReturnValue(false);
    setup("/messages");

    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to navigation/i })).toBeNull();
  });

  it("drills back in when My Messages is picked again", async () => {
    // The route never changed, so nothing about the address can put the
    // conversations back — only picking the item again says to.
    setup("/messages");

    await userEvent.click(await screen.findByRole("button", { name: /back to navigation/i }));
    expect(await screen.findByText("Home")).toBeInTheDocument();

    await userEvent.click(screen.getByText("My Messages"));

    expect(await screen.findByRole("button", { name: /back to navigation/i })).toBeInTheDocument();
  });
});
