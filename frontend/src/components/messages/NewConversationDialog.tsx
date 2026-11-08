import { useNavigate } from "@tanstack/react-router";
import { MessageSquarePlus, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DirectMessagePermissionRead,
  PeopleCommunitySection,
  PersonRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ConnectionActionsMenu } from "@/components/connections/ConnectionActionsMenu";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { parseHandle, useDmPermissions, useRequestConnection } from "@/hooks/useDirectMessages";
import { useRosterCheck, useStartGroup } from "@/hooks/useMyMessages";
import { useMoreCommunityPeople, usePeopleSections } from "@/hooks/usePeople";
import { getErrorMessage } from "@/lib/errorMessage";
import { getInitials } from "@/lib/initials";
import { toast } from "@/lib/mascotToast";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { cn } from "@/ui/lib/utils";
import { LoadMore } from "@/ui/load-more";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/** How long typing settles before the roster follows it. */
const SEARCH_SETTLES_MS = 250;

/**
 * Somebody who is not in the list yet.
 *
 * The conversation list can only offer people it already has — the ones who
 * agreed to hear from you. Everybody else is reached from here, and there are
 * exactly two ways to name them, which is why they share one field. Typing
 * narrows the communities you are in. Typing a
 * whole handle, number included, also offers a connection: that is the one
 * shape that reaches an account no roster of yours will ever list.
 *
 * This replaces a page of its own, minus the browsing: that page listed
 * everyone you shared a community with, and the only thing anybody did from a
 * row was reach for one of them.
 *
 * Picking somebody navigates rather than acting. A row is not a promise that a
 * channel exists — most of the people it lists have never agreed to anything —
 * and the page it lands on is the one that already knows how to say so and
 * what to offer instead.
 */
