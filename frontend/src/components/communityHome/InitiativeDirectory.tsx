/**
 * The community's initiatives, in one section: the ones you're in, and the ones you
 * could join.
 *
 * This is the community's complete initiative list — the directory endpoint returns
 * every listed initiative plus the caller's own, whatever their policy — so it
 * replaces the standalone initiatives page rather than sitting beside it. Each
 * card carries what the initiative published about itself (name, colour,
 * description, roster size) and, for one you're in, your role and how much work
 * is inside. The caller's own state decides the single call to action:
 *
 *  - already a member → a link into the initiative, badged with your role;
 *  - `open` → a Join button, which creates the membership row RLS reads;
 *  - `request` → a Request to join button, or the standing "requested" mark
 *    once you've knocked. Nothing about what you can see moves until a manager
 *    answers, so the card says only that you asked.
 *
 * A community admin reads this page the same way anyone else does — their
 * authority over the community is unchanged, it just no longer decides what is
 * listed here. They walk in rather than knock, so a card they are not in
 * offers Join whatever its policy says.
 *
 * A manager also sees how many people are waiting at their own door: the count
 * reads zero for everyone who couldn't act on it anyway.
 *
 * The initiative's colour is the card's identity: it tints the border and
 * header wash, the same treatment project cards give their initiative colour.
 * The whole section collapses from its heading, remembered per community.
 */

import { Link } from "@tanstack/react-router";
import { Check, ChevronRight, Clock, Loader2, Plus, Users } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeDirectoryEntry,
  InitiativeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";
import { RequestToJoinDialog } from "@/components/initiatives/RequestToJoinDialog";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives, useJoinInitiative } from "@/hooks/useInitiatives";
import { useToolCountsByInitiative } from "@/hooks/useToolCounts";
import { useCommunityPath } from "@/lib/communityUrl";
import { hexToRgba, InitiativeColorDot, resolveInitiativeColor } from "@/lib/initiativeColors";
import { toast } from "@/lib/mascotToast";
import { getItem, setItem } from "@/lib/storage";
import { initiativeRoute, TOOL_ICONS, TOOLS, toolNavLabelKey } from "@/lib/tools";
import { cn } from "@/lib/utils";

export const DIRECTORY_SECTION_ID = "initiative-directory";

/** Per-community, so collapsing one community's list says nothing about another's. */
// The key keeps its old name, so a device keeps what it collapsed.
const collapsedStorageKey = (communityId: number) =>
  `guildHome.initiatives.collapsed.${communityId}`;

export interface InitiativeDirectoryProps {
  entries: InitiativeDirectoryEntry[];
  /** Opens the create dialog. Passed only when the reader may create one, so
   *  its presence is the permission gate. */
  onCreate?: () => void;
}

const POLICY_HINT_KEY: Record<InitiativeJoinPolicy, string> = {
  [InitiativeJoinPolicy.private]: "directory.policy.private",
  [InitiativeJoinPolicy.request]: "directory.policy.request",
  [InitiativeJoinPolicy.open]: "directory.policy.open",
};

const buildCardTint = (hexColor: string): CSSProperties => ({
  borderColor: hexToRgba(hexColor, 0.35),
  backgroundImage: `linear-gradient(150deg, ${hexToRgba(hexColor, 0.14)} 0%, ${hexToRgba(
    hexColor,
    0.04
  )} 40%, transparent 75%)`,
});

