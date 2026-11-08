/**
 * My Messages, through the router the app ships.
 *
 * The page is only useful if it is reachable: the generated route tree has to
 * serve `/messages` — outside the community tree, because a direct message is
 * not a community's business — and load the page from its own chunk. A test
 * that mounts the component directly proves neither.
 *
 * The crypto itself is proved in `src/crypto/ratchet.test.ts`, against the real
 * ratchet. What is worth proving here is what the page does with it: that a
 * thread renders from this device's own store rather than from an endpoint,
 * and that sending goes through the ratchet rather than posting a body.
 * Registering this browser's device before anything is collected is the
 * hook's, proved in `src/hooks/useMyMessages.test.tsx`.
 */
import { createRouter } from "@tanstack/react-router";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DeviceGoneError, RecipientHasNoDeviceError } from "@/crypto/messaging";
import { toast } from "@/lib/mascotToast";
import { routeTree } from "@/routeTree.gen";

import { layOutVirtualList } from "./helpers/layOutVirtualList";
import { buildRouterContext, renderPage } from "./helpers/render";

const MESSAGES_ROUTE_ID = "/_serverRequired/_authenticated/messages";

/** A device's keys, real enough to draw its code from. */
const KEYS = {
  fingerprint: "C35J1oMcLovDN1JgJEHVuok+7W313W52YY6oaGnw2m8=",
  identityKey: "zuFDxA+kaChnPNa1QI59q0xuKG+kAI21A/AGDod1RPM=",
};

const mocks = vi.hoisted(() => ({
  ensureDevice: vi.fn(),
  registeredDevice: vi.fn(),
  collect: vi.fn(),
  sendText: vi.fn(),
  sendReaction: vi.fn(),
  sendEdit: vi.fn(),
  sendRemove: vi.fn(),
  logGet: vi.fn(),
  unreadIn: vi.fn(),
  markRead: vi.fn(),
  conversations: vi.fn(),
  createConversation: vi.fn(),
  acceptInvitation: vi.fn(),
  leaveConversation: vi.fn(),
  messageRequests: vi.fn(),
  dmPermission: vi.fn(),
  requestMessage: vi.fn(),
  acceptMessageRequest: vi.fn(),
  removeMessageRequest: vi.fn(),
  userProfile: vi.fn(),
  dmSettings: vi.fn(),
  ownDevice: vi.fn(),
  historyAsk: vi.fn(),
  startVerification: vi.fn(),
  peerDeviceChanges: vi.fn(),
}));

// The ratchet is exercised for real in src/crypto/ratchet.test.ts. Here it is
// the seam the page talks to, so the page's own behaviour is what is on trial.
vi.mock("@/crypto/messaging", async (importOriginal) => ({
  // The error classes are real: the page tells one kind of failure from another
  // by identity, so a stand-in would prove nothing.
  RecipientHasNoDeviceError: (await importOriginal<Record<string, unknown>>())
    .RecipientHasNoDeviceError,
  DeviceGoneError: (await importOriginal<Record<string, unknown>>()).DeviceGoneError,
  ensureDevice: () => mocks.ensureDevice(),
  registeredDevice: () => mocks.registeredDevice(),
  collect: () => mocks.collect(),
  sendText: (
    conversationId: string,
    otherUserId: number,
    body: string,
    options?: { replyTo?: string }
  ) => mocks.sendText(conversationId, otherUserId, body, options),
  sendReaction: (
    conversationId: string,
    otherUserId: number,
    targetId: string,
    emoji: string,
    on: boolean
  ) => mocks.sendReaction(conversationId, otherUserId, targetId, emoji, on),
  sendEdit: (conversationId: string, otherUserId: number, targetId: string, body: string) =>
    mocks.sendEdit(conversationId, otherUserId, targetId, body),
  sendRemove: (conversationId: string, otherUserId: number, targetId: string) =>
    mocks.sendRemove(conversationId, otherUserId, targetId),
  messageLog: { get: (id: string) => mocks.logGet(id) },
  // Which threads are unread, and saying one has been looked at, both read the
  // same local log the thread does.
  unreadIn: (id: string) => mocks.unreadIn(id),
  markRead: (id: string) => mocks.markRead(id),
  // Both sides of confirming a new device read this device's own store, not
  // an endpoint.
  ownDeviceWaiting: () => mocks.ownDevice(),
  historyAskWaiting: () => mocks.historyAsk(),
  startVerification: (change: unknown, options: unknown) =>
    mocks.startVerification(change, options),
  confirmMatch: vi.fn(),
  rejectMatch: vi.fn(),
  cancelVerification: vi.fn(),
  dismissVerification: vi.fn(),
  peerDeviceChanges: { all: () => mocks.peerDeviceChanges() },
}));

