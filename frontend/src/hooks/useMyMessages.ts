/**
 * My Messages, as React sees it.
 *
 * The ratchet has to advance in a defined order, so the work itself lives in
 * `@/crypto/messaging` and this file only schedules it. Two things are worth
 * knowing about the shape:
 *
 * * **The local log is the source of truth for a thread.** The server deletes a
 *   message the moment it is collected, so React Query caches what this device
 *   decrypted, not what an endpoint would return.
 * * **Collection is triggered by the socket, not a poll.** A `dm` frame carries
 *   nothing; it says there is something to fetch.
 */

import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import {
  acceptInvitation,
  checkRoster,
  createConversation,
  createGroupConversation as createGroup,
  leaveConversation,
  listConversations,
  markConversationRead as reportThreadRead,
} from "@/api/generated/direct-messages/direct-messages";
import { invalidate, q } from "@/api/query-keys";
import type { PeerKeyChange, StoredMessage } from "@/crypto/messaging";
import {
  answerNewDevice,
  cancelVerification,
  collect,
  collectVerification,
  confirmMatch,
  DeviceGoneError,
  dismissVerification,
  ensureDevice,
  historyAsk,
  historyAskWaiting,
  markRead,
  messageLog,
  ownDeviceWaiting,
  peerDeviceChanges,
  registeredDevice,
  rejectMatch,
  sendEdit,
  sendReaction,
  sendRemove,
  sendText,
  startVerification,
  subscribeVerification,
  unreadIn,
  verificationView,
  wantThreadHistory,
} from "@/crypto/messaging";
import { useApiMutation } from "@/hooks/useApiMutation";
import {
  useDirectMessagesEnabled,
  useDmSettings,
  usePendingConnectionRequests,
} from "@/hooks/useDirectMessages";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

export const messageKeys = {
  conversations: ["dm", "conversations"] as const,
  // Deliberately outside the `["dm", …]` family a socket frame invalidates:
  // registering is a once-per-browser answer, and re-asking it on every frame
  // would cost a round trip to be told the same device id again.
  device: ["dm-device"] as const,
  // A separate key from `device`, because it is a different question with a
  // different answer: *is* there one, versus make sure there is. Sharing one
  // would let whichever asked first decide what the other one got back.
  registered: ["dm-device-registered"] as const,
  inbox: ["dm", "inbox"] as const,
  thread: (conversationId: string) => ["dm", "thread", conversationId] as const,
  // Keyed on the conversations it counts, so a new one is a new question
  // rather than a stale answer waiting for something to invalidate it.
  unread: (conversationIds: string[]) => ["dm", "unread", conversationIds.join(",")] as const,
  /** When each conversation's newest message on this device was written. */
  latest: (conversationIds: string[]) => ["dm", "latest", conversationIds.join(",")] as const,
  /** A new device of this account's waiting to be confirmed, read out of the local store. */
  ownDevice: ["dm", "own-device"] as const,
  /** This device's own outstanding ask for its history. */
  historyAsk: ["dm", "history-ask"] as const,
  /** When other people's devices changed, noted locally for their conversations. */
  peerDeviceChanges: ["dm", "peer-device-changes"] as const,
  /** This device's verification inbox, which a socket frame asks to be read. */
  verification: ["dm", "verification"] as const,
  /** The family a socket frame invalidates, which is everything read locally. */
  all: ["dm"] as const,
};

/** Register this browser's device, once, before anything else can work. */
export function useDmDevice() {
  const dmEnabled = useDirectMessagesEnabled();
  return useQuery({
    queryKey: messageKeys.device,
    queryFn: async () => {
      try {
        return await ensureDevice();
      } catch (error) {
        // The page can only say that it failed. What failed is worth having
        // when somebody has to work out why.
        console.error("[messages] this device could not be set up", error);
        throw error;
      }
    },
    // A deployment with messaging switched off has nothing to register a
    // device with, and registering one would be this browser publishing keys
    // for a channel that does not exist.
    enabled: dmEnabled,
    staleTime: Number.POSITIVE_INFINITY,
    // Setting up is safe to ask again: a device already registered is found
    // rather than made twice. One failed round trip should not leave the page
    // saying this browser cannot do encrypted messages until it is reloaded.
    retry: 2,
  });
}

