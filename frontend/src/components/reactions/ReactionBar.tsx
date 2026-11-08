/**
 * The row of reaction chips under a piece of content, plus the buttons to add
 * one: a one-tap thumbs up, and the picker for everything else.
 *
 * Generic over the target: it takes a `ReactionTarget` and an id, so anything
 * the backend registry makes reactable renders the same bar without a second
 * component. Nothing here knows what a comment is.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ReactionGroup, ReactionTarget } from "@/api/generated/initiativeAPI.schemas";
import { ReactionPicker } from "@/components/reactions/ReactionPicker";
import { useToggleReaction } from "@/hooks/useReactions";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/** Shared empty list, so "no reactions" keeps a stable identity across renders
 *  and does not read as fresh server data below. */
const NO_REACTIONS: ReactionGroup[] = [];

/** The one reaction worth a button of its own: agreeing is what most people
 *  come to a reaction bar to do. */
const QUICK_REACTION = "👍";

interface ReactionBarProps {
  targetType: ReactionTarget;
  targetId: number;
  groups?: ReactionGroup[];
  /** False while the viewer may read but not write (a read-only community). */
  canReact?: boolean;
  className?: string;
}

export const ReactionBar = ({
  targetType,
  targetId,
  groups = NO_REACTIONS,
  canReact = true,
  className,
}: ReactionBarProps) => {
  const { t } = useTranslation("common");
  const toggle = useToggleReaction();
  // The server's answer to our own toggle, shown until fresh data arrives
  // through the normal path — the invalidated query, or a realtime nudge from
  // someone else reacting. Dropped the moment the prop brings a new list, so a
  // reaction added elsewhere is never masked by our own last answer.
  const [live, setLive] = useState<ReactionGroup[] | null>(null);
  const [basis, setBasis] = useState(groups);
  if (groups !== basis) {
    setBasis(groups);
    setLive(null);
  }
  const shown = live ?? groups;

  const mine = useMemo(
    () => new Set(shown.filter((group) => group.reacted).map((group) => group.emoji)),
    [shown]
  );

  /** "Alice, Bob and 3 others" — the named reactors are capped by the API, so
   *  whoever is missing is counted rather than dropped. */
  const reactorList = (group: ReactionGroup) => {
    const names = group.users.map((user) => getUserDisplayName(user));
    const extra = group.count - names.length;
    if (names.length === 0) {
      return t("reactions.countOnly", { count: group.count });
    }
    return extra > 0
      ? t("reactions.namesAndMore", { names: names.join(", "), count: extra })
      : names.join(", ");
  };

  const react = (emoji: string) => {
    if (!canReact) return;
    toggle.mutate(
      { targetType, targetId, emoji },
      { onSuccess: (summary) => setLive(summary.groups) }
    );
  };

  if (shown.length === 0 && !canReact) return null;

  // Once somebody has given a thumbs up its chip is the one-tap toggle, and a
  // second button doing the same thing would only ask which to press.
  const offerQuick = canReact && !shown.some((group) => group.emoji === QUICK_REACTION);

  return (
    // The bar carries its own tooltip provider: it drops into pages that have
    // one and pages that do not, and it should not need either to know.
    <TooltipProvider delayDuration={200}>
      <div className={cn("flex flex-wrap items-center gap-1", className)}>
        {shown.map((group) => (
          <Tooltip key={group.emoji}>
            <TooltipTrigger asChild>
              <button
                type="button"
                disabled={!canReact || toggle.isPending}
                onClick={() => react(group.emoji)}
                aria-pressed={group.reacted}
                aria-label={t("reactions.chipLabel", {
                  emoji: group.emoji,
                  count: group.count,
                })}
                className={cn(
                  "flex h-7 items-center gap-1 rounded-full border px-2 text-xs transition-colors",
                  "disabled:cursor-default disabled:opacity-70",
                  group.reacted
                    ? "border-primary/40 bg-primary/10 text-foreground"
                    : "border-border bg-muted/40 text-muted-foreground hover:bg-muted"
                )}
              >
                <span className="text-sm leading-none">{group.emoji}</span>
                {/* One of something is what the emoji already says. The count
                    appears when it is telling you something the picture does
                    not -- and the label carries it either way. */}
                {group.count > 1 ? <span className="tabular-nums">{group.count}</span> : null}
              </button>
            </TooltipTrigger>
            <TooltipContent>{reactorList(group)}</TooltipContent>
          </Tooltip>
        ))}
        {offerQuick && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={toggle.isPending}
                onClick={() => react(QUICK_REACTION)}
                aria-label={t("reactions.quick", { emoji: QUICK_REACTION })}
                className="h-7 w-7 p-0 text-sm grayscale hover:grayscale-0 focus-visible:grayscale-0"
              >
                <span aria-hidden="true">{QUICK_REACTION}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("reactions.quick", { emoji: QUICK_REACTION })}</TooltipContent>
          </Tooltip>
        )}
        {canReact && <ReactionPicker onSelect={react} mine={mine} disabled={toggle.isPending} />}
      </div>
    </TooltipProvider>
  );
};
