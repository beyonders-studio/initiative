import { Link, useSearch } from "@tanstack/react-router";
import { Search, Users } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ContactGrantRead,
  DmRosterMember,
  Presence,
  ProfileDecorationsOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { ConnectionActionsMenu } from "@/components/connections/ConnectionActionsMenu";
import { PrivatePanel, unreachableReason } from "@/components/connections/UnreachableEmptyState";
import { NewConversationDialog } from "@/components/messages/NewConversationDialog";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  useAcceptConnection,
  useAcceptMessageRequest,
  useConnections,
  useDmPermissions,
  useDmSettings,
  useMessageRequests,
  useRemoveConnection,
  useRemoveMessageRequest,
} from "@/hooks/useDirectMessages";
import { useConversations, useLatestMessages, useUnreadMessages } from "@/hooks/useMyMessages";
import { groupName, isGroup, roster } from "@/lib/conversationName";
import { getUrlHandle, getUserHandle } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";

const ROW = "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-sm";

/**
 * Everything a row needs to know about somebody: what they are called, and how
 * they look.
 *
 * Structural rather than one of the two shapes that satisfy it. A contact grant
 * and a conversation's roster both carry this much, and a row does not care
 * which of them it came from -- what it cares about is that a person on screen
 * always has a name and a face.
 */
type Person = {
  user_id: number;
  username: string;
  discriminator: number;
  avatar_url?: string | null;
  profile_decorations?: ProfileDecorationsOutput | null;
  presence?: Presence;
};

/**
 * The menu belongs to the row, not to the list: on a pointer it opens out of
 * the row's edge when the row is under the cursor, and it comes back whenever
 * it is focused or open, so a keyboard never chases a control it cannot see.
 * A touch screen has no hover to reveal it, so below `sm` it is simply there.
 *
 * It animates its *width* rather than only its opacity, the way the initiative
 * and project rows in the main sidebar do — so a name has the whole row until
 * somebody reaches for the menu, instead of being cut short all the time to
 * hold a space for something that is not on screen.
 */
const ROW_MENU = cn(
  "h-7 w-7 shrink-0 p-0",
  "motion-reduce:transition-none sm:w-0 sm:overflow-hidden sm:opacity-0 sm:transition-all",
  "sm:group-hover/row:w-7 sm:group-hover/row:opacity-100",
  "sm:group-focus-within/row:w-7 sm:group-focus-within/row:opacity-100",
  "sm:data-[state=open]:w-7 sm:data-[state=open]:opacity-100"
);

/**
 * How many faces the space a single avatar occupies will hold, overlapped.
 *
 * Above it the row draws the group symbol instead. Not a truncation: a roster
 * is what tells one group from another, so showing some of it and not the rest
 * is worse than showing none of it -- and the row spells out every name beside
 * this either way.
 */
const FACES_THAT_FIT = 3;

/** Who is on a group, drawn as their faces where they all fit. */
const RosterFaces = ({ members }: { members: DmRosterMember[] }) =>
  members.length === 0 || members.length > FACES_THAT_FIT ? (
    <Users className="size-6 shrink-0 p-0.5" aria-hidden="true" />
  ) : (
    <span className="flex size-6 shrink-0 items-center -space-x-2" aria-hidden="true">
      {members.map((member) => (
        <ProfileAvatar
          key={member.user_id}
          user={{ ...member, id: member.user_id }}
          decorations={member.profile_decorations}
          hidePresence
          className="size-4 ring-1 ring-background"
        />
      ))}
    </span>
  );

/**
 * A thread with more than two people on it.
 *
 * Kept apart from `Entry` rather than folded into it: every row above is a
 * person -- it has their picture, their handle, and a menu of things to do
 * about them -- and a group is none of those. It is a conversation, addressed
 * by its id, named by who is on it.
 */
interface GroupRow {
  conversationId: string;
  name: string;
  /** Who is on it, so the row shows faces rather than a symbol for "several". */
  members: DmRosterMember[];
  waiting: number;
  /** Named on it, but has not answered yet. */
  pending: boolean;
  /** When its newest message was written, or it was opened: what orders it. */
  latest: number;
}