export const NewConversationDialog = () => {
  const { t } = useTranslation(["messages", "connections", "settings"]);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);
  /**
   * People gathered for a group, in the order they were added.
   *
   * Empty for the ordinary case: picking one person still opens their thread
   * on the first click, because that is what this dialog is mostly for. A
   * group is built by adding rather than by picking, so the two do not compete
   * for the same gesture.
   */
  const [gathered, setGathered] = useState<PersonRead[]>([]);

  // The field answers every keystroke; the request waits for typing to stop.
  const settled = useDebouncedValue(term, SEARCH_SETTLES_MS);
  // Not until it is opened: the aggregate walks every community the reader
  // is in, and a button nobody has pressed is no reason to walk them.
  const sections = usePeopleSections(settled, { enabled: open });

  const groups = useMemo(() => sections.data?.sections ?? [], [sections.data]);
  const ids = useMemo(() => {
    const seen = new Set<number>();
    for (const group of groups) {
      for (const person of group.items) seen.add(person.id);
    }
    return [...seen];
  }, [groups]);
  // One question for everybody on screen, not one per row.
  const permissions = useDmPermissions(open ? ids : []);
  const answers = permissions.data?.permissions ?? {};

  const requestConnection = useRequestConnection();
  // Only a whole handle is a connection: half of one is a search term.
  const handle = parseHandle(term);

  const close = () => {
    setOpen(false);
    setTerm("");
    setError(null);
    setGathered([]);
  };

  const gather = (person: PersonRead) =>
    setGathered((held) =>
      held.some((one) => one.id === person.id)
        ? held.filter((one) => one.id !== person.id)
        : [...held, person]
    );

  const gatheredIds = useMemo(() => gathered.map((person) => person.id), [gathered]);
  const rosterCheck = useRosterCheck(open ? gatheredIds : []);
  const startGroup = useStartGroup();

  const refusal = rosterCheck.data;
  // Two names, because that is what the caller can act on: which pair to break
  // up. Which of them is limiting who may message them is theirs, not ours.
  const unreachable = refusal?.unreachable_pair?.length
    ? gathered
        .filter((person) => refusal.unreachable_pair?.includes(person.id))
        .map((person) => getUserDisplayName(person))
    : [];
  const tooLarge = Boolean(refusal?.too_large);
  // A roster that has just changed has not been checked yet, and one whose
  // check failed has not been checked at all. Proposing either would hand the
  // refusal back from the server after the person committed, which is the late
  // answer asking early was meant to replace.
  const checking = rosterCheck.isFetching;
  const checkFailed = rosterCheck.isError;
  const blocked = unreachable.length > 0 || tooLarge || checking || checkFailed;

  const propose = () => {
    setError(null);
    startGroup.mutate(gatheredIds, {
      onSuccess: (conversation) => {
        close();
        void navigate({ to: "/messages", search: { thread: conversation.id } });
      },
      onError: (err) => setError(getErrorMessage(err, "errors:DM_ROSTER_NOT_REACHABLE")),
    });
  };

  const pick = (person: PersonRead) => {
    close();
    void navigate({ to: "/messages", search: { with: getUrlHandle(person) } });
  };

  const connect = () => {
    if (!handle) return;
    setError(null);
    requestConnection.mutate(
      { data: handle },
      {
        onSuccess: () => {
          toast.success(t("settings:privacy.connections.sent"));
          close();
        },
        onError: (err) => setError(getErrorMessage(err, "errors:CONTACT_GRANT_CANNOT_REACH")),
      }
    );
  };

  // Whether there is anybody at all to offer.
  const anybody = groups.some((group) => group.items.length > 0);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setOpen(true);
        else close();
      }}
    >
      {/* The one thing on this column that starts something rather than
          narrowing what is already there, so it is the one thing drawn as a
          filled button. The name is inside it for a screen reader either way;
          the tooltip is for everybody else, since an icon alone says "add"
          without saying add what. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>
              <Button size="icon" className="size-8 shrink-0">
                <MessageSquarePlus className="size-4" aria-hidden />
                <span className="sr-only">{t("messages:newConversation.trigger")}</span>
              </Button>
            </DialogTrigger>
          </TooltipTrigger>
          <TooltipContent side="top">{t("messages:newConversation.trigger")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("messages:newConversation.title")}</DialogTitle>
          <DialogDescription>{t("messages:newConversation.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-1">
          <Input
            autoFocus
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
              setError(null);
            }}
            placeholder={t("messages:newConversation.placeholder")}
            aria-label={t("messages:newConversation.placeholder")}
            onKeyDown={(event) => {
              if (event.key === "Enter" && handle) connect();
            }}
          />
          <p className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
            {error ?? t("messages:newConversation.hint")}
          </p>
        </div>

        {/* Above the rosters, because it is about somebody who is not in them.
            It appears only once the handle is whole: a connection is addressed
            by the exact name and number, and half of one addresses nobody. */}
        {handle ? (
          <Button
            variant="outline"
            className="w-full justify-start"
            disabled={requestConnection.isPending}
            onClick={connect}
          >
            {t("messages:newConversation.connect", {
              handle: `${handle.username}#${String(handle.discriminator).padStart(4, "0")}`,
            })}
          </Button>
        ) : null}

        {gathered.length > 0 ? (
          <div className="space-y-2 rounded-md border p-2">
            <ul className="flex flex-wrap gap-1">
              {gathered.map((person) => (
                <li key={person.id}>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-7 gap-1 px-2"
                    // Labelled rather than left to its contents: the name is
                    // already on screen, and reading it twice says less than
                    // saying what the button does.
                    aria-label={t("messages:newConversation.removeFromGroup", {
                      name: getUserDisplayName(person),
                    })}
                    onClick={() => gather(person)}
                  >
                    <span className="max-w-32 truncate">{getUserDisplayName(person)}</span>
                    <X className="size-3" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>

            {/* Said while there is still a name to drop, which is the whole
                point of asking before the roster is submitted. */}
            {unreachable.length > 1 ? (
              <p className="text-destructive text-xs">
                {t("messages:newConversation.cannotReachEachOther", {
                  first: unreachable[0],
                  second: unreachable[1],
                })}
              </p>
            ) : tooLarge ? (
              <p className="text-destructive text-xs">
                {t("messages:newConversation.tooManyPeople", {
                  count: refusal?.max_members ?? 0,
                })}
              </p>
            ) : checkFailed ? (
              <p className="text-destructive text-xs">
                {t("messages:newConversation.checkUnavailable")}
              </p>
            ) : checking ? (
              <p className="text-muted-foreground text-xs">
                {t("messages:newConversation.checkingRoster")}
              </p>
            ) : (
              <p className="text-muted-foreground text-xs">
                {t("messages:newConversation.groupHint")}
              </p>
            )}

            <Button
              className="w-full"
              disabled={gathered.length < 2 || blocked || startGroup.isPending}
              onClick={propose}
            >
              {t("messages:newConversation.startGroup", { count: gathered.length + 1 })}
            </Button>
          </div>
        ) : null}

        <div className="-mx-2 max-h-80 overflow-y-auto px-2">
          {sections.isLoading ? (
            <SkeletonRegion className="py-2">
              <ListSkeleton rows={4} />
            </SkeletonRegion>
          ) : !anybody ? (
            /* A section arrives for every community that has somebody else in
               it, listable or not, so its presence is what separates the two
               silences: people are there and none of them take messages, or
               there is nobody to have taken them. */
            <p className="py-2 text-muted-foreground text-sm">
              {settled.trim()
                ? t("messages:newConversation.noMatches")
                : groups.length
                  ? t("messages:newConversation.empty")
                  : t("messages:newConversation.noCommunities")}
            </p>
          ) : (
            <div className="space-y-3">
              {groups
                .filter((group) => group.items.length > 0)
                .map((group) => (
                  <CommunityRoster
                    // Remounted on a new term, which is what puts a community
                    // somebody expanded back to its first page: under a
                    // different term it is a different set of people, and
                    // carrying the expansion over would fetch a second page
                    // nobody asked for.
                    key={`${group.community_id}:${settled}`}
                    section={group}
                    search={settled}
                    answers={answers}
                    onPick={pick}
                    onGather={gather}
                    gathered={new Set(gatheredIds)}
                  />
                ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

/**
 * One community's people, grown rather than paged.
 *
 * A picker is read downwards: stepping between pages would take away the row
 * somebody had just spotted, so *Show more* appends. Page one arrives with the
 * walk the dialog already made; everything after it is this community's own
 * request, and only once somebody asks.
 *
 * It answers for its own extra rows too. The dialog asks one question about
 * everybody the walk returned, which is the whole of what most readers ever
 * see; anybody past that is this section's to ask about.
 */
const CommunityRoster = ({
  section,
  search,
  answers,
  onPick,
  onGather,
  gathered,
}: {
  section: PeopleCommunitySection;
  search: string;
  answers: Record<string, DirectMessagePermissionRead>;
  onPick: (person: PersonRead) => void;
  onGather: (person: PersonRead) => void;
  gathered: Set<number>;
}) => {
  const [wantsMore, setWantsMore] = useState(false);
  const more = useMoreCommunityPeople(section.community_id, search, wantsMore);

  const extra = useMemo(
    () => more.data?.pages.flatMap((page) => page.sections?.[0]?.items ?? []) ?? [],
    [more.data]
  );
  const extraAnswers = useDmPermissions(useMemo(() => extra.map((p) => p.id), [extra]));
  const answerFor = (id: number) =>
    answers[String(id)] ?? extraAnswers.data?.permissions?.[String(id)];

  // Still more to come until this community says otherwise. While a page is on
  // its way the button stays, disabled, rather than vanishing and returning.
  const exhausted = wantsMore && more.isSuccess && !more.hasNextPage;
  const hasMore = section.has_next && !exhausted;

  return (
    <section>
      <h3 className="flex items-center gap-1.5 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
        {/* Decorative: its fallback is the community's own initials, which
            would otherwise be read out in front of the name it stands for. */}
        <Avatar aria-hidden className="size-4 rounded-md">
          {section.icon_url ? <AvatarImage src={section.icon_url} alt="" /> : null}
          <AvatarFallback className="rounded-md bg-muted text-3xs text-muted-foreground">
            {getInitials(section.community_name, "G")}
          </AvatarFallback>
        </Avatar>
        <span className="min-w-0 flex-1 truncate">{section.community_name}</span>
        <span className="shrink-0 tabular-nums">{section.total_count}</span>
      </h3>
      <ul>
        {[...section.items, ...extra].map((person) => {
          const answer = answerFor(person.id);
          return (
            <PickerPerson
              key={person.id}
              person={person}
              answer={answer}
              onPick={onPick}
              onGather={onGather}
              gathered={gathered.has(person.id)}
            />
          );
        })}
      </ul>
      <LoadMore
        hasMore={hasMore}
        loading={more.isFetching}
        onLoadMore={() => (wantsMore ? void more.fetchNextPage() : setWantsMore(true))}
      />
    </section>
  );
};

/**
 * One person, offered.
 *
 * Every refusal collapses into one word server-side, so a row built from it
 * cannot say which refusal it is -- and does not try. It simply stops being a
 * way in.
 */
const PickerPerson = ({
  person,
  answer,
  onPick,
  onGather,
  gathered,
}: {
  person: PersonRead;
  answer: DirectMessagePermissionRead | undefined;
  onPick: (person: PersonRead) => void;
  onGather: (person: PersonRead) => void;
  gathered: boolean;
}) => {
  const { t } = useTranslation(["messages", "connections"]);
  const denied = answer?.permission === "denied";

  return (
    <li className="flex items-center gap-1">
      <button
        type="button"
        disabled={denied}
        onClick={() => onPick(person)}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-sm",
          denied ? "cursor-default opacity-60" : "hover:bg-accent"
        )}
      >
        <ProfileAvatar
          user={person}
          decorations={person.profile_decorations}
          presence={person.presence}
          className="size-6"
        />
        <UserHandle
          user={person}
          className="min-w-0 flex-1"
          nameClassName="min-w-0 truncate"
          numberClassName="shrink-0"
        />
        <span className="shrink-0 text-muted-foreground text-xs">
          {denied
            ? t("messages:newConversation.unreachable")
            : answer?.permission === "may_request"
              ? t("connections:actions.ask")
              : null}
        </span>
      </button>
      {/* Gathering somebody is not picking them: a click on the row still
          opens their own thread, which is what this dialog is mostly for. A
          group is built here instead, so the two never compete for the same
          gesture. Shut for somebody who cannot be reached, for the same reason
          the row itself is. */}
      <Button
        type="button"
        size="icon"
        variant={gathered ? "secondary" : "ghost"}
        className="size-7 shrink-0"
        disabled={denied}
        aria-pressed={gathered}
        onClick={() => onGather(person)}
      >
        <Plus className="size-3.5" aria-hidden />
        <span className="sr-only">
          {t("messages:newConversation.addToGroup", { name: getUserDisplayName(person) })}
        </span>
      </Button>
      {/* Outside the button, and outside its `disabled`: if the way in is
          shut, everything else you might do about them stays open -- go and
          look at them, connect, ignore. */}
      <ConnectionActionsMenu
        user={{
          id: person.id,
          username: person.username,
          discriminator: person.discriminator,
        }}
        className="size-8 shrink-0"
        permission={answer ?? null}
        // The row is the way in. Everything else the menu holds -- the
        // profile above all -- is only here.
        omit={["message", "ask"]}
      />
    </li>
  );
};