export function useConversations() {
  return useQuery({
    queryKey: messageKeys.conversations,
    queryFn: () => listConversations(),
    enabled: useDirectMessagesEnabled(),
    staleTime: 30_000,
  });
}

/** One thread, read out of this device's own store. */
export function useThread(conversationId: string | undefined) {
  return useQuery({
    queryKey: messageKeys.thread(conversationId ?? ""),
    queryFn: (): Promise<StoredMessage[]> =>
      conversationId ? messageLog.get(conversationId) : Promise.resolve([]),
    enabled: Boolean(conversationId),
    staleTime: 0,
  });
}

export function useSendMessage(conversationId: string, memberIds: number[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, replyTo }: { body: string; replyTo?: string }) =>
      sendText(conversationId, memberIds, body, { replyTo }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: messageKeys.thread(conversationId),
      });
      void queryClient.invalidateQueries({ queryKey: ["dm", "latest"] });
    },
    // Settled, not success: reading the directory happens before the send, so
    // a send that fails afterwards can still have found something to say.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.peerDeviceChanges });
    },
  });
}

/**
 * Acting on a message that has already been said.
 *
 * Three writes with one shape: each applies to this device's own log first and
 * tells the other side after, so the thread answers the click rather than the
 * round trip. Refreshing the thread is what puts the answer on screen, since
 * the log is where a thread is read from.
 */
export function useMessageActions(conversationId: string, memberIds: number[]) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: messageKeys.thread(conversationId) });
    void queryClient.invalidateQueries({ queryKey: messageKeys.peerDeviceChanges });
  };

  const react = useMutation({
    mutationFn: ({ targetId, emoji, on }: { targetId: string; emoji: string; on: boolean }) =>
      sendReaction(conversationId, memberIds, targetId, emoji, on),
    onSettled: refresh,
  });
  const edit = useMutation({
    mutationFn: ({ targetId, body }: { targetId: string; body: string }) =>
      sendEdit(conversationId, memberIds, targetId, body),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (targetId: string) => sendRemove(conversationId, memberIds, targetId),
    onSettled: refresh,
  });

  return { react, edit, remove };
}

export function useStartConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => createConversation({ user_id: userId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
    },
  });
}

/**
 * Fetch and decrypt whatever is waiting, then refresh the threads it touched.
 *
 * This is a *query*, not an effect, and that is what makes the socket work: a
 * `dm` frame invalidates everything under `["dm"]`, which includes this key, so
 * the frame re-runs the collection. An effect would have needed its own
 * subscription to the same signal.
 *
 * It never invalidates its own key — only the threads, the conversation list
 * and the notices it can raise — so a collection cannot re-trigger itself.
 */