/** One person this list can offer, whether or not a thread is open with them. */
interface Entry {
  userId: number;
  person: Person;
  /** Absent until a conversation has actually been opened with them. */
  conversationId?: string;
  waiting: number;
  /** As a group's. Nothing for somebody with no conversation yet. */
  latest: number;
}

/** One row of the list: a person, or a conversation with several. */
type Thread = { kind: "person"; entry: Entry } | { kind: "group"; row: GroupRow };

const latestOfThread = (thread: Thread) =>
  thread.kind === "person" ? thread.entry.latest : thread.row.latest;

/**
 * Which agreement a pending request is part of — the only thing that differs
 * between two rows asking the reader the same question.
 */
type RequestKind = "connection" | "message";
interface PendingRequest {
  grant: ContactGrantRead;
  kind: RequestKind;
}

/**
 * Who there is to talk to, wherever that has to be offered.
 *
 * Drawn in two places on purpose. It is the sidebar's whole content on a wide
 * screen — and on a phone the sidebar shuts the moment you pick My Messages,
 * the way it does for every other destination, so the page it lands on has to
 * be the list rather than an apology for not being one. One component, so the
 * two cannot drift.
 *
 * One list, newest message first: a conversation with one person and one with
 * several sit together, since what the reader is after is whoever spoke last.
 * A thread this device holds nothing of goes by when it was opened, and
 * somebody you may message but have not yet comes last. Requests waiting on an
 * answer sit above it all.
 *
 * Above all of it, two controls that answer opposite questions. The field
 * narrows what is already here, on the handle, which is the one thing every
 * row carries — nothing is fetched for it and nobody new appears. Finding
 * somebody who is *not* here is the button beside it, which is why they sit
 * together.
 *
 * `explain` is for the wide half of the two. Being on Private is the one empty
 * list whose reason takes a paragraph and two buttons to give, and a sidebar
 * column is not the place for either -- the page beside it always has room,
 * and an account with nothing to open is always looking at that page.
 *
 * Every row addresses its person in the URL rather than holding a selection of
 * its own: the page already resolves `?with=` to a conversation, and a link is
 * what a back button, a middle click and a shared address all understand.
 */
