import { useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, Lock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SmartChipAspect, type SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import { RequestAccessDialog, Requested, standingTarget } from "@/components/access/RequestAccess";
import { Button } from "@/components/ui/button";
import { ChecklistChip } from "@/components/ui/editor/nodes/checklist-chip";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useShareStanding } from "@/hooks/useShareRequests";
import { useChipState } from "@/hooks/useSmartChips";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { dateTimeFormat } from "@/lib/intl";
import { entityIcon } from "@/lib/searchResults";
import { chipAspect, chipDisplay, chipEntityType, chipRef } from "@/lib/smartChips";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface SmartChipProps {
  chipKind: SmartChipKind;
  entityId: number;
  /** The label stored in the document, shown when the thing cannot be read. */
  fallback: string;
}

/**
 * The chip itself.
 *
 * Inline it is the reading and nothing else — `In Progress`, `42 / 100`,
 * `Sep 12` — because a sentence that already names the task should not name it
 * twice. What the reading is ABOUT is one hover away: the card says what the
 * thing is called now, what kind of thing it is, and which fact this is.
 *
 * Each chip asks for itself and the asks of one moment go out together, so a
 * document with thirty of these still makes a single call.
 */
export function SmartChip(props: SmartChipProps) {
  // The one chip that is acted on rather than read is drawn as what it is: a
  // box to tick.
  if (chipAspect(props.chipKind) === SmartChipAspect.checklist) {
    return <ChecklistChip entityId={props.entityId} fallback={props.fallback} />;
  }
  return <ReadingChip {...props} />;
}

function ReadingChip({ chipKind, entityId, fallback }: SmartChipProps) {
  const { t, i18n } = useTranslation(["editor", "search", "access"]);
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();
  const state = useChipState(chipRef(chipKind, entityId));

  const entityType = chipEntityType(chipKind);
  // The answer carries the thing's name beside its reading, so the card names
  // what it is called NOW rather than what it was called when this was written
  // — and asking cost the page nothing beyond the reading itself.
  const liveTitle = state?.title;

  const display = chipDisplay(
    fallback,
    state,
    (iso) =>
      dateTimeFormat(i18n.language, { month: "short", day: "numeric" }).format(new Date(iso)),
    t("smartChips.none")
  );

  const refType = entityRefTypeFor(entityType);
  // Something that could not be read has nowhere to go — the same answer
  // whether it was deleted or was never this reader's to see.
  const reachable = refType !== null && display.live;
  const open = () => {
    if (!refType || !reachable) return;
    void navigate({ to: communityPath(communityId, entityRefRoute(refType, entityId)) });
  };

  const Icon = entityIcon(entityType);

  // Whether the reader may ask for it is read when they look at the card, so
  // a page of chips asks nothing until one is hovered.
  const [looking, setLooking] = useState(false);
  const [asking, setAsking] = useState(false);
  const { data: standing } = useShareStanding(entityType, entityId, looking && !reachable);
  const askable = !reachable && standing != null && standing.level == null;

  return (
    <>
      <HoverCard openDelay={200} closeDelay={100} onOpenChange={setLooking}>
        <HoverCardTrigger asChild>
          <button
            type="button"
            onClick={open}
            // `aria-disabled` rather than `disabled`: a disabled button takes no
            // pointer events, and the card is what explains why this one is dim.
            aria-disabled={!reachable}
            className={cn(
              // Sized in `em`, not a fixed step. A chip is a word in somebody's
              // sentence, so it belongs to whatever that sentence is set in —
              // dropped into a heading, a `text-xs` chip reads as a footnote
              // stuck to the title. 0.85em is what `text-xs` came to inside body
              // text, so ordinary prose looks exactly as it did and everything
              // else now scales with what it sits in — padding and margin
              // included, or the box tightens around the text as it grows.
              "mx-[0.15em] inline-flex items-center rounded-[0.25em] px-[0.4em] py-[0.15em] align-baseline font-medium text-[0.85em]",
              display.className,
              reachable ? "cursor-pointer hover:brightness-95" : "cursor-default"
            )}
            // A status carries a colour its project chose, which beats any tone.
            style={
              display.color
                ? { backgroundColor: `${display.color}26`, color: display.color }
                : undefined
            }
          >
            {display.text}
          </button>
        </HoverCardTrigger>
        <HoverCardContent align="start" className="w-auto max-w-72 p-3">
          <div className="flex items-start gap-2">
            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 space-y-1">
              <p className="truncate font-medium text-sm leading-tight">{liveTitle ?? fallback}</p>
              <p className="text-muted-foreground text-xs">
                {t(`search:types.${entityType}` as never)}
                {" · "}
                {t(`smartChips.aspects.${chipAspect(chipKind)}` as never)}
              </p>
              {reachable ? (
                <p className="flex items-center gap-1 text-primary text-xs">
                  <ArrowUpRight className="size-3 shrink-0" />
                  {t("smartChips.openHint")}
                </p>
              ) : askable ? (
                <>
                  <p className="text-muted-foreground text-xs">{t("access:request.cantSee")}</p>
                  {standing.pending ? (
                    <Requested level={standing.pending} className="text-xs" />
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="mt-1 h-7"
                      onClick={() => setAsking(true)}
                    >
                      <Lock />
                      {t("access:request.submit")}
                    </Button>
                  )}
                </>
              ) : (
                <p className="text-muted-foreground text-xs">{t("references.unavailable")}</p>
              )}
            </div>
          </div>
        </HoverCardContent>
      </HoverCard>
      {/* Beside the card rather than in it: the card closes as the pointer
        leaves for the dialog. */}
      {askable ? (
        <RequestAccessDialog
          open={asking}
          onOpenChange={setAsking}
          target={standingTarget(standing)}
        />
      ) : null}
    </>
  );
}
