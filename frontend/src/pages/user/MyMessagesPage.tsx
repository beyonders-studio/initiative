import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Check,
  CheckCheck,
  Pencil,
  Reply,
  Send,
  ShieldCheck,
  Trash2,
  UserX,
  X,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { AgeUnansweredPanel } from "@/components/connections/UnreachableEmptyState";
import { ConversationList } from "@/components/messages/ConversationList";
import { HistoryAskNotice } from "@/components/messages/HistoryAskNotice";
import { MessageContent } from "@/components/messages/MessageContent";
import { NewDevicePrompt } from "@/components/messages/NewDevicePrompt";
import { StartWithPerson } from "@/components/messages/StartWithPerson";
import { ReactionPicker } from "@/components/reactions/ReactionPicker";
import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ratchetSupported } from "@/crypto/client";
import { RecipientHasNoDeviceError } from "@/crypto/messaging";
import type { ReceiptState, StoredMessage } from "@/crypto/store";
import { useAuth } from "@/hooks/useAuth";
import {
  useCanUseDirectMessages,
  useDirectMessagesEnabled,
  useDmSettings,
  useMessageRequests,
} from "@/hooks/useDirectMessages";
import {
  useAnswerInvitation,
  useCollectMessages,
  useConversations,
  useDmDevice,
  useMarkThreadRead,
  useMessageActions,
  usePeerDeviceChanges,
  useSendMessage,
  useStartConversation,
  useThread,
} from "@/hooks/useMyMessages";
import { useUserProfile } from "@/hooks/useUsers";
import { groupName, isGroup, roster } from "@/lib/conversationName";
import { formatDateTime, formatDayHeading, localDayKey } from "@/lib/formatDate";
import { dateTimeFormat } from "@/lib/intl";
import { hour12Option } from "@/lib/timeFormat";
import { getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

/**
 * My Messages — the conversations this account has open, read on this device.
 *
 * Two things about this page are unlike every other list in the product:
 *
 * * **The thread comes out of local storage, not an endpoint.** The server
 *   deletes a message once this device has collected it, so what is on screen
 *   is what this device decrypted and wrote down.
 * * **A device that has never been here has no history.** That is what forward
 *   secrecy costs, and the page says so rather than looking broken.
 *
 * It is also the page a person row points at, via `?with=<handle>`. Most of
 * the people it can be opened for have no channel yet — a person listed is
 * somebody you share a community with, not somebody who agreed to hear from
 * you — so the handle is a request to open a conversation, and what comes back
 * may be the offer to ask for one instead.
 */
export function MyMessagesPage() {
  const { t } = useTranslation(["messages", "nav", "common"]);
  const device = useDmDevice();
  const conversations = useConversations();
  const requests = useMessageRequests();
  const startConversation = useStartConversation();
  // Absent, the settings read as an account that has answered nothing, which
  // is the one thing that must never be shown to somebody who has -- so the
  // gate below waits for the answer rather than assuming one.
  const dmSettings = useDmSettings();
  const settingsLoaded = dmSettings.isSuccess;
  const canMessage = useCanUseDirectMessages();
  // The deployment's own switch, read separately from `canMessage`: the two
  // refusals have nothing to do with each other and only one of them is
  // anything the reader can act on.
  const dmEnabled = useDirectMessagesEnabled();

  // Who the URL asked for, resolved to a person. The profile is what a panel
  // for somebody with no channel has to draw, and the id is what everything
  // else here is keyed on.
  const { with: withHandle, thread: withThread } = useSearch({ strict: false }) as {
    with?: string;
    thread?: string;
  };
  const target = useUserProfile(withHandle);

  useCollectMessages(device.isSuccess);

  /** Everyone with an accepted channel, whether or not it has been opened. */
  const reachable = useMemo(() => requests.data?.accepted ?? [], [requests.data?.accepted]);

  /** What to call the other side of a conversation, wherever it is named. */
  const nameOf = (userId: number) => {
    const person = personFor.get(userId);
    return person ? getUserHandle(person) : t("unknownAccount");
  };

  const rows = useMemo(
    () => conversations.data?.conversations ?? [],
    [conversations.data?.conversations]
  );

  /**
   * Everybody this page can name and draw, from both places a person is known.
   *
   * The whole record rather than a name: a person is their picture and what
   * they wear on it as much as their handle.
   *
   * A conversation carries its own roster, which is the only source for
   * somebody a group put you in touch with -- agreeing to a roster is the whole
   * of the ask, so there need be no request between the two of you to look up.
   * An accepted request is laid over it for the people who also sent one.
   */
  const personFor = useMemo(() => {
    const people = new Map<number, Speaker>();
    for (const row of rows) for (const member of roster(row)) people.set(member.user_id, member);
    for (const grant of reachable) people.set(grant.user_id, grant);
    return people;
  }, [rows, reachable]);

  const targetId = target.data?.id;
  const channelOpen = targetId !== undefined && personFor.has(targetId);

  /**
   * The thread on screen, which is whichever one the address names.
   *
   * Derived rather than held. A selection kept in state outlives the address
   * that set it: while the next person's profile is still arriving there is no
   * `targetId` to match, and a remembered id would go on drawing the last
   * conversation under a URL that has already moved on -- the address changes
   * and the pane does not. Read from the URL, an unresolved handle simply has
   * no conversation yet, which is the truth and is what the panel below is for.
   */
  // A thread named by id wins: it is the only way a group can be addressed,
  // and it names a conversation that exists rather than a person one might be
  // opened with. A handle still opens one that does not exist yet, which is
  // what the effect below is for and what an id cannot do.
  const namedThread = withThread ? rows.find((row) => row.id === withThread) : undefined;
  // Pairs only. A group's `other_user_id` is the lowest id on its roster, so a
  // handle would otherwise match a group that happens to contain that person
  // and open it in place of the conversation with them.
  const targetConversation =
    targetId !== undefined
      ? (rows.find((row) => !isGroup(row) && row.other_user_id === targetId) ?? null)
      : null;
  const current = namedThread ?? targetConversation;

  // Acting on the handle in the URL, once per handle: select their thread, or
  // open one where the channel is already there. A conversation is one per
  // pair server-side, so asking for one that exists returns it rather than a
  // second — which is what makes this safe to fire from an effect.
  //
  // Not before the list has arrived, though: until then every conversation
  // looks missing, and opening one that is already there is a round trip to be
  // told what was on its way.
  const opened = useRef<string | null>(null);
  const startMessages = startConversation.mutate;
  const conversationsLoaded = conversations.isSuccess;

  // Whose open failed, not merely that one did: a mutation has one error state
  // and the reader moves on to somebody else, who would otherwise arrive at a
  // failure that was never theirs.
  const [failedFor, setFailedFor] = useState<string | null>(null);

  // Nothing to select on the way out: opening one refreshes the list, and the
  // thread on screen is read from that list against the handle in the address.
  const openWith = useCallback(
    (userId: number, handle: string) =>
      startMessages(userId, {
        onSuccess: () => setFailedFor(null),
        onError: () => setFailedFor(handle),
      }),
    [startMessages]
  );

  useEffect(() => {
    // A named thread is what is on screen, so the handle is not acted on: it
    // would open a conversation with somebody in the background, under a thread
    // that is not theirs.
    if (withThread) return;
    if (!withHandle || targetId === undefined || !conversationsLoaded) return;
    if (opened.current === withHandle) return;
    // Already there: nothing to open, and nothing to select -- the render
    // reads it off the address.
    if (targetConversation) {
      opened.current = withHandle;
      return;
    }
    if (channelOpen) {
      opened.current = withHandle;
      openWith(targetId, withHandle);
    }
  }, [
    withThread,
    withHandle,
    targetId,
    targetConversation,
    channelOpen,
    conversationsLoaded,
    openWith,
  ]);

  // This deployment does not offer messaging. Checked before everything
  // below, because none of it applies: there is no device to set up, no
  // settings to have loaded, and nothing the reader could answer to change it.
  // Somebody only gets here by address -- every way in is already gone -- so
  // the page says where they are rather than looking broken.
  if (!dmEnabled) {
    return (
      <div>
        <StatusMessage
          icon={<ShieldCheck className="size-6" aria-hidden />}
          title={t("platformDisabled")}
          description={t("platformDisabledBody")}
          backTo="/"
          backLabel={t("nav:home")}
        />
      </div>
    );
  }

  // A runtime with no web workers cannot hold a ratchet at all, and saying so
  // is more use than the generic failure it would otherwise reach.
  if (!ratchetSupported()) {
    return (
      <div>
        <StatusMessage
          icon={<ShieldCheck className="size-6" aria-hidden />}
          title={t("unsupportedBrowser")}
        />
      </div>
    );
  }

  if (device.isError) {
    return (
      <div className="flex flex-col items-center">
        <StatusMessage
          icon={<ShieldCheck className="size-6" aria-hidden />}
          title={t("deviceFailed")}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={device.isFetching}
          onClick={() => void device.refetch()}
        >
          {t("common:tryAgain")}
        </Button>
      </div>
    );
  }

  // An account that has not answered the age question cannot message anybody
  // and nobody can message it, so there is no list to show and no conversation
  // to open: every control on this page would refuse. So the question is the
  // page, rather than a notice on top of an empty one -- and it is asked here
  // as well as in Settings, because this is where somebody arrives wanting to
  // use the thing it gates.
  if (settingsLoaded && !canMessage) {
    return (
      <div className="space-y-6">
        <header className="space-y-1">
          <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        </header>
        <AgeUnansweredPanel id="messages-age" />
      </div>
    );
  }

  return (
    // Fills the shell: `main` has a real height now, so the thread can be what
    // is left of it after the header, and its log is the only thing that
    // scrolls.
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
          <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
          {t("encryptedNotice")}
        </p>
      </header>

      {/* Above the thread, because it is about the account rather than about
          whoever is on screen — and because a device waiting on an answer is
          waiting on a person who has to see it to give one. */}
      <NewDevicePrompt />

      {/* The other side of the same verification, on the device that asked. */}
      <HistoryAskNotice />

      {/* Who there is to talk to lives in the sidebar, which drills into this
          route -- so the page is only ever the one conversation. That is what
          leaves a phone the whole width for it. */}
      {current?.pending ? (
        // Named on it, and has not answered. The thread is not drawn at all:
        // there is nothing in it yet for this account, because nothing is
        // delivered to somebody who has not agreed to be there.
        <InvitationPanel key={current.id} conversationId={current.id} name={groupName(current)} />
      ) : current ? (
        // Keyed on the conversation: a thread holds a half-typed message, and
        // the one you were writing to Alice must not follow you to Bob.
        <Thread
          key={current.id}
          conversationId={current.id}
          otherUserId={current.other_user_id}
          memberIds={current.member_ids ?? []}
          name={isGroup(current) ? groupName(current) : nameOf(current.other_user_id)}
          // Everybody the thread might have to draw. One map for the page, so
          // a person looks the same in the header, in a message and in a quote.
          people={personFor}
        />
      ) : withHandle ? (
        // Somebody was asked for. Either their thread is on its way, or there
        // is no channel and the panel says what would open one.
        failedFor === withHandle ? (
          <div className="space-y-3 text-center">
            <p className="text-muted-foreground text-sm">{t("openFailed")}</p>
            {/* A button rather than the effect having another go on its own:
                the address has not changed, so nothing would re-run it, and a
                state change that did would keep re-running it against whatever
                is refusing. */}
            <Button
              variant="outline"
              onClick={() => targetId !== undefined && openWith(targetId, withHandle)}
            >
              {t("tryAgain")}
            </Button>
          </div>
        ) : target.isLoading || !conversationsLoaded || channelOpen ? (
          <p className="text-muted-foreground text-sm">{t("loading")}</p>
        ) : target.data ? (
          <StartWithPerson person={target.data} />
        ) : (
          <StatusMessage
            icon={<UserX className="size-6" aria-hidden />}
            title={t("unknownAccount")}
          />
        )
      ) : (
        // The list, not a note about where the list is. On a phone the sidebar
        // shuts on the way here, so this is the only thing on screen -- and on
        // a wide screen it is a landing view rather than an empty one.
        <section className="rounded-lg border">
          <h2 className="border-b px-3 py-2 font-medium text-sm">{t("empty.title")}</h2>
          <div className="p-2">
            <ConversationList explain />
          </div>
        </section>
      )}
    </div>
  );
}

/**
 * How long a quiet gap has to be before the next message starts a new run.
 *
 * A run is one person speaking once. Same sender is not enough on its own --
 * two messages a day apart are two occasions, and drawing them as one leaves
 * the second wearing the first one's timestamp.
 */
const RUN_GAP_MS = 5 * 60 * 1000;

/** The clock time a message was said at, in the reader's own convention. */
const clockTime = (at: string): string => {
  const date = new Date(at);
  return Number.isNaN(date.getTime())
    ? ""
    : dateTimeFormat(undefined, {
        timeStyle: "short",
        hour12: hour12Option(),
      }).format(date);
};

/** Whether the second message carries on the first one's run. */
const continuesRun = (before: StoredMessage, after: StoredMessage) => {
  if (before.mine !== after.mine) return false;
  // The same person, not merely the same side. On a pair those are the same
  // question and both messages carry no author at all, so it is unchanged
  // there; on a group two people answering one after the other are two runs,
  // and folding them into one would put the second person's words under the
  // first one's face.
  if (before.author !== after.author) return false;
  const gap = new Date(after.at).getTime() - new Date(before.at).getTime();
  // An unreadable time groups by sender alone rather than breaking every run.
  return Number.isNaN(gap) || gap < RUN_GAP_MS;
};

/**
 * How far one of your own messages has got, at the end of the run it is in.
 *
 * One tick means a device of theirs holds it; two mean somebody looked. With
 * nothing back yet there is no tick: the message being on screen already says
 * it went, because one that reached nobody is refused rather than shown. A tick
 * is drawn from what came back, so a thread that reports nothing shows none.
 */
const Receipt = ({ state }: { state?: ReceiptState }) => {
  const { t } = useTranslation("messages");
  const label = t(`receipt.${state ?? "sent"}`);
  return (
    <span className={cn("relative flex items-center", state === "read" && "text-primary")}>
      {/* Said either way: an absent tick is a state, not an absent one. */}
      <span className="sr-only">{label}</span>
      {state === "read" ? (
        <CheckCheck className="size-3.5" aria-hidden />
      ) : state === "delivered" ? (
        <Check className="size-3.5" aria-hidden />
      ) : null}
    </span>
  );
};

/** A person as the thread needs to draw them: a picture and a colour. */
type Speaker =
  | {
      user_id?: number;
      id?: number;
      username?: string | null;
      discriminator?: number | null;
      avatar_url?: string | null;
      profile_decorations?: ProfileDecorationsOutput | null;
    }
  | null
  | undefined;

/**
 * One side's picture, drawn once per run of their messages.
 *
 * Smaller on a narrow screen, where the width it costs is width the message
 * does not get.
 */
const SPEAKER_SIZE = "size-6 sm:size-8";

const Speaking = ({
  who,
  hidden,
  small = false,
}: {
  who: Speaker;
  hidden: boolean;
  /** In a quote, where it names a speaker rather than heading their run. */
  small?: boolean;
}) =>
  hidden || !who ? (
    // The space is held either way, so a run's messages stay in one column
    // rather than stepping sideways under the first of them.
    <div className={cn(small ? "size-4" : SPEAKER_SIZE, "shrink-0")} aria-hidden />
  ) : (
    <ProfileAvatar
      user={{ ...who, id: who.id ?? who.user_id }}
      decorations={who.profile_decorations}
      className={cn("shrink-0", small ? "size-4" : SPEAKER_SIZE)}
    />
  );

function Thread({
  conversationId,
  otherUserId,
  memberIds,
  name,
  people,
}: {
  conversationId: string;
  otherUserId: number;
  /**
   * Everybody a message here is encrypted for. One entry for a pair; more once
   * a group can be opened. Kept apart from `otherUserId`, which is who the
   * thread is drawn as and is still one person until the list can draw a
   * roster.
   */
  memberIds: number[];
  name: string;
  /** Everybody the page can name and draw, keyed by account. */
  people: Map<number, Speaker>;
}) {
  const { t } = useTranslation(["messages", "common"]);
  const { user: me } = useAuth();
  const thread = useThread(conversationId);
  /**
   * The other side, where there is one side. A pair has exactly one, and that
   * is what the header is named after.
   */
  const sole = memberIds.length === 1 ? people.get(memberIds[0]) : undefined;
  /**
   * Who said it.
   *
   * A message carries its author once a thread can hold more than two people.
   * One stored before that does not, and neither does one on a pair, where
   * "not mine" has only ever had one answer -- so a pair falls back to the one
   * person on the other side and reads exactly as it always has.
   */
  const speakerOf = (message: StoredMessage): Speaker =>
    message.mine ? me : message.author === undefined ? sole : people.get(message.author);
  const send = useSendMessage(conversationId, memberIds);
  const actions = useMessageActions(conversationId, memberIds);
  const [draft, setDraft] = useState("");
  /** The message being answered, and the one being rewritten. Never both. */
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  /**
   * Whose actions a tap has opened.
   *
   * A pointer reveals them by hovering the message; a touch screen has no
   * hover, so tapping the bubble is what asks for them. One at a time, because
   * the toolbar is about the message under it.
   */
  const [tapped, setTapped] = useState<string | null>(null);
  const log = useRef<HTMLDivElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  /** Every message on screen, so a quote can go back to the one it names. */
  const rows = useRef(new Map<string, HTMLDivElement>());
  /** Where a quote just took the reader, marked long enough to be noticed. */
  const [landedOn, setLandedOn] = useState<string | null>(null);

  /**
   * Bring the message a quote names back into view.
   *
   * The log's own `scrollTop`, moved by the difference between the two boxes --
   * not `scrollIntoView`, which asks the browser to scroll *every* scrollport
   * the element sits in, including ones with `overflow: hidden` that offer the
   * reader no way back.
   */
  const goToMessage = (id: string) => {
    const target = rows.current.get(id);
    const box = log.current;
    if (!target || !box) return;
    const gap = target.getBoundingClientRect().top - box.getBoundingClientRect().top;
    // A third of the way down rather than hard against the top edge: what was
    // said before it is usually why it was said.
    box.scrollTop += gap - box.clientHeight / 3;
    setLandedOn(id);
  };

  /**
   * Anywhere else closes it.
   *
   * Opened by tapping a message, the bar has no other way out: there is no
   * hover to leave and nothing on it says "done". A pointer landing outside
   * the message it belongs to is that, and so is Escape.
   *
   * The emoji picker is portaled to the end of the document, so it is outside
   * the message by DOM and inside it by intent -- hence the second test.
   */
  useEffect(() => {
    if (!tapped) return;
    const close = (event: Event) => {
      const target = event.target as HTMLElement | null;
      if (rows.current.get(tapped)?.contains(target ?? null)) return;
      if (target?.closest("[data-radix-popper-content-wrapper]")) return;
      setTapped(null);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTapped(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", onEscape);
    };
  }, [tapped]);

  // The mark is about the arrival, not about the message, so it clears itself.
  useEffect(() => {
    if (!landedOn) return;
    const timer = setTimeout(() => setLandedOn(null), 1600);
    return () => clearTimeout(timer);
  }, [landedOn]);

  // The composer is as tall as what is in it, up to the cap the CSS sets --
  // measured rather than counted, so a long line that wrapped takes the room
  // it actually needs. Reset first: scrollHeight cannot shrink on its own.
  //
  // The borders are added back because the box is sized border-box and
  // scrollHeight is not: one line set to exactly its own scrollHeight is two
  // pixels short of itself, which is enough to scroll an empty composer.
  useEffect(() => {
    const field = composer.current;
    if (!field) return;
    field.style.height = "auto";
    const borders = field.offsetHeight - field.clientHeight;
    field.style.height = `${field.scrollHeight + borders}px`;
  }, [draft]);

  const messages = thread.data ?? [];
  const noted = usePeerDeviceChanges().data;
  /**
   * When somebody on this conversation changed their devices, as this device
   * noticed it, oldest first. Said once where it happened and left at that:
   * there is nothing to do about it.
   */
  const deviceChanges = useMemo(
    () =>
      memberIds
        .flatMap((userId) => (noted?.[userId] ?? []).map((at) => ({ userId, at: Date.parse(at) })))
        .sort((a, b) => a.at - b.at),
    [memberIds, noted]
  );
  const changesBetween = (after: number, until: number) =>
    deviceChanges
      .filter((change) => change.at > after && change.at <= until)
      .map((change) => (
        <p
          key={`devices-${change.userId}-${change.at}`}
          className="py-1 text-center text-muted-foreground text-xs"
        >
          {t("peerDevicesChanged", { name: getUserHandle(people.get(change.userId)) })}
        </p>
      ));
  // An open thread is a read thread — including whatever arrives while it is
  // open, which is why the count is what re-runs it.
  useMarkThreadRead(conversationId, messages.length, memberIds);
  useEffect(() => {
    // The log's own scrollTop, not `scrollIntoView`. That asks the browser to
    // bring an element into view by scrolling *every* scrollport it sits in --
    // including ones with `overflow: hidden`, which are still scrollable to a
    // script even though nothing offers the reader a way back. The only box
    // that should move here is this one.
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  const focusComposer = () => composer.current?.focus();

  /** Answer this one: the composer keeps whatever is half-typed in it. */
  const startReply = (id: string) => {
    setEditing(null);
    setReplyTo(id);
    setTapped(null);
    focusComposer();
  };

  /** Rewrite this one, in the composer rather than in the bubble -- the same
   *  field, the same growing, and one place where a message is written. */
  const startEdit = (message: StoredMessage) => {
    setReplyTo(null);
    setEditing(message.id);
    setDraft(message.body);
    setTapped(null);
    focusComposer();
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft("");
  };

  const submit = () => {
    const body = draft.trim();
    if (!body || send.isPending || actions.edit.isPending) return;
    if (editing) {
      const target = editing;
      setEditing(null);
      setDraft("");
      // Two ways for a correction not to happen, and the words have to come
      // back for both: the send threw, or it resolved `false` because there
      // was nothing left to edit -- another tab removed the message while this
      // one was still showing it. Only the first is an error.
      const restore = () => {
        setEditing(target);
        setDraft(body);
        focusComposer();
      };
      actions.edit.mutate(
        { targetId: target, body },
        {
          onSuccess: (edited) => {
            if (!edited) restore();
          },
          onError: restore,
        }
      );
      return;
    }
    const answering = replyTo ?? undefined;
    setDraft("");
    setReplyTo(null);
    // What was typed comes back if it could not be sent: the composer is the
    // only place it exists, and a failed send should not eat it.
    send.mutate(
      { body, replyTo: answering },
      {
        onError: () => {
          setDraft(body);
          if (answering) setReplyTo(answering);
        },
      }
    );
  };

  const toggleReaction = (message: StoredMessage, emoji: string) =>
    actions.react.mutate({
      targetId: message.id,
      emoji,
      on: !message.reactions?.[emoji]?.mine,
    });

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border">
      {/* The handle, with its number in the lighter weight it wears
          everywhere else. `name` is the plain-text fallback for a person this
          device cannot resolve, and is what the failure notice below reads. */}
      <div className="shrink-0 border-b px-3 py-2 font-medium text-sm">
        {sole ? <UserHandle user={sole} /> : name}
      </div>
      <div
        ref={log}
        // Reaching the end of the thread stops there rather than handing the
        // rest of the gesture to whatever is behind it.
        // The top padding is headroom for the actions of the first message,
        // which are drawn above it: a scrollport clips what is outside it, and
        // with only the ordinary padding there the first message's bar is the
        // one you cannot reach. It is the height of that bar -- a row of
        // `size-7` buttons, its own padding and border, and the gap under it --
        // rounded up to the next step.
        className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-3 pt-10 pb-3"
      >
        {messages.length === 0 ? (
          <>
            <p className="text-muted-foreground text-sm">{t("noHistoryHere")}</p>
            {changesBetween(Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY)}
          </>
        ) : (
          <>
            {messages.map((message, index) => {
              // One picture per run rather than per message: a picture beside
              // every line of somebody talking is the same fact six times, and
              // the run is what the eye reads as one person speaking.
              const startsRun = index === 0 || !continuesRun(messages[index - 1], message);
              // The time goes under the last of a run, for the same reason: it
              // is when they finished saying it.
              const endsRun =
                index === messages.length - 1 || !continuesRun(message, messages[index + 1]);
              const answered = message.replyTo
                ? (messages.find((entry) => entry.id === message.replyTo) ?? null)
                : null;
              const reactions = Object.entries(message.reactions ?? {});
              // A new day, or the first thing this device holds.
              const opensDay =
                index === 0 || localDayKey(messages[index - 1].at) !== localDayKey(message.at);
              return (
                <Fragment key={message.id}>
                  {changesBetween(
                    index === 0 ? Number.NEGATIVE_INFINITY : Date.parse(messages[index - 1].at),
                    Date.parse(message.at)
                  )}
                  {opensDay ? (
                    <div className="flex items-center gap-3 py-2">
                      <span className="h-px flex-1 bg-border" />
                      <span className="shrink-0 font-medium text-muted-foreground text-xs">
                        {formatDayHeading(message.at, t as TranslateFn)}
                      </span>
                      <span className="h-px flex-1 bg-border" />
                    </div>
                  ) : null}
                  <div
                    ref={(node) => {
                      if (node) rows.current.set(message.id, node);
                      else rows.current.delete(message.id);
                    }}
                    className={cn(
                      // Aligned to the top of the bubble: a picture beside the last
                      // line of a long message reads as belonging to whatever comes
                      // after it rather than to what it is under.
                      "group/message flex items-start gap-2",
                      message.mine && "flex-row-reverse",
                      startsRun && index > 0 && "pt-2"
                    )}
                  >
                    {/* The picture, with the time hung under it.
                      The time is positioned rather than stacked: in the flow it
                      makes every row as tall as a picture plus a line of text,
                      including the rows that show neither -- which opens a gap
                      between every message of a run. Out of the flow the column
                      is the size it always was, and the time sits under the
                      face it belongs to.

                      Its width is fixed and wider than the picture, because
                      what has to fit there is the time: centred on the picture
                      alone it overflows both ways -- off the side of the thread
                      on one and across the message on the other -- and how far
                      depends on a clock format this cannot know. */}
                    <div className="relative flex w-12 shrink-0 justify-center">
                      <Speaking who={speakerOf(message)} hidden={!startsRun} />
                      {startsRun ? (
                        <span
                          className="absolute inset-x-0 top-full mt-1.5 truncate text-center text-3xs text-muted-foreground tabular-nums"
                          title={formatDateTime(message.at)}
                        >
                          {clockTime(message.at)}
                        </span>
                      ) : null}
                    </div>
                    <div
                      className={cn(
                        // What the floating actions below are positioned against:
                        // this box is the message, quote and reactions included.
                        "relative flex min-w-0 max-w-[75%] flex-col gap-0.5",
                        message.mine && "items-end"
                      )}
                    >
                      {/* What this answers, quoted above it. A device that never
                      held the message being answered still shows the answer --
                      it just has nothing to quote and nowhere to go back to. */}
                      {message.replyTo ? (
                        answered ? (
                          <button
                            type="button"
                            onClick={() => goToMessage(answered.id)}
                            className="flex w-full min-w-0 flex-col gap-0.5 rounded-md border-primary/60 border-s-2 bg-muted/40 px-2 py-1 text-start hover:bg-muted"
                          >
                            <span className="flex min-w-0 items-center gap-1">
                              <Speaking who={speakerOf(answered)} hidden={false} small />
                              <span className="min-w-0 truncate font-medium text-primary text-xs">
                                {getUserHandle(speakerOf(answered))}
                              </span>
                            </span>
                            {/* Two lines of it at most: a quote is there to say
                            which message, not to say it again. */}
                            <span className="wrap-anywhere line-clamp-2 min-w-0 text-muted-foreground text-xs">
                              {answered.removedAt ? t("removed") : answered.body}
                            </span>
                          </button>
                        ) : (
                          <span className="flex max-w-full items-center gap-1 px-1 text-muted-foreground text-xs">
                            <Reply className="size-3 shrink-0" aria-hidden />
                            <span className="min-w-0 truncate">{t("reply.missing")}</span>
                          </span>
                        )
                      ) : null}
                      <div
                        className={cn(
                          "flex w-full items-start gap-1",
                          message.mine && "flex-row-reverse"
                        )}
                      >
                        {/* The bubble summons the actions for anything that
                          cannot hover. Not gated on a breakpoint: a wide
                          touch screen has no hover either, and a viewport
                          width is a poor guess at what a device can do -- so
                          the tap is simply always there, and on a pointer it
                          only ever agrees with what hovering already showed.
                          A click that ends a selection is not a tap, and a
                          link inside is doing something else.

                          It carries no role and takes no focus on purpose: a
                          button role would wrap the links inside it in a
                          button. A keyboard reaches the same bar by tabbing
                          into it instead -- the buttons stay in the document
                          and in the focus order at every width, and focusing
                          one opens the bar through `focus-within`. So the two
                          rules below are about a path that exists by another
                          route, not one that is missing. */}
                        {/* biome-ignore lint/a11y/noStaticElementInteractions: the actions are keyboard-reachable through focus-within */}
                        {/* biome-ignore lint/a11y/useKeyWithClickEvents: the actions are keyboard-reachable through focus-within */}
                        <div
                          className={cn(
                            "rounded-lg px-3 py-2 text-sm",
                            // `wrap-anywhere` rather than `break-words`: only this
                            // one counts towards how narrow the bubble may be, so a
                            // single unbroken run of characters wraps instead of
                            // sizing the bubble to itself and running off the side.
                            "wrap-anywhere w-fit max-w-full",
                            message.mine ? "bg-primary text-primary-foreground" : "bg-muted",
                            // Where a quote just landed, for as long as it takes to
                            // see it.
                            landedOn === message.id && "ring-2 ring-primary ring-offset-1"
                          )}
                          onClick={
                            message.removedAt
                              ? undefined
                              : (event) => {
                                  // A link inside is doing something else, and a
                                  // tap that ends a selection is not a tap.
                                  if ((event.target as HTMLElement).closest("a")) return;
                                  if (window.getSelection()?.isCollapsed === false) return;
                                  setTapped((open) => (open === message.id ? null : message.id));
                                }
                          }
                        >
                          {message.removedAt ? (
                            <span className="italic opacity-70">{t("removed")}</span>
                          ) : (
                            <MessageContent body={message.body} />
                          )}
                        </div>
                      </div>
                      {/* Over the message rather than beside it: a toolbar in the
                      flow moves the words to make room for itself every time a
                      cursor passes, and a thread that shifts under the pointer
                      is harder to read than one with something floating on it.
                      It sits on the inner corner -- the side the picture is
                      not -- and overlaps the top edge, so it is plainly about
                      the message under it. */}
                      {message.removedAt ? null : (
                        <div
                          className={cn(
                            // The gap between the bar and the message is padding on
                            // this box rather than a margin outside it, so the two
                            // of them are one unbroken thing to hover. A margin
                            // leaves a few dead pixels on the way up: the pointer
                            // crosses them, this message stops being hovered, the
                            // bar goes, and the message above lights up instead --
                            // which walks the bar up the thread and never lets you
                            // reach it.
                            "absolute bottom-full z-10 pb-1",
                            // Anchored to the message's own edge and growing
                            // inward, into the room the other quarter of the row
                            // always leaves -- anchored the other way it runs off
                            // the side of anything short.
                            message.mine ? "end-0" : "start-0",
                            // Out of sight, never out of the document: `hidden`
                            // takes the buttons out of the focus order too, and
                            // then a keyboard has no way to any of this. Faded
                            // and inert instead, and brought back by a hover, by
                            // focusing one of them, or by tapping the message.
                            tapped === message.id
                              ? "block"
                              : cn(
                                  "pointer-events-none block opacity-0",
                                  "group-hover/message:pointer-events-auto group-hover/message:opacity-100",
                                  "group-focus-within/message:pointer-events-auto group-focus-within/message:opacity-100"
                                ),
                            "transition-opacity"
                          )}
                        >
                          <div className="flex items-center gap-0.5 rounded-md border bg-popover p-0.5 shadow-md">
                            <TooltipProvider delayDuration={200}>
                              <ReactionPicker
                                className="size-7"
                                mine={
                                  new Set(
                                    reactions
                                      .filter(([, sides]) => sides.mine)
                                      .map(([emoji]) => emoji)
                                  )
                                }
                                disabled={actions.react.isPending}
                                onSelect={(emoji) => toggleReaction(message, emoji)}
                              />
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="size-7"
                                    onClick={() => startReply(message.id)}
                                  >
                                    <Reply className="size-3.5" aria-hidden />
                                    <span className="sr-only">{t("reply.action")}</span>
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent side="top">{t("reply.action")}</TooltipContent>
                              </Tooltip>
                              {/* Only your own: an edit or a removal is somebody acting
                          on what they themselves said, and the log refuses
                          anything else even if this offered it. */}
                              {message.mine ? (
                                <>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="size-7"
                                        onClick={() => startEdit(message)}
                                      >
                                        <Pencil className="size-3.5" aria-hidden />
                                        <span className="sr-only">{t("edit.action")}</span>
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="top">{t("edit.action")}</TooltipContent>
                                  </Tooltip>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="size-7 text-destructive"
                                        onClick={() => setRemoving(message.id)}
                                      >
                                        <Trash2 className="size-3.5" aria-hidden />
                                        <span className="sr-only">{t("remove.action")}</span>
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="top">{t("remove.action")}</TooltipContent>
                                  </Tooltip>
                                </>
                              ) : null}
                            </TooltipProvider>
                          </div>
                        </div>
                      )}
                      {reactions.length > 0 ? (
                        <div
                          className={cn("flex flex-wrap gap-1 px-1", message.mine && "justify-end")}
                        >
                          {reactions.map(([emoji, sides]) => {
                            const count = Number(sides.mine) + Number(sides.theirs);
                            return (
                              <button
                                key={emoji}
                                type="button"
                                aria-pressed={sides.mine}
                                aria-label={t("reactions.chip", { emoji, count })}
                                disabled={actions.react.isPending}
                                onClick={() => toggleReaction(message, emoji)}
                                className={cn(
                                  "flex h-6 items-center gap-1 rounded-full border px-1.5 text-xs transition-colors",
                                  sides.mine
                                    ? "border-primary/40 bg-primary/10"
                                    : "border-border bg-muted/40 text-muted-foreground hover:bg-muted"
                                )}
                              >
                                <span className="text-sm leading-none">{emoji}</span>
                                {/* Both of you, or one of you: only the first is
                                worth a number, and the label says it either
                                way. */}
                                {count > 1 ? <span className="tabular-nums">{count}</span> : null}
                              </button>
                            );
                          })}
                          {/* A second way in, where the reader's eye already is:
                            adding to a row of reactions is a different gesture
                            from acting on the message, and sending them up to
                            the bar for it makes it the same one. */}
                          <ReactionPicker
                            className={cn(
                              "size-6",
                              tapped === message.id
                                ? ""
                                : cn(
                                    // Inert as well as faded, the way the bar is:
                                    // an invisible button that still takes a tap
                                    // is a tap on the space beside the reactions
                                    // opening an emoji picker out of nowhere.
                                    "pointer-events-none opacity-0 transition-opacity",
                                    "group-hover/message:pointer-events-auto group-hover/message:opacity-100",
                                    "group-focus-within/message:pointer-events-auto group-focus-within/message:opacity-100"
                                  )
                            )}
                            mine={
                              new Set(
                                reactions.filter(([, sides]) => sides.mine).map(([emoji]) => emoji)
                              )
                            }
                            disabled={actions.react.isPending}
                            onSelect={(emoji) => toggleReaction(message, emoji)}
                          />
                        </div>
                      ) : null}
                      {/* The clock is under the picture now, so what is left here
                      is only what this one message has to say for itself. */}
                      {message.editedAt || (endsRun && message.mine) ? (
                        <span className="flex items-center gap-1 px-1 text-muted-foreground text-xs">
                          {message.editedAt ? <span>{t("edited")}</span> : null}
                          {endsRun && message.mine ? <Receipt state={message.receipt} /> : null}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </Fragment>
              );
            })}
            {changesBetween(Date.parse(messages[messages.length - 1].at), Number.POSITIVE_INFINITY)}
          </>
        )}
      </div>
      {/* What the composer is about, when it is about something. Above the
          field rather than inside it, so the words being typed are never
          mixed up with the message they answer or replace. */}
      {replyTo || editing ? (
        <div className="flex shrink-0 items-center gap-2 border-t px-3 pt-2 text-muted-foreground text-xs">
          {editing ? (
            <Pencil className="size-3 shrink-0" aria-hidden />
          ) : (
            <Reply className="size-3 shrink-0" aria-hidden />
          )}
          <span className="min-w-0 flex-1 truncate">
            {editing
              ? t("edit.editing")
              : t("reply.replyingTo", {
                  body: messages.find((entry) => entry.id === replyTo)?.body ?? "",
                })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={() => (editing ? cancelEdit() : setReplyTo(null))}
          >
            <X className="size-3.5" aria-hidden />
            <span className="sr-only">{t("common:cancel")}</span>
          </Button>
        </div>
      ) : null}
      <form
        className="flex shrink-0 items-end gap-2 border-t p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Textarea
          ref={composer}
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          // Enter sends, because that is what a composer this shape is for;
          // Shift+Enter is the newline, and the field grows to show it.
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              if (editing) cancelEdit();
              else setReplyTo(null);
              return;
            }
            if (event.key !== "Enter" || event.shiftKey) return;
            event.preventDefault();
            submit();
          }}
          placeholder={t("composerPlaceholder")}
          aria-label={t("composerPlaceholder")}
          // No scrollbar chrome: the field grows instead of scrolling until it
          // reaches the cap, and past that the caret is what moves the view.
          className="max-h-40 min-h-0 resize-none overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        />
        <Button
          type="submit"
          size="icon"
          className="shrink-0"
          disabled={send.isPending || !draft.trim()}
        >
          <Send className="size-4" aria-hidden />
          <span className="sr-only">{t("send")}</span>
        </Button>
      </form>
      {send.isError ? (
        <div className="px-3 pb-3">
          <p className="text-destructive text-sm">
            {send.error instanceof RecipientHasNoDeviceError
              ? t("recipientHasNoDevice", { name })
              : t("sendFailed")}
          </p>
        </div>
      ) : null}

      {/* Said plainly rather than promised: their client takes it off their
          copy, and a copy is what a message on somebody's device is. */}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => setRemoving(open ? removing : null)}
        title={t("remove.title")}
        description={t("remove.body")}
        confirmLabel={t("remove.action")}
        destructive
        isLoading={actions.remove.isPending}
        onConfirm={() => {
          if (removing) actions.remove.mutate(removing, { onSettled: () => setRemoving(null) });
        }}
      />
    </section>
  );
}

/**
 * A roster somebody has been named on, and has not answered.
 *
 * The whole roster is shown before the answer is given, because seeing who is
 * on it is what makes accepting consent rather than notification. There is no
 * thread underneath it: nothing is delivered to somebody who has not agreed to
 * be there, so there is nothing yet to read.
 */
function InvitationPanel({ conversationId, name }: { conversationId: string; name: string }) {
  const { t } = useTranslation(["messages", "common"]);
  const navigate = useNavigate();
  const { accept, decline } = useAnswerInvitation(conversationId);
  const busy = accept.isPending || decline.isPending;

  return (
    <div className="mx-auto max-w-md space-y-4 py-10 text-center">
      <h2 className="font-semibold text-xl tracking-tight">{t("messages:invitation.heading")}</h2>
      <p className="text-muted-foreground text-sm">{t("messages:invitation.who")}</p>
      <p className="break-words font-medium text-sm">{name}</p>
      <div className="flex justify-center gap-2">
        <Button onClick={() => accept.mutate()} disabled={busy}>
          {t("messages:invitation.join")}
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() =>
            decline.mutate(undefined, {
              // Nothing left to draw once it is declined, so the page goes
              // back to the list rather than sitting on a thread that is gone.
              onSuccess: () => void navigate({ to: "/messages", search: {} }),
            })
          }
        >
          {t("messages:invitation.decline")}
        </Button>
      </div>
    </div>
  );
}
