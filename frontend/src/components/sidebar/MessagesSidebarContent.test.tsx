/**
 * The conversations list, in the column the navigation drills out of.
 *
 * What is worth asserting here is what moved: that a row addresses its person
 * rather than holding a selection of its own, that somebody waiting on an
 * answer can be answered without leaving the list, and that the arrow
 * climbs back out. The thread itself is the page's business and is proved
 * there.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/sidebar/sidebar";

const mocks = vi.hoisted(() => ({
  conversations: vi.fn(),
  unread: vi.fn(),
  messageRequests: vi.fn(),
  connections: vi.fn(),
  accept: vi.fn(),
  decline: vi.fn(),
}));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useConversations: () => mocks.conversations(),
  useUnreadMessages: () => mocks.unread(),
  useLatestMessages: () => ({ data: new Map<string, string>() }),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
  useConnections: () => mocks.connections(),
  useAcceptMessageRequest: () => ({ mutate: mocks.accept, isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: mocks.decline, isPending: false }),
}));

import { MessagesSidebarContent } from "./MessagesSidebarContent";

const grant = (userId: number, username: string) => ({
  user_id: userId,
  username,
  discriminator: 1234,
  avatar_url: null,
  status: "active" as const,
  presence: "offline" as const,
  profile_decorations: {},
  state: "accepted",
  outgoing: false,
  created_at: "2026-09-01T00:00:00Z",
  responded_at: "2026-09-01T00:00:00Z",
});

const setup = (onBack = vi.fn()) =>
  renderPage(
    () => (
      <SidebarProvider>
        <MessagesSidebarContent onBack={onBack} />
      </SidebarProvider>
    ),
    { initialRoute: "/messages" }
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.conversations.mockReturnValue({ data: { conversations: [] }, isLoading: false });
  mocks.unread.mockReturnValue({ data: new Map() });
  mocks.messageRequests.mockReturnValue({
    data: { accepted: [], incoming: [], outgoing: [] },
  });
  mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
});

describe("the messages sidebar", () => {
  it("answers somebody waiting without leaving the list", async () => {
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [], incoming: [grant(9, "robin")], outgoing: [] },
    });

    setup();

    await userEvent.click(await screen.findByRole("button", { name: "Accept" }));
    expect(mocks.accept).toHaveBeenCalledWith({ userId: 9 });

    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(mocks.decline).toHaveBeenCalledWith({ userId: 9 });
  });

  it("shows an ask you sent, and offers to withdraw it", async () => {
    // Both directions in one section: the same question either way round, and
    // an ask left off the page looks like one that never happened.
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [], incoming: [], outgoing: [{ ...grant(9, "robin"), outgoing: true }] },
    });

    setup();

    expect(await screen.findByTitle("robin#1234")).toBeInTheDocument();
    // Nothing to accept: it is theirs to answer, not yours.
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mocks.decline).toHaveBeenCalledWith({ userId: 9 });
  });

  it("addresses each person by handle, a fresh channel included, and drops a conversation whose other side it can no longer see", async () => {
    // Ignoring somebody takes the grant with it. The thread this device has
    // already collected stays on it, but a row with no name to show and no
    // handle to address is a person nobody can open.
    mocks.conversations.mockReturnValue({
      data: {
        conversations: [
          { id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" },
          { id: "conv-2", other_user_id: 8, created_at: "2026-09-01T00:00:00Z" },
        ],
      },
      isLoading: false,
    });
    // Sam has a channel nobody has opened yet; a row addresses its person
    // rather than holding a selection of its own.
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex"), grant(9, "sam")], incoming: [], outgoing: [] },
    });

    setup();

    for (const [title, handle] of [
      ["alex#1234", "alex1234"],
      ["sam#1234", "sam1234"],
    ]) {
      expect((await screen.findByTitle(title)).closest("a")).toHaveAttribute(
        "href",
        `/messages?with=${handle}`
      );
    }
    expect(screen.queryByText(/unknown account/i)).toBeNull();
  });

  it("climbs back out to the navigation", async () => {
    const onBack = vi.fn();
    setup(onBack);

    await userEvent.click(await screen.findByRole("button", { name: /back to navigation/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