export function useCollectMessages(enabled: boolean) {
  const queryClient = useQueryClient();
  const dmEnabled = useDirectMessagesEnabled();
  const receipts = useSendsReceipts();

  return useQuery({
    queryKey: messageKeys.inbox,
    queryFn: async () => {
      const touched = await collect({ receipts });
      for (const conversationId of touched) {
        void queryClient.invalidateQueries({
          queryKey: messageKeys.thread(conversationId),
        });
      }
      // Always, and after the collection rather than with it: a new device of
      // this account's is found by the collection's own read of the device
      // list and written to this device's own store, which no frame and no
      // other query knows to look at again. The socket frame that started this
      // collection invalidated the prompt a round trip *before* that, so this
      // is what puts it on screen for somebody who has just signed in
      // elsewhere and is not about to reload.
      void queryClient.invalidateQueries({ queryKey: messageKeys.ownDevice });
      void queryClient.invalidateQueries({ queryKey: messageKeys.historyAsk });
      // Same reason: a directory read during this collection can record a key
      // change locally, and nothing else asks that query again.
      void queryClient.invalidateQueries({ queryKey: messageKeys.peerDeviceChanges });
      if (touched.length > 0) {
        void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
        void queryClient.invalidateQueries({ queryKey: ["dm", "unread"] });
        void queryClient.invalidateQueries({ queryKey: ["dm", "latest"] });
      }
      return touched;
    },
    enabled: enabled && dmEnabled,
    // A collection that fails leaves the queue intact; the next frame or the
    // next visit tries again.
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
}

/**
 * Collect anywhere in the app, but only for a browser already set up.
 *
 * What makes a mark on My Messages mean anything is that the mail is fetched
 * while you are somewhere else — otherwise nothing new is ever noticed until
 * you go and look, which is the one thing the mark is there to save you. It
 * deliberately does *not* register a device: setting one up is what visiting
 * the page does, and a browser that never has stays as it was.
 */
export function useCollectMessagesWhereRegistered() {
  const registered = useQuery({
    queryKey: messageKeys.registered,
    queryFn: () => registeredDevice().then((id) => id ?? null),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  // Watching the answer to the *other* question rather than fetching anything:
  // this browser may be set up while the app is running, by the one page that
  // does it, and collection should start then rather than on the next load.
  const device = useQuery({ queryKey: messageKeys.device, queryFn: skipToken });
  const enabled = Boolean(registered.data ?? device.data);
  useCollectVerification(enabled);
  return useCollectMessages(enabled);
}

/** The comparison this tab is running or showing, as the verification dialog draws it. */
export function useVerification() {
  return useSyncExternalStore(subscribeVerification, verificationView);
}

/**
 * Read this device's verification inbox whenever a socket frame says there is
 * something, and every couple of seconds while a comparison is running, since
 * the other device is waiting on each step.
 */
function useCollectVerification(enabled: boolean) {
  const dmEnabled = useDirectMessagesEnabled();
  const queryClient = useQueryClient();
  const { phase } = useVerification();
  const running = phase === "waiting" || phase === "compare";
  // A comparison that ends verified released a device from this browser's own
  // store, which only these queries read: the prompt about it, the notice on
  // the device that was verified, and the collection that was leaving its
  // messages waiting.
  useEffect(() => {
    if (phase !== "verified") return;
    void queryClient.invalidateQueries({ queryKey: messageKeys.ownDevice });
    void queryClient.invalidateQueries({ queryKey: messageKeys.historyAsk });
    void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
  }, [phase, queryClient]);
  return useQuery({
    queryKey: messageKeys.verification,
    queryFn: () => collectVerification().then(() => null),
    enabled: enabled && dmEnabled,
    refetchInterval: running ? 2_000 : false,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
}

/** What the prompt and the dialog can do about a comparison. */
export function useVerificationActions() {
  const { t } = useTranslation("messages");
  const queryClient = useQueryClient();
  const onError = (error: unknown) =>
    toast.error(getErrorMessage(error, "messages:verification.error"));
  return {
    start: useMutation({
      mutationFn: ({ change, sendHistory }: { change: PeerKeyChange; sendHistory: boolean }) =>
        startVerification(change, { sendHistory }),
      onError: (error) => {
        if (!(error instanceof DeviceGoneError)) return onError(error);
        // Its prompt is already gone from the store; this takes it off screen.
        toast.info(t("newDevice.gone"));
        void queryClient.invalidateQueries({ queryKey: messageKeys.ownDevice });
      },
    }),
    confirm: useApiMutation({ mutationFn: confirmMatch, errorKey: "messages:verification.error" }),
    reject: useApiMutation({ mutationFn: rejectMatch, errorKey: "messages:verification.error" }),
    cancel: useMutation({ mutationFn: cancelVerification }),
    dismiss: dismissVerification,
  };
}

/**
 * How many things are waiting in My Messages, as one number.
 *
 * Two kinds, and they mean the same thing to the person seeing the mark:
 * something is there that you have not dealt with. Counted in one place because
 * more than one surface draws it -- the sidebar item, and the logo above the
 * whole rail, which is the only mark visible from inside a community.
 */
/**
 * A device of this account's that signed in after this browser, waiting to be
 * confirmed. Read from this device's own store; keyed under `["dm", …]`, so a
 * collection refreshes it.
 */
export function useOwnDeviceWaiting() {
  return useQuery({
    queryKey: messageKeys.ownDevice,
    queryFn: () => ownDeviceWaiting(),
    staleTime: 0,
  });
}

/**
 * Answer the prompt about a new device. Everything under `["dm"]` is refreshed,
 * which collects again: what the device sent here was waiting on this answer.
 */
export function useAnswerNewDevice() {
  const queryClient = useQueryClient();
  return useApiMutation({
    mutationFn: ({
      change,
      mine,
      sendHistory,
    }: {
      change: PeerKeyChange;
      mine: boolean;
      sendHistory: boolean;
    }) => answerNewDevice(change, { mine, sendHistory }),
    invalidate: () => queryClient.invalidateQueries({ queryKey: messageKeys.all }),
    errorKey: "messages:newDevice.error",
  });
}

/**
 * This device waiting to be verified by another of this account's and sent
 * its history.
 */
export function useHistoryAsk() {
  return useQuery({
    queryKey: messageKeys.historyAsk,
    queryFn: () => historyAskWaiting().then((ask) => ask ?? null),
    staleTime: 0,
    // The notice gives up after a day, and a tab left open is exactly where
    // that day runs out with nothing else happening to notice it. Asked once,
    // when it is due, rather than polled: the answer cannot change before then.
    refetchInterval: (query) =>
      query.state.data ? Math.max(1_000, query.state.data.expiresAt - Date.now()) : false,
  });
}

/** When other people's devices changed, by user id, for their conversations to say so. */
export function usePeerDeviceChanges() {
  return useQuery({
    queryKey: messageKeys.peerDeviceChanges,
    queryFn: () => peerDeviceChanges.all(),
    staleTime: 0,
  });
}

/**
 * Put the waiting notice away without answering the question.
 *
 * The ask stays outstanding — this is the banner going quiet, not the transfer
 * being called off — so a history approved later still arrives and still lands.
 */
export function useDismissHistoryAsk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => historyAsk.dismissNotice(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.historyAsk });
    },
  });
}

export function useMessagesWaiting(): number {
  const pending = usePendingConnectionRequests();
  const conversations = useConversations();
  const unread = useUnreadMessages((conversations.data?.conversations ?? []).map((row) => row.id));
  const unreadTotal = [...(unread.data?.values() ?? [])].reduce((total, count) => total + count, 0);
  return pending + unreadTotal;
}

/**
 * How many messages are waiting in each conversation, on this device.
 *
 * Read from the local log, because that is where a thread is — the server
 * deletes a message once it has been collected and could not answer this even
 * if it were asked.
 */
/**
 * When the newest message in each conversation was written, on this device, by
 * the sender's clock: what the conversation list is ordered by. Absent for a
 * thread this device holds nothing of.
 */
export function useLatestMessages(conversationIds: string[]) {
  return useQuery({
    queryKey: messageKeys.latest(conversationIds),
    queryFn: async () => {
      const latest = new Map<string, string>();
      for (const id of conversationIds) {
        const log = await messageLog.get(id);
        if (log.length > 0) latest.set(id, log[log.length - 1].at);
      }
      return latest;
    },
    enabled: conversationIds.length > 0,
    staleTime: 0,
  });
}

export function useUnreadMessages(conversationIds: string[]) {
  return useQuery({
    queryKey: messageKeys.unread(conversationIds),
    queryFn: async () => {
      const counts = new Map<string, number>();
      for (const id of conversationIds) {
        counts.set(id, await unreadIn(id));
      }
      return counts;
    },
    enabled: conversationIds.length > 0,
    staleTime: 0,
  });
}

/**
 * Mark a thread as looked at, whenever what is in it changes.
 *
 * Two readers to satisfy, and only one of them is here. The local marker is
 * what the conversation list counts from, and the server's rolled-up bell line
 * is a separate thing that only the account holder's own client can close —
 * nothing else knows a message reached a screen. So the look is reported
 * onwards, but only where it read something: an already-current thread has
 * nothing to tell anybody.
 *
 * The report is best-effort — it affects a bell line, and a thread should not
 * surface an error because one did not clear — but it is not fire-and-forget.
 * The local marker has already advanced by the time it is sent, so a dropped
 * request would leave a count nothing ever says again. A failure is remembered
 * against its conversation and retried the next time the effect runs, which is
 * the next message or the next time the thread is opened.
 */
export function useMarkThreadRead(
  conversationId: string,
  messageCount: number,
  memberIds: number[]
) {
  const queryClient = useQueryClient();
  const receipts = useSendsReceipts();
  const unreported = useRef<string | null>(null);
  // The roster by its contents, not by the array it arrived in. A caller that
  // builds one inline hands a new array every render, and this effect reads the
  // local log and invalidates the unread queries -- work that belongs to the
  // thread changing, not to the page re-rendering.
  const roster = memberIds.join(",");
  useEffect(() => {
    // Rebuilt from the key rather than closed over, so the effect depends on
    // the roster by value and nothing else.
    const members = roster ? roster.split(",").map(Number) : [];
    void markRead(conversationId, { memberIds: members, receipts })
      .then(async (readCount) => {
        if (readCount === 0 && unreported.current !== conversationId) return;
        try {
          await reportThreadRead(conversationId);
          if (unreported.current === conversationId) unreported.current = null;
          await invalidate(q.notifications());
        } catch {
          unreported.current = conversationId;
        }
      })
      .finally(() => queryClient.invalidateQueries({ queryKey: ["dm", "unread"] }));
  }, [conversationId, messageCount, roster, receipts, queryClient]);
}

/**
 * Whether this account tells a sender their message arrived and was read.
 *
 * Read where the receipts are sent rather than passed down from a page: the
 * collection loop runs whether or not anything is on screen, and the switch has
 * to reach it there too.
 *
 * Quiet until the answer is actually in. Assuming the friendlier default while
 * the setting is on its way would report on behalf of somebody who had turned
 * reporting off, on every load, and nothing can take that back. A receipt that
 * was never sent costs a tick.
 */
export function useSendsReceipts(): boolean {
  const { data, isSuccess } = useDmSettings();
  return isSuccess && (data?.send_receipts ?? true);
}

/**
 * Answering an invitation to a group.
 *
 * Yes and no are different writes but one decision, so they live together: a
 * decline is the ordinary leave, because being asked and refusing and being on
 * it and leaving both come to "not on it" — and both are answered by being
 * asked again if anybody proposes that roster.
 */
export function useAnswerInvitation(conversationId: string) {
  const queryClient = useQueryClient();
  const settle = () => {
    void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
  };
  // An invitation goes stale -- somebody proposes the roster again, or it is
  // answered on another device -- so both of these can be refused, and a button
  // that quietly becomes pressable again reads as having been ignored.
  const accept = useApiMutation({
    mutationFn: () => acceptInvitation(conversationId),
    invalidate: () => {
      // Nothing was kept for somebody who had not answered, so the thread up
      // to this moment has to be asked for. Recorded here and sent by the next
      // collection, which is also what retries it.
      void wantThreadHistory(conversationId);
      settle();
    },
    errorKey: "errors:DM_NO_INVITATION",
  });
  const decline = useApiMutation({
    mutationFn: () => leaveConversation(conversationId),
    invalidate: settle,
    errorKey: "errors:DM_CONVERSATION_NOT_FOUND",
  });
  return { accept, decline };
}

/**
 * Whether these people could be a group, asked while somebody is still
 * choosing them.
 *
 * The proposal enforces the same rule; this is the question, so the answer
 * arrives when a name can still be dropped rather than as a refusal after the
 * roster is submitted. Quiet below three, which is a pair and has its own way
 * in.
 */
export function useRosterCheck(userIds: number[]) {
  const roster = [...userIds].sort((a, b) => a - b);
  return useQuery({
    queryKey: ["dm", "roster-check", roster],
    queryFn: () => checkRoster({ user_ids: roster }),
    enabled: roster.length >= 2,
    staleTime: 0,
  });
}

/** Propose a roster. Everybody on it is asked; nobody is added. */
export function useStartGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userIds: number[]) => createGroup({ user_ids: userIds }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
    },
  });
}