export const ConversationList = ({ explain = false }: { explain?: boolean } = {}) => {
  const { t } = useTranslation(["messages", "connections"]);
  const { with: openHandle, thread: openThread } = useSearch({ strict: false }) as {
    with?: string;
    thread?: string;
  };
  const [term, setTerm] = useState("");

  const conversations = useConversations();
  const requests = useMessageRequests();
  const connections = useConnections();
  const settings = useDmSettings();

  const reachable = useMemo(() => requests.data?.accepted ?? [], [requests.data?.accepted]);

  const rows = useMemo(
    () => conversations.data?.conversations ?? [],
    [conversations.data?.conversations]
  );

  /**
   * Who the list can name, from both places a person is known.
   *
   * A conversation carries its own roster, which is the only source for
   * somebody a group put you in touch with: agreeing to a roster is the whole
   * of the ask, so there need be no request between the two of you to look up.
   * An accepted request is laid over it for the people who also sent one.
   */
  const personFor = useMemo(() => {
    const people = new Map<number, Person>();
    for (const row of rows) for (const member of roster(row)) people.set(member.user_id, member);
    for (const grant of reachable) people.set(grant.user_id, grant);
    return people;
  }, [rows, reachable]);
  const unread = useUnreadMessages(rows.map((row) => row.id));
  const latestMessage = useLatestMessages(rows.map((row) => row.id));
  const latestOf = useCallback(
    (row: (typeof rows)[number]) =>
      Date.parse(latestMessage.data?.get(row.id) ?? row.created_at) || 0,
    [latestMessage.data]
  );

  // Somebody you may message but have not opened a channel with yet.
  const unopened = useMemo(
    () =>
      reachable.filter(
        (grant) => !rows.some((row) => !isGroup(row) && row.other_user_id === grant.user_id)
      ),
    [reachable, rows]
  );

  // Nothing is asked of the server for a term: every row here is already in
  // hand, and the handle is all any of them carries.
  const matches = useMemo(() => {
    const needle = term.trim().toLowerCase().replace(/^@/, "");
    return (person: Person) => !needle || getUserHandle(person).toLowerCase().includes(needle);
  }, [term]);

  /**
   * Everything waiting on an answer, either way round and of either kind.
   *
   * Both kinds together: to the person reading it they are the same question
   * — somebody wants to be able to talk and it has not started yet — and the
   * mark that brought them here never said which sort it was. Theirs first: those are the ones only
   * you can move. Yours are listed so an ask you sent does not look like it
   * never happened.
   */
  const waiting = useMemo(() => {
    const sources: [
      RequestKind,
      { incoming?: ContactGrantRead[]; outgoing?: ContactGrantRead[] } | undefined,
    ][] = [
      ["message", requests.data],
      ["connection", connections.data],
    ];
    const incoming: PendingRequest[] = [];
    const outgoing: PendingRequest[] = [];
    for (const [kind, data] of sources) {
      for (const grant of data?.incoming ?? []) incoming.push({ grant, kind });
      for (const grant of data?.outgoing ?? []) outgoing.push({ grant, kind });
    }
    return [...incoming, ...outgoing].filter(({ grant }) => matches(grant));
  }, [requests.data, connections.data, matches]);

  const acceptMessage = useAcceptMessageRequest();
  const declineMessage = useRemoveMessageRequest();
  const acceptConnection = useAcceptConnection();
  const declineConnection = useRemoveConnection();

  const accept = ({ grant, kind }: PendingRequest) =>
    kind === "connection"
      ? acceptConnection.mutate({ userId: grant.user_id })
      : acceptMessage.mutate({ userId: grant.user_id });

  const dismiss = ({ grant, kind }: PendingRequest) =>
    kind === "connection"
      ? declineConnection.mutate({ userId: grant.user_id })
      : declineMessage.mutate({ userId: grant.user_id });

  const answering =
    acceptMessage.isPending ||
    declineMessage.isPending ||
    acceptConnection.isPending ||
    declineConnection.isPending;

  const groupRows: GroupRow[] = useMemo(
    () =>
      rows
        .filter((row) => isGroup(row))
        .map((row) => ({
          conversationId: row.id,
          name: groupName(row),
          members: roster(row),
          waiting: unread.data?.get(row.id) ?? 0,
          pending: Boolean(row.pending),
          latest: latestOf(row),
        })),
    [rows, unread.data, latestOf]
  );

  const entries: Entry[] = useMemo(
    () => [
      // Only conversations whose other side this reader can still see. A grant
      // that has lapsed -- they were ignored, or whatever let the two of you
      // talk has ended -- leaves a row with no name to show and no handle to
      // address, so listing it offers a person who cannot be opened. What this
      // device already collected stays on it either way.
      ...rows
        .filter((row) => !isGroup(row) && personFor.has(row.other_user_id))
        .map((row) => ({
          userId: row.other_user_id,
          person: personFor.get(row.other_user_id) as Person,
          conversationId: row.id,
          waiting: unread.data?.get(row.id) ?? 0,
          latest: latestOf(row),
        })),
      ...unopened.map((grant) => ({
        userId: grant.user_id,
        person: grant,
        waiting: 0,
        latest: Number.NEGATIVE_INFINITY,
      })),
    ],
    [rows, personFor, unopened, unread.data, latestOf]
  );

  // One question about everybody listed, not one per row: what the menu on a
  // row can offer -- connecting, above all -- depends on the server's answer
  // about that person, and a list of them is a list of the same question.
  const permissions = useDmPermissions(useMemo(() => entries.map((e) => e.userId), [entries]));
  const answers = permissions.data?.permissions ?? {};

  // A term narrows people on their handles and groups on their names, which
  // is all a group has.
  const threads: Thread[] = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return [
      ...entries
        .filter((entry) => matches(entry.person))
        .map((entry): Thread => ({ kind: "person", entry })),
      ...groupRows
        .filter((row) => !needle || row.name.toLowerCase().includes(needle))
        .map((row): Thread => ({ kind: "group", row })),
    ].sort((a, b) => latestOfThread(b) - latestOfThread(a));
  }, [entries, groupRows, matches, term]);

  const searching = term.trim().length > 0;
  const reason = settings.data
    ? unreachableReason(!settings.data.age_answer_required, settings.data.dm_policy)
    : null;

  // Whether there is anything to narrow, asked of what the account has rather
  // than of what is left after typing — so the field does not disappear under
  // the cursor on a term that matches nobody.
  const anything =
    entries.length +
      (requests.data?.incoming?.length ?? 0) +
      (requests.data?.outgoing?.length ?? 0) +
      (connections.data?.incoming?.length ?? 0) +
      (connections.data?.outgoing?.length ?? 0) >
    0;

  const personRow = (entry: Entry) => {
    const them = entry.person;
    const handle = getUrlHandle(them);
    return (
      <li
        key={entry.conversationId ?? `u${entry.userId}`}
        className={cn(
          "group/row flex items-center rounded-md pe-1 hover:bg-accent",
          handle === openHandle && "bg-accent"
        )}
      >
        <Link
          to="/messages"
          search={{ with: handle }}
          className={cn(ROW, !entry.conversationId && "text-muted-foreground")}
        >
          <ProfileAvatar
            user={{ ...them, id: them.user_id }}
            decorations={them.profile_decorations}
            presence={them.presence}
            className="size-6"
          />
          <UserHandle
            user={them}
            className="min-w-0 flex-1"
            nameClassName="min-w-0 truncate"
            numberClassName="shrink-0"
          />
          {/* A dot carries no text, so the count it stands for is written
                  out for anyone not looking at it. */}
          {entry.waiting ? (
            <span className="relative ms-auto flex shrink-0 items-center">
              <span className="sr-only">{t("unreadHere", { count: entry.waiting })}</span>
              <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
            </span>
          ) : null}
          {!entry.conversationId ? (
            <span className="shrink-0 text-xs">{t("startHint")}</span>
          ) : null}
        </Link>
        {/* Outside the link, because acting on somebody is not the same
                gesture as opening what they said. The ways in are left out:
                the row is one, and clicking it is the conversation. */}
        <ConnectionActionsMenu
          user={{
            id: them.user_id,
            username: them.username,
            discriminator: them.discriminator,
          }}
          className={ROW_MENU}
          permission={answers[String(them.user_id)] ?? null}
          omit={["message"]}
        />
      </li>
    );
  };

  const groupRow = (row: GroupRow) => (
    <li
      key={row.conversationId}
      className={cn(
        "group/row flex items-center rounded-md pe-1 hover:bg-accent",
        row.conversationId === openThread && "bg-accent"
      )}
    >
      <Link
        to="/messages"
        search={{ thread: row.conversationId }}
        className={cn(ROW, row.pending && "text-muted-foreground")}
      >
        <RosterFaces members={row.members} />
        <span className="min-w-0 flex-1 truncate">{row.name}</span>
        {row.waiting ? (
          <span className="relative ms-auto flex shrink-0 items-center">
            <span className="sr-only">{t("unreadHere", { count: row.waiting })}</span>
            <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
          </span>
        ) : null}
        {/* Named on it, not yet on it. The row opens the thread, which is
            where the answer is given. */}
        {row.pending ? <span className="shrink-0 text-xs">{t("groupThreads.invited")}</span> : null}
      </Link>
    </li>
  );

  return (
    <div className="space-y-3">
      {/* Drawn before anything is known, and before the loading line below:
          an account with nobody in it is exactly the one that needs the way
          to find somebody. */}
      <div className="flex items-center gap-1 px-2">
        {anything ? (
          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder={t("search.placeholder")}
              aria-label={t("search.label")}
              className="h-8 ps-7 text-sm"
            />
          </div>
        ) : (
          <div className="min-w-0 flex-1" />
        )}
        <NewConversationDialog />
      </div>

      {conversations.isLoading ? (
        <p className="px-2 py-1 text-muted-foreground text-sm">{t("loading")}</p>
      ) : (
        <>
          {waiting.length > 0 ? (
            <section>
              <h3 className="px-2 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
                {t("requests.heading")}
              </h3>
              <ul className="space-y-2 px-2 py-1">
                {waiting.map((row) => {
                  const { grant, kind } = row;
                  return (
                    <li key={`${kind}-${grant.user_id}`}>
                      <div className="flex items-center gap-2">
                        <ProfileAvatar
                          user={{ ...grant, id: grant.user_id }}
                          decorations={grant.profile_decorations}
                          presence={grant.presence}
                          className="size-7"
                        />
                        <UserHandle
                          user={grant}
                          className="min-w-0 flex-1 text-sm"
                          nameClassName="min-w-0 truncate"
                          numberClassName="shrink-0"
                        />
                        {/* Withdrawing your own ask and declining theirs are the
                            same write, so an outgoing row offers only that one --
                            and one button is a trailing action on the name rather
                            than a full-width bar stranded under it. */}
                        {grant.outgoing ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 shrink-0 px-2 text-xs"
                            disabled={answering}
                            onClick={() => dismiss(row)}
                          >
                            {t("requests.cancel")}
                          </Button>
                        ) : null}
                      </div>
                      {/* What they asked for: the one thing the two kinds do not
                          have in common, and the one that decides what accepting
                          it opens. */}
                      <p className="mt-1 text-muted-foreground text-xs">
                        {t(
                          grant.outgoing
                            ? kind === "connection"
                              ? "requests.youAskedToConnect"
                              : "requests.youAsked"
                            : kind === "connection"
                              ? "requests.wantsToConnect"
                              : "requests.asked"
                        )}
                      </p>
                      {grant.outgoing ? null : (
                        <div className="mt-1.5 flex gap-1.5">
                          <Button
                            size="sm"
                            className="h-7 flex-1"
                            disabled={answering}
                            onClick={() => accept(row)}
                          >
                            {t("requests.accept")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 flex-1"
                            disabled={answering}
                            onClick={() => dismiss(row)}
                          >
                            {t("requests.decline")}
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          {threads.length === 0 ? (
            searching ? (
              // Only when the term found nothing at all. A request matching it
              // is drawn above, and saying "nobody matches" over the top of
              // somebody's name contradicts the page.
              waiting.length === 0 ? (
                <p className="px-2 py-1 text-muted-foreground text-sm">{t("search.noMatches")}</p>
              ) : null
            ) : /* Why it is empty, where the reason is the reader's own settings
                   rather than an absence of people. Nothing is guessed before
                   the settings arrive: absent, they read as an account that has
                   answered nothing, which is the one thing that must never be
                   shown to somebody who has. */
            reason === "age" ? (
              <div className="space-y-2 px-2 py-1">
                <p className="text-muted-foreground text-sm">{t("ageLocked")}</p>
                <Button variant="outline" size="sm" asChild>
                  <Link to="/profile/privacy">{t("connections:unreachable.private.settings")}</Link>
                </Button>
              </div>
            ) : reason === "private" && explain ? (
              <div className="px-2 py-1">
                <PrivatePanel />
              </div>
            ) : waiting.length === 0 ? (
              <p className="px-2 py-1 text-muted-foreground text-sm">{t("nobodyYet")}</p>
            ) : null
          ) : (
            <ul>
              {threads.map((thread) =>
                thread.kind === "person" ? personRow(thread.entry) : groupRow(thread.row)
              )}
            </ul>
          )}
        </>
      )}
    </div>
  );
};