// The mascot types its toasts out over time, so what a toast says is read from
// the call rather than the screen.
vi.mock("@/lib/mascotToast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/api/generated/direct-messages/direct-messages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listConversations: () => mocks.conversations(),
  createConversation: (body: { user_id: number }) => mocks.createConversation(body),
  acceptInvitation: (id: string) => mocks.acceptInvitation(id),
  leaveConversation: (id: string) => mocks.leaveConversation(id),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
  useDmSettings: () => mocks.dmSettings(),
  useCanUseDirectMessages: () => mocks.dmSettings().data?.age_answer_required === false,
  useDmPermission: () => mocks.dmPermission(),
  useRequestMessage: () => ({ mutate: mocks.requestMessage, isPending: false }),
  useAcceptMessageRequest: () => ({ mutate: mocks.acceptMessageRequest, isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: mocks.removeMessageRequest, isPending: false }),
}));

// The page resolves `?with=` to a person before it can decide anything about
// them, so the profile is the seam that decides which pane is on trial.
vi.mock("@/hooks/useUsers", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useUserProfile: (handle: string | null | undefined) => mocks.userProfile(handle),
}));

const router = createRouter({ routeTree, context: buildRouterContext() });

// The page refuses outright where there are no web workers, because the ratchet
// cannot run there. jsdom has none, so one stands in — nothing here calls it,
// since the crypto seam is mocked below.
const noWorker = globalThis.Worker === undefined;
beforeAll(() => {
  if (noWorker) globalThis.Worker = class {} as unknown as typeof Worker;
});
afterAll(() => {
  if (noWorker) Reflect.deleteProperty(globalThis, "Worker");
});
// The thread's log, a phone's height.
layOutVirtualList((element) => element.classList.contains("overscroll-contain"), {
  height: 800,
  rowHeight: 48,
});

const grant = (userId: number, username: string) => ({
  user_id: userId,
  username,
  discriminator: 1234,
  avatar_url: null,
  status: "active" as const,
  presence: "offline" as const,
  state: "accepted",
  outgoing: false,
  created_at: "2026-09-01T00:00:00Z",
  responded_at: "2026-09-01T00:00:00Z",
});