export const InitiativeDirectory = ({ entries, onCreate }: InitiativeDirectoryProps) => {
  const { t } = useTranslation(["communityHome", "initiatives", "nav"]);
  const gp = useCommunityPath();
  const { isCommunityAdmin } = useInitiativeAccess();
  const communityId = useActiveCommunityId();

  // One reading for everyone, community admin included: a card is yours when you
  // are in it, and on offer when you are not. An admin's authority still
  // reaches the whole community — it just no longer decides what this page lists,
  // so the group a card is in is exactly the answer to "am I in there
  // already": the title leads in from one group, the Join button from the
  // other, and no card carries both.
  const mine = entries.filter((entry) => entry.is_member);
  const canEnter = (entry: InitiativeDirectoryEntry) => entry.is_member;
  const joinable = entries.filter((entry) => !entry.is_member);
  const hasEnterable = mine.length > 0;

  // A community admin walks in rather than knocking: they hold the authority the
  // request queue exercises, so a card they are not in offers the same one
  // button whatever its policy.
  const walksIn = (entry: InitiativeDirectoryEntry) =>
    isCommunityAdmin || entry.join_policy === InitiativeJoinPolicy.open;

  // Only a card the reader can enter shows counts — for the rest
  // RLS would answer zero anyway — so nothing is fetched for a directory of
  // strangers.
  const initiativesQuery = useInitiatives({ enabled: hasEnterable });
  const toolCounts = useToolCountsByInitiative({ enabled: hasEnterable });

  const membershipById = new Map<number, InitiativeRead>(
    (initiativesQuery.data ?? []).map((initiative) => [initiative.id, initiative])
  );

  const [open, setOpen] = useState(() => getItem(collapsedStorageKey(communityId)) !== "true");
  // Switching communities keeps this mounted, so re-read the community whose list it now is.
  const [prevCommunityId, setPrevCommunityId] = useState(communityId);
  if (prevCommunityId !== communityId) {
    setPrevCommunityId(communityId);
    setOpen(getItem(collapsedStorageKey(communityId)) !== "true");
  }

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    setItem(collapsedStorageKey(communityId), String(!next));
  };

  const joinInitiative = useJoinInitiative({
    onSuccess: (initiative) => {
      toast.success(t("directory.joined", { name: initiative.name }));
    },
  });
  const joiningId = joinInitiative.isPending ? joinInitiative.variables?.initiativeId : undefined;

  // Which door is being knocked on, if any — the dialog is one instance for the
  // whole section rather than one per card.
  const [requesting, setRequesting] = useState<{ id: number; name: string } | null>(null);

  // Nothing to show and nothing to add: the community simply has no initiatives
  // this reader can reach, and the surrounding page says so where it matters.
  if (entries.length === 0 && !onCreate) {
    return null;
  }

  /**
   * What the reader is here: their role in the initiative. A member whose row
   * carries no role still gets the plain "you're in" mark.
   */
  const renderMembershipBadge = (entry: InitiativeDirectoryEntry) => {
    if (entry.role_display_name) {
      return (
        <Badge variant="secondary" className="shrink-0 gap-1">
          <Check className="h-3 w-3" aria-hidden="true" />
          {entry.role_display_name}
        </Badge>
      );
    }
    if (entry.is_member) {
      return (
        <Badge variant="secondary" className="shrink-0 gap-1">
          <Check className="h-3 w-3" aria-hidden="true" />
          {t("directory.memberBadge")}
        </Badge>
      );
    }
    return null;
  };

  /**
   * What is inside an initiative you're in: one stat per tool that initiative
   * actually offers you, in registry order, drawn from the same `Tool` map the
   * rest of the app uses — a new tool earns its number here without a line of
   * its own. Zeros are kept: "no files" is information too.
   *
   * On screen it is an icon and a number; a screen reader and a hover title get
   * the tool's name with it.
   */
  const renderToolStats = (entry: InitiativeDirectoryEntry) => {
    const initiative = membershipById.get(entry.id);
    if (!initiative) {
      return null;
    }
    return TOOLS.filter((tool) => initiative.can.view.includes(tool)).map((tool) => {
      const Icon = TOOL_ICONS[tool];
      const { counts, isLoading } = toolCounts[tool];
      const label = t("directory.toolCount", {
        label: t(toolNavLabelKey(tool), { ns: "nav" }),
        count: counts.get(entry.id) ?? 0,
      });
      return (
        <span key={tool} className="flex items-center gap-1.5" title={label}>
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          <span aria-hidden="true">{isLoading ? "…" : (counts.get(entry.id) ?? 0)}</span>
          <span className="sr-only">{label}</span>
        </span>
      );
    });
  };

  const renderCard = (entry: InitiativeDirectoryEntry) => (
    <Card
      key={entry.id}
      className="flex flex-col transition-shadow hover:shadow-md"
      style={buildCardTint(resolveInitiativeColor(entry.color))}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-0.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <InitiativeColorDot color={entry.color} className="shrink-0" />
              <CardTitle className="wrap-break-word min-w-0 text-lg leading-tight">
                {/* The title is the way in for a card you can enter; one you
                    can't stays plain text rather than a dead link. */}
                {canEnter(entry) ? (
                  <Link
                    to={gp(initiativeRoute(entry.id))}
                    className="rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    {entry.name}
                  </Link>
                ) : (
                  entry.name
                )}
              </CardTitle>
            </div>
            <p className="pl-5 text-muted-foreground text-xs">
              {t(POLICY_HINT_KEY[entry.join_policy] as never)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {/* Reads zero for anyone who couldn't answer the queue anyway, so
                the number appearing at all is the permission check — and it
                leads to the queue, which is a route of its own. */}
            {entry.pending_join_request_count > 0 ? (
              <Link
                to={gp(`${initiativeRoute(entry.id)}/settings/members`)}
                className="shrink-0 rounded-md outline-none focus-visible:ring-1 focus-visible:ring-ring"
                title={t("directory.pendingRequests", {
                  count: entry.pending_join_request_count,
                })}
              >
                <Badge variant="default" className="gap-1">
                  <Clock className="h-3 w-3" aria-hidden="true" />
                  <span aria-hidden="true">{entry.pending_join_request_count}</span>
                  <span className="sr-only">
                    {t("directory.pendingRequests", { count: entry.pending_join_request_count })}
                  </span>
                </Badge>
              </Link>
            ) : null}
            {renderMembershipBadge(entry)}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 pb-4">
        {entry.description ? (
          <div className="line-clamp-3 text-sm">
            <Markdown content={entry.description} />
          </div>
        ) : (
          <p className="text-muted-foreground text-sm italic">{t("initiatives:noDescription")}</p>
        )}
      </CardContent>
      <CardFooter className="mt-auto flex-wrap justify-between gap-x-3 gap-y-2 border-t border-t-inherit pt-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground text-sm">
          <span className="flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5" aria-hidden="true" />
            {t("directory.memberCount", { count: entry.member_count })}
          </span>
          {canEnter(entry) ? renderToolStats(entry) : null}
        </div>
        {/* Nothing to offer a card you're already in — its title leads there.
            Otherwise: walk in where you may, ask where you must. */}
        {canEnter(entry) ? null : walksIn(entry) ? (
          <Button
            size="sm"
            disabled={joinInitiative.isPending}
            onClick={() => joinInitiative.mutate({ initiativeId: entry.id })}
          >
            {joiningId === entry.id ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("directory.joining")}
              </>
            ) : (
              t("directory.join")
            )}
          </Button>
        ) : entry.join_policy === InitiativeJoinPolicy.request ? (
          entry.has_pending_request ? (
            // Waiting on a manager is a state, not an action: nothing the
            // requester can press moves it along.
            <span className="flex items-center gap-1.5 text-muted-foreground text-sm">
              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
              {t("directory.requested")}
            </span>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRequesting({ id: entry.id, name: entry.name })}
            >
              {t("directory.requestToJoin")}
            </Button>
          )
        ) : null}
      </CardFooter>
    </Card>
  );

  /** A group with no entries is not a heading over nothing — it is absent. */
  const renderGroup = (groupEntries: InitiativeDirectoryEntry[], labelKey: string) =>
    groupEntries.length === 0 ? null : (
      <div className="space-y-3">
        <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
          {t(labelKey as never)}
        </h3>
        <div className="grid grid-cols-fill-72/3 gap-4">{groupEntries.map(renderCard)}</div>
      </div>
    );

  return (
    <Collapsible open={open} onOpenChange={handleOpenChange} asChild>
      <section id={DIRECTORY_SECTION_ID} className="space-y-4" aria-labelledby="directory-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 id="directory-heading" className="font-semibold text-xl tracking-tight">
              <CollapsibleTrigger className="flex items-center gap-2 text-left">
                <ChevronRight
                  className={cn("h-5 w-5 shrink-0 transition-transform", open && "rotate-90")}
                  aria-hidden="true"
                />
                {t("directory.title")}
              </CollapsibleTrigger>
            </h2>
            <p className="pl-7 text-muted-foreground text-sm">{t("directory.subtitle")}</p>
          </div>
          {onCreate ? (
            <Button size="sm" onClick={onCreate}>
              <Plus className="h-4 w-4" />
              {t("initiatives:newInitiative")}
            </Button>
          ) : null}
        </div>

        <CollapsibleContent className="space-y-6">
          {renderGroup(mine, "directory.groups.mine")}
          {renderGroup(joinable, "directory.groups.joinable")}
        </CollapsibleContent>

        <RequestToJoinDialog
          initiative={requesting}
          open={requesting !== null}
          onOpenChange={(next) => {
            if (!next) {
              setRequesting(null);
            }
          }}
        />
      </section>
    </Collapsible>
  );
};
