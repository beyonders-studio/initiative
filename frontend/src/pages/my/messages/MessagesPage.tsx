import { useNavigate, useSearch } from "@tanstack/react-router";
import { KeyRound, ShieldCheck, UserX, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { AgeUnansweredPanel } from "@/components/connections/UnreachableEmptyState";
import { ConversationList } from "@/components/messages/ConversationList";
import { ratchetSupported } from "@/crypto/client";
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
  useDismissHistoryAsk,
  useDmDevice,
  useHistoryAsk,
  useStartConversation,
} from "@/hooks/useMyMessages";
import { useUserProfile } from "@/hooks/useUsers";
import { groupName, isGroup, roster } from "@/lib/conversationName";
import { getUserHandle } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { NewDevicePrompt } from "./NewDevicePrompt";
import { StartWithPerson } from "./StartWithPerson";
import { type Speaker, Thread } from "./Thread";

/**
 * This device, waiting to be verified by another of the account's and sent
 * the messages it arrived without.
 *
 * The comparison is started on the other device; when it is, the verification
 * dialog opens here too. This says nothing about how long that will take,
 * because nothing here knows: the other device has to be opened by a person
 * before it can answer.
 *
 * It can be put away by hand as well as by the day running out. Dismissing it
 * settles nothing: the ask is still outstanding, and history approved on the
 * other device afterwards still arrives — which is what the closing line says,
 * so nobody reads the button as calling the transfer off.
 */
const HistoryAskNotice = () => {
  const { t } = useTranslation("messages");
  const ask = useHistoryAsk();
  const dismiss = useDismissHistoryAsk();

  if (!ask.data) return null;

  return (
    <section className="space-y-3 border-b bg-muted/40 px-6 py-4">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium text-sm">{t("historyAsk.title")}</h2>
            <p className="max-w-prose text-muted-foreground text-sm">{t("historyAsk.body")}</p>
          </div>
          <p className="max-w-prose text-muted-foreground text-xs">{t("historyAsk.dismissNote")}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="ml-auto shrink-0 text-muted-foreground"
          aria-label={t("historyAsk.dismiss")}
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate()}
        >
          <X className="size-4" aria-hidden />
        </Button>
      </div>
    </section>
  );
};

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
export function MessagesPage() {
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
    // Fills the shell, and its log is the only thing that scrolls. No page
    // title: the sidebar beside it already says where this is, and every line
    // a heading took was a line of conversation off the screen.
    <div className="flex h-full min-h-0 flex-col gap-4">
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
          <SkeletonRegion>
            <ListSkeleton rows={3} />
          </SkeletonRegion>
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