const messagesPage = async () => {
  const route = router.routesById[MESSAGES_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderMessages = async (routerSearch?: Record<string, unknown>) => {
  const Page = await messagesPage();
  return renderPage(Page, { initialRoute: "/messages", routerSearch });
};

/** Open the page on somebody, the way the sidebar addresses them. */
const renderMessagesWith = async (userId: number, username: string) => {
  mocks.userProfile.mockReturnValue(profile(userId, username));
  return renderMessages({ with: `${username}1234` });
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.ensureDevice.mockResolvedValue("device-1");
  mocks.registeredDevice.mockResolvedValue("device-1");
  mocks.unreadIn.mockResolvedValue(0);
  mocks.markRead.mockResolvedValue(undefined);
  mocks.collect.mockResolvedValue([]);
  mocks.sendText.mockResolvedValue({ id: "1", body: "hi", at: "", mine: true });
  mocks.sendReaction.mockResolvedValue(true);
  mocks.sendEdit.mockResolvedValue(true);
  mocks.sendRemove.mockResolvedValue(true);
  mocks.logGet.mockResolvedValue([]);
  mocks.conversations.mockResolvedValue({ conversations: [] });
  mocks.createConversation.mockResolvedValue({
    id: "conv-new",
    other_user_id: 0,
    created_at: "2026-09-01T00:00:00Z",
  });
  mocks.messageRequests.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.dmPermission.mockReturnValue({ data: { permission: "denied" } });
  mocks.userProfile.mockReturnValue({ data: undefined, isLoading: false });
  mocks.dmSettings.mockReturnValue({
    data: {
      dm_policy: "community",
      communities: [],
      age_confirmed_at: "2020-01-01T00:00:00Z",
      age_answer_required: false,
    },
    isSuccess: true,
  });
  mocks.acceptInvitation.mockResolvedValue(undefined);
  mocks.leaveConversation.mockResolvedValue(undefined);
  mocks.ownDevice.mockResolvedValue(null);
  mocks.historyAsk.mockResolvedValue(undefined);
  mocks.startVerification.mockResolvedValue(undefined);
  mocks.peerDeviceChanges.mockResolvedValue({});
});

/** The person a `?with=` handle resolves to. */
const profile = (userId: number, username: string) => ({
  data: {
    id: userId,
    username,
    discriminator: 1234,
    avatar_url: null,
    status: "active" as const,
    custom_status: {},
    profile_decorations: {},
    presence: "offline" as const,
    joined_at: "2026-01-01T00:00:00Z",
  },
  isLoading: false,
});

/** The pair every thread here is on, as the server lists it. */
const conversation = {
  id: "conv-1",
  other_user_id: 7,
  member_ids: [7],
  created_at: "2026-09-01T00:00:00Z",
};

describe("My Messages", () => {
  it("is reachable at /messages", async () => {
    await renderMessages();

    expect(
      await screen.findByRole("heading", { name: /pick a conversation/i })
    ).toBeInTheDocument();
  });

  it("lands on the list rather than a note about where the list is", async () => {
    // On a phone the sidebar shuts on the way here, so the page has to be able
    // to offer the conversations itself or there is no way to pick one without
    // opening the menu again.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });

    await renderMessages();

    expect((await screen.findByTitle("alex#1234")).closest("a")).toHaveAttribute(
      "href",
      "/messages?with=alex1234"
    );
  });

  it("says so when there is nobody to talk to at all", async () => {
    await renderMessages();

    expect(await screen.findByText(/nobody yet/i)).toBeInTheDocument();
  });

  it("renders a thread out of this device's own store", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "only this device has this", at: "", mine: false },
    ]);

    await renderMessagesWith(7, "alex");

    expect(await screen.findByText("only this device has this")).toBeInTheDocument();
    expect(mocks.logGet).toHaveBeenCalledWith("conv-1");
  });

  it("times the start of a run rather than every message in it", async () => {
    // A run is one person speaking once, so it wears one time: the moment they
    // began. Same sender is not enough to make a run — two messages an hour
    // apart are two occasions, and the second must not wear the first's time.
    const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "one", at: at(60), mine: false },
      { id: "m2", body: "two", at: at(59), mine: false },
      { id: "m3", body: "much later", at: at(3), mine: false },
    ]);

    await renderMessagesWith(7, "alex");
    await screen.findByText("much later");

    // Three messages, two runs, two times. The picture's own slot holds the
    // column open on the rows between, so nothing steps sideways and no gap
    // opens up either.
    const clock = /^\d{1,2}[:.]\d{2}(\s?[AP]M)?$/i;
    const times = screen
      .getAllByTitle(/2026|,/)
      .filter((slot) => clock.test(slot.textContent ?? ""));
    expect(times).toHaveLength(2);
  });

  it("heads each day the thread has messages on", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    const now = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    mocks.logGet.mockResolvedValue([
      { id: "m0", body: "long ago", at: "2026-07-22T09:00:00Z", mine: false },
      { id: "m1", body: "then", at: yesterday.toISOString(), mine: false },
      { id: "m2", body: "now", at: now.toISOString(), mine: false },
    ]);

    await renderMessagesWith(7, "alex");
    await screen.findByText("now");

    // The two days somebody is most likely reading are named, not dated.
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
    expect(screen.getByText(/Jul 22, 2026/)).toBeInTheDocument();
  });

  it("says how far one of your own messages got", async () => {
    // A tick apiece: delivered means a device of theirs holds it, read means
    // somebody looked, and nothing back yet draws neither.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "waiting", at: "2026-09-01T00:00:00Z", mine: true },
      { id: "m2", body: "landed", at: "2026-09-01T01:00:00Z", mine: true, receipt: "delivered" },
      { id: "m3", body: "seen", at: "2026-09-01T02:00:00Z", mine: true, receipt: "read" },
    ]);

    await renderMessagesWith(7, "alex");
    await screen.findByText("seen");

    // Each is its own run — an hour apart — so each wears its own state.
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
  });

  it("answers one message with another, and says which", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "monday?", at: "2026-09-01T00:00:00Z", mine: false },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("monday?");

    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    await userEvent.type(screen.getByRole("textbox", { name: /write a message/i }), "yes");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(mocks.sendText).toHaveBeenCalledWith("conv-1", [7], "yes", { replyTo: "m1" });
  });

  it("quotes who it is answering, and goes back to them when picked", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    // Far enough back that the message answered is out of the window.
    const between = Array.from({ length: 30 }, (_, index) => ({
      id: `between-${index}`,
      body: `between ${index}`,
      at: `2026-09-01T00:${String(index + 1).padStart(2, "0")}:00Z`,
      mine: false,
    }));
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "are you coming monday", at: "2026-09-01T00:00:00Z", mine: false },
      ...between,
      {
        id: "m2",
        body: "yes",
        at: "2026-09-01T01:00:00Z",
        mine: true,
        replyTo: "m1",
      },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("yes");
    expect(screen.queryByText("between 0")).not.toBeInTheDocument();

    // The quote names its speaker, so a thread reads without opening it.
    const quote = screen.getByRole("button", { name: /are you coming monday/ });
    expect(quote).toHaveTextContent("alex#1234");

    await userEvent.click(quote);

    expect(await screen.findByText("between 0")).toBeInTheDocument();
    // The answer is out of the window now, and still holds the focus, so the
    // next Tab goes on from it.
    expect(quote).toHaveFocus();
  });

  it("keeps the actions in the focus order at every width", async () => {
    // `display: none` would take them out of it, and the bubble that summons
    // them on a touch screen is not focusable -- so hiding them that way
    // leaves a keyboard no way to reply, edit or remove anything.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "mine", at: "2026-09-01T00:00:00Z", mine: true },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("mine");

    const reply = screen.getByRole("button", { name: "Reply" });
    // Faded and inert until wanted, never absent: nothing on the way up to it
    // may be `hidden`, or focus cannot land on it.
    for (
      let node: HTMLElement | null = reply;
      node && node !== document.body;
      node = node.parentElement
    ) {
      // `hidden`, plain or behind variants (`max-sm:hidden`); a class that
      // hides something inside it (`[&>svg]:hidden`) leaves it reachable.
      expect(node.className).not.toMatch(/(^|\s)([\w/-]+:)*hidden(\s|$)/);
    }
    reply.focus();
    expect(reply).toHaveFocus();
  });

  it("offers rewriting and taking back only your own messages", async () => {
    // The log refuses anything else, so offering it would be a button that
    // does nothing -- and the reason is not the interface's to invent.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "theirs", at: "2026-09-01T00:00:00Z", mine: false },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("theirs");

    expect(screen.getByRole("button", { name: "Reply" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("rewrites one of your own in the composer, not in the bubble", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "mondat", at: "2026-09-01T00:00:00Z", mine: true },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("mondat");

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const field = screen.getByRole("textbox", { name: /write a message/i });
    // The words to change arrive in the field, rather than being retyped.
    expect(field).toHaveValue("mondat");
    await userEvent.clear(field);
    await userEvent.type(field, "monday");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(mocks.sendEdit).toHaveBeenCalledWith("conv-1", [7], "m1", "monday");
    expect(mocks.sendText).not.toHaveBeenCalled();
  });

  it("gives the words back when a correction did not happen", async () => {
    // Another tab removed the message while this one was still showing it, so
    // the edit resolves `false` rather than throwing. Losing the correction
    // either way is the same loss to whoever typed it.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "mondat", at: "2026-09-01T00:00:00Z", mine: true },
    ]);
    mocks.sendEdit.mockResolvedValue(false);
    await renderMessagesWith(7, "alex");
    await screen.findByText("mondat");

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const field = screen.getByRole("textbox", { name: /write a message/i });
    await userEvent.clear(field);
    await userEvent.type(field, "monday");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(field).toHaveValue("monday"));
  });

  it("takes one back only once it has been confirmed", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "oops", at: "2026-09-01T00:00:00Z", mine: true },
    ]);
    await renderMessagesWith(7, "alex");
    await screen.findByText("oops");

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(mocks.sendRemove).not.toHaveBeenCalled();

    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Remove" })
    );

    expect(mocks.sendRemove).toHaveBeenCalledWith("conv-1", [7], "m1");
  });

  it("leaves a line where a removed message was, and nothing to do about it", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      {
        id: "m1",
        body: "",
        at: "2026-09-01T00:00:00Z",
        mine: false,
        removedAt: "2026-09-01T01:00:00Z",
      },
    ]);
    await renderMessagesWith(7, "alex");

    // The thread keeps its shape: a gap would leave whatever answered it
    // reading as an answer to nothing.
    expect(await screen.findByText("Message removed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reply" })).toBeNull();
  });

  it("turns a reaction off by pressing the one already there", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      {
        id: "m1",
        body: "monday?",
        at: "2026-09-01T00:00:00Z",
        mine: false,
        reactions: { "👍": { mine: true, theirs: false } },
      },
    ]);
    await renderMessagesWith(7, "alex");

    await userEvent.click(await screen.findByRole("button", { name: /👍, 1/ }));

    expect(mocks.sendReaction).toHaveBeenCalledWith("conv-1", [7], "m1", "👍", false);
  });

  it("collects again when a dm frame invalidates the mailbox", async () => {
    // A content-free frame is the only thing that says a message arrived, so
    // the collection has to be something invalidation can re-run.
    const { queryClient } = await renderMessages();
    await waitFor(() => expect(mocks.collect).toHaveBeenCalledTimes(1));

    // What the `dm` frame does: invalidate everything under ["dm"].
    await queryClient.invalidateQueries({ queryKey: ["dm"] });

    await waitFor(() => expect(mocks.collect).toHaveBeenCalledTimes(2));
  });

  it("puts a new device of the account on screen as soon as a collection finds it", async () => {
    // The new device is found by the collection's own read of the device list,
    // and the frame that started the collection invalidated the prompt a round
    // trip earlier. Nothing else would look again, so without the collection
    // saying so the prompt waits for a reload -- which is the one thing
    // somebody who has just signed in on another device is not about to do.
    mocks.collect.mockImplementation(async () => {
      await Promise.resolve();
      mocks.ownDevice.mockResolvedValue({
        userId: 1,
        deviceId: "device-2",
        label: "A laptop",
        now: KEYS,
        at: "2026-09-06T00:00:00Z",
        asked: true,
      });
      return [];
    });

    await renderMessages();

    expect(
      await screen.findByRole("heading", { name: /new device signed in/i })
    ).toBeInTheDocument();
    // Verifying starts a comparison, carrying the history the device asked
    // for, which is offered already ticked.
    expect(screen.getByRole("checkbox", { name: /message history/i })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^verify$/i }));
    expect(mocks.startVerification).toHaveBeenCalledWith(
      expect.objectContaining({ deviceId: "device-2" }),
      { sendHistory: true }
    );
  });

  it("takes down the prompt for a device that has left the account", async () => {
    // Signed out, or removed from another device, after it was held here.
    mocks.ownDevice.mockResolvedValue({
      userId: 1,
      deviceId: "device-2",
      label: "A laptop",
      now: KEYS,
      at: "2026-09-06T00:00:00Z",
    });
    mocks.startVerification.mockImplementation(async () => {
      mocks.ownDevice.mockResolvedValue(null);
      throw new DeviceGoneError();
    });

    await renderMessages();
    await userEvent.click(await screen.findByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(expect.stringMatching(/signed out or was removed/i))
    );
    expect(toast.error).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /new device signed in/i })).toBeNull()
    );
  });

  it("offers another go when this device could not be set up", async () => {
    // The hook retries on its own first, so the page waits out its backoff.
    mocks.ensureDevice.mockRejectedValue(new Error("offline"));

    await renderMessages();
    const retry = await screen.findByRole("button", { name: /try again/i }, { timeout: 8_000 });
    expect(screen.getByText(/could not be set up/i)).toBeInTheDocument();
    expect(mocks.ensureDevice).toHaveBeenCalledTimes(3);

    mocks.ensureDevice.mockResolvedValue("device-1");
    await userEvent.click(retry);

    expect(
      await screen.findByRole("heading", { name: /pick a conversation/i })
    ).toBeInTheDocument();
    expect(screen.queryByText(/could not be set up/i)).toBeNull();
  }, 15_000);

  it("tells the waiting device where to verify it, and shows no standing code", async () => {
    mocks.historyAsk.mockResolvedValue({ expiresAt: Date.now() + 60_000 });

    await renderMessages();

    expect(await screen.findByRole("heading", { name: /verify this device/i })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /pictures/i })).toBeNull();
  });

  it("does not carry a half-written message into another conversation", async () => {
    // A composer keeps a draft. If the thread is not remounted per conversation
    // the draft follows the switch, and the next Send addresses somebody else.
    mocks.conversations.mockResolvedValue({
      conversations: [
        conversation,
        { id: "conv-2", other_user_id: 8, created_at: "2026-09-01T00:00:00Z" },
      ],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex"), grant(8, "sam")], incoming: [], outgoing: [] },
    });

    // Switching is a change of address now that the list is the sidebar's, so
    // the draft has to survive -- or rather not survive -- a navigation.
    mocks.userProfile.mockImplementation((handle: string) =>
      handle === "alex1234" ? profile(7, "alex") : profile(8, "sam")
    );
    const { router } = await renderMessages({ with: "alex1234" });
    await userEvent.type(await screen.findByLabelText(/write a message/i), "meant for alex");
    await act(() => router.navigate({ to: "/messages", search: { with: "sam1234" } }));

    expect(await screen.findByLabelText(/write a message/i)).toHaveValue("");
  });

  it("says an account has no device rather than reporting a plain failure", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.sendText.mockRejectedValue(new RecipientHasNoDeviceError());

    await renderMessagesWith(7, "alex");
    await userEvent.type(await screen.findByLabelText(/write a message/i), "hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/has not set up encrypted messages/i)).toBeInTheDocument();
    // And the text comes back, because the composer was the only copy of it.
    expect(screen.getByLabelText(/write a message/i)).toHaveValue("hello");
  });

  it("opens the conversation the address names", async () => {
    // A person row links straight here. Landing on the page is not enough —
    // it has to land on that person's thread.
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.userProfile.mockReturnValue(profile(7, "alex"));
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "already talking", at: "2026-09-01T00:00:00Z", mine: false },
    ]);
    // A change to their devices is said once, where it happened, and asks nothing.
    mocks.peerDeviceChanges.mockResolvedValue({ 7: ["2026-09-02T00:00:00Z"] });

    const Page = await messagesPage();
    renderPage(Page, { initialRoute: "/messages", routerSearch: { with: "alex1234" } });

    expect(await screen.findByText("already talking")).toBeInTheDocument();
    expect(await screen.findByText(/devices changed/i)).toBeInTheDocument();
  });

  it("asks the age question here, instead of a page whose every control refuses", async () => {
    // Unanswered, this account cannot message anybody and nobody can message
    // it. The form is on this page rather than only in Settings, because this
    // is where somebody arrives wanting the thing it gates.
    mocks.dmSettings.mockReturnValue({
      data: {
        dm_policy: "community",
        communities: [],
        age_confirmed_at: null,
        age_answer_required: true,
      },
      isSuccess: true,
    });

    await renderMessages();

    expect(await screen.findByLabelText(/date of birth/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nobody yet/i)).toBeNull();
  });

  it("waits for the settings before deciding the account has answered nothing", async () => {
    mocks.dmSettings.mockReturnValue({ data: undefined, isSuccess: false });

    await renderMessages();

    expect(
      await screen.findByRole("heading", { name: /pick a conversation/i })
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/date of birth/i)).toBeNull();
  });

  it("stops drawing the last thread the moment the address names another", async () => {
    // The address is the selection. Held in state instead, it outlives the URL
    // that set it: while the next person's profile is still arriving there is
    // nobody to match, and the pane would go on showing the conversation you
    // just left under an address that has already moved on.
    mocks.conversations.mockResolvedValue({
      conversations: [
        { id: "conv-a", other_user_id: 1, created_at: "2026-09-01T00:00:00Z" },
        { id: "conv-b", other_user_id: 2, created_at: "2026-09-01T00:00:00Z" },
      ],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(1, "ada"), grant(2, "grace")], incoming: [], outgoing: [] },
    });
    // Only the first one resolves: the second is still on its way, which is
    // the window the stale thread used to show through.
    mocks.userProfile.mockImplementation((handle: string) =>
      handle === "ada1234" ? profile(1, "ada") : { data: undefined, isLoading: true }
    );
    mocks.logGet.mockImplementation((id: string) =>
      Promise.resolve(
        id === "conv-a" ? [{ id: "m1", body: "ada is talking", at: "", mine: false }] : []
      )
    );

    const Page = await messagesPage();
    const { router: pageRouter } = renderPage(Page, {
      initialRoute: "/messages",
      routerSearch: { with: "ada1234" },
    });
    expect(await screen.findByText("ada is talking")).toBeInTheDocument();

    await act(() =>
      pageRouter.navigate({ to: "/messages", search: { with: "grace1234" } as never })
    );

    await waitFor(() => expect(screen.queryByText("ada is talking")).toBeNull());
  });

  it("offers to ask, for somebody there is no channel with", async () => {
    // The common case, because a person listed is somebody you share a
    // community with rather than somebody who agreed to hear from you.
    mocks.userProfile.mockReturnValue(profile(9, "bram"));
    mocks.dmPermission.mockReturnValue({ data: { permission: "may_request" } });

    const Page = await messagesPage();
    renderPage(Page, { initialRoute: "/messages", routerSearch: { with: "bram1234" } });

    await userEvent.click(await screen.findByRole("button", { name: /ask to message/i }));
    expect(mocks.requestMessage).toHaveBeenCalledWith({ data: { user_id: 9 } }, expect.anything());
  });

  it("offers nothing to ask for when the server says no", async () => {
    // Every refusal collapses into one word, so the panel cannot tell them
    // apart and does not pretend to — and connecting belongs to the picker and
    // the actions menu rather than to this page.
    mocks.userProfile.mockReturnValue(profile(9, "bram"));

    const Page = await messagesPage();
    renderPage(Page, { initialRoute: "/messages", routerSearch: { with: "bram1234" } });

    expect(await screen.findByText(/can't message them right now/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect/i })).toBeNull();
  });

  it("offers another go when a conversation could not be opened", async () => {
    // The address does not change when the button is pressed, so nothing would
    // re-run on its own — and a pane stuck on \"Loading…\" is a dead end.
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.userProfile.mockReturnValue(profile(7, "alex"));
    mocks.createConversation.mockRejectedValueOnce(new Error("network"));

    const Page = await messagesPage();
    renderPage(Page, { initialRoute: "/messages", routerSearch: { with: "alex1234" } });

    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    await waitFor(() => expect(mocks.createConversation).toHaveBeenCalledTimes(2));
  });

  it("does not hand the next person the last one's failure", async () => {
    // One mutation, one error state — so a failure has to remember whose it
    // was, or somebody you have never tried to reach arrives at it.
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.userProfile.mockImplementation((handle: string) =>
      handle === "alex1234" ? profile(7, "alex") : profile(9, "bram")
    );
    mocks.dmPermission.mockReturnValue({ data: { permission: "may_request" } });
    mocks.createConversation.mockRejectedValue(new Error("network"));

    const Page = await messagesPage();
    const { router } = renderPage(Page, {
      initialRoute: "/messages",
      routerSearch: { with: "alex1234" },
    });
    expect(await screen.findByRole("button", { name: /try again/i })).toBeVisible();

    // Bram has no channel at all, so nothing was ever tried for him.
    await router.navigate({ to: "/messages", search: { with: "bram1234" } });

    expect(await screen.findByRole("button", { name: /ask to message/i })).toBeVisible();
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("sends through the ratchet rather than posting a body", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [conversation],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });

    await renderMessagesWith(7, "alex");
    await userEvent.type(await screen.findByLabelText(/write a message/i), "hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(mocks.sendText).toHaveBeenCalledWith("conv-1", [7], "hello", { replyTo: undefined })
    );
  });
});

describe("a group thread", () => {
  /** A group as the server answers it: no single other party, a roster. */
  const groupThread = (overrides: Record<string, unknown> = {}) => ({
    id: "conv-g",
    other_user_id: 7,
    created_at: "2026-09-01T00:00:00Z",
    kind: "group",
    member_ids: [7, 9],
    members: [
      { user_id: 7, username: "alex", discriminator: 1234 },
      { user_id: 9, username: "sam", discriminator: 5678 },
    ],
    pending: false,
    ...overrides,
  });

  it("is named by who is on it, not by one of them", async () => {
    mocks.conversations.mockResolvedValue({ conversations: [groupThread()] });

    await renderMessages({ thread: "conv-g" });

    expect(await screen.findByText("alex#1234, sam#5678")).toBeInTheDocument();
  });

  it("draws each message against the face of whoever said it", async () => {
    mocks.conversations.mockResolvedValue({ conversations: [groupThread()] });
    // Nobody here has sent a message request, which is the ordinary case for a
    // group: agreeing to the roster was the whole of the ask. The roster the
    // conversation carries is therefore the only way to draw these people.
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      // A minute apart, so the quiet gap that also breaks a run cannot be what
      // separates them: the only thing between these two is who said them.
      { id: "m1", body: "monday then", at: "2026-09-01T00:00:00Z", mine: false, author: 7 },
      { id: "m2", body: "works for me", at: "2026-09-01T00:01:00Z", mine: false, author: 9 },
    ]);

    await renderMessages({ thread: "conv-g" });
    await screen.findByText("works for me");

    // One face each, from the roster: a group has no single other party, so a
    // message drawn against "them" would be drawn against nobody. Neither has
    // a picture set, so each is drawn as their own initial.
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("S")).toBeInTheDocument();
  });

  it("opens from its id, because it has no handle to be addressed by", async () => {
    mocks.conversations.mockResolvedValue({ conversations: [groupThread()] });

    await renderMessages({ thread: "conv-g" });

    // The composer is there, which is the thread rather than the list.
    expect(await screen.findByText("alex#1234, sam#5678")).toBeInTheDocument();
    expect(mocks.logGet).toHaveBeenCalledWith("conv-g");
  });

  it("offers the roster and an answer while the invitation is unanswered", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [groupThread({ pending: true })],
    });

    await renderMessages({ thread: "conv-g" });

    // The whole roster before the answer: seeing who is on it is what makes
    // accepting consent rather than notification.
    expect(await screen.findByText("alex#1234, sam#5678")).toBeInTheDocument();
    const join = await screen.findByRole("button", { name: "Join" });

    await userEvent.click(join);

    await waitFor(() => expect(mocks.acceptInvitation).toHaveBeenCalledWith("conv-g"));
  });

  it("declines through the ordinary leave", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [groupThread({ pending: true })],
    });

    await renderMessages({ thread: "conv-g" });
    await userEvent.click(await screen.findByRole("button", { name: "No thanks" }));

    await waitFor(() => expect(mocks.leaveConversation).toHaveBeenCalledWith("conv-g"));
  });

  it("does not open a conversation behind a thread named by id", async () => {
    // Both selectors at once: the id is what is on screen, so acting on the
    // handle would open a conversation with somebody under a thread that is
    // not theirs.
    mocks.conversations.mockResolvedValue({ conversations: [groupThread()] });
    mocks.userProfile.mockReturnValue(profile(7, "alex"));
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });

    await renderMessages({ thread: "conv-g", with: "alex1234" });
    await screen.findByText("alex#1234, sam#5678");

    expect(mocks.createConversation).not.toHaveBeenCalled();
  });

  it("is not mistaken for the conversation with its lowest member", async () => {
    // A group's other_user_id is the lowest id on its roster, so a handle
    // lookup must not land on it.
    mocks.conversations.mockResolvedValue({ conversations: [groupThread()] });
    mocks.userProfile.mockReturnValue(profile(7, "alex"));
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.dmPermission.mockReturnValue({ data: { permission: "open" } });

    await renderMessages({ with: "alex1234" });

    // It opened the pair rather than showing the group.
    await waitFor(() => expect(mocks.createConversation).toHaveBeenCalledWith({ user_id: 7 }));
  });

  it("reads nothing into a thread nobody has answered yet", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [groupThread({ pending: true })],
    });

    await renderMessages({ thread: "conv-g" });
    await screen.findByRole("button", { name: "Join" });

    // Nothing is delivered to somebody who has not agreed to be there, so
    // there is no thread to read.
    expect(mocks.logGet).not.toHaveBeenCalledWith("conv-g");
  });
});
