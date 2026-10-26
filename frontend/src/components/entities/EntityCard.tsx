import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  type RelatedEnd,
  SearchEntityType,
  type SmartChipState,
} from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useCommunityPath } from "@/lib/communityUrl";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { fileIcon } from "@/lib/fileIcon";
import { relatedTarget } from "@/lib/relationships";
import { hitIcon, searchHitPath } from "@/lib/searchResults";
import { CHIP_TONE_CLASSES } from "@/lib/smartChips";
import { entityRefRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

/** How much of a thing to draw. */
export type EntityCardVariant = "card" | "compact";

interface EntityCardProps {
  /** The thing on the far end of a link. */
  end: RelatedEnd;
  variant?: EntityCardVariant;
  /**
   * What the link says, drawn on the card itself. For a surface that shows every
   * link together rather than under a heading per kind of link.
   */
  badge?: string;
  /** When the link was made, if the surface shows it. */
  linkedAt?: string | null;
  /**
   * What the far end is currently doing — a task's column, an event's date, a
   * counter's reading. Read live rather than stored on the edge, so a card says
   * what the thing is now and not what it was when somebody linked it.
   */
  state?: SmartChipState | null;
  /**
   * Whether the far end has finished, where that means anything. `false` dims
   * the card: a blocker somebody has dealt with should stop drawing the eye
   * without having to be unlinked. `null` is a kind that never finishes, which
   * is most of them, and draws normally.
   */
  isOpen?: boolean | null;
  /** Take the link back. Omitted when this reader may not. */
  onRemove?: () => void;
  removing?: boolean;
  className?: string;
}

/**
 * One thing, whatever kind of thing it is.
 *
 * A list of links is a list of mixed kinds, so this draws any of them from what
 * a far end carries — what it is, what it is called, what it looks like, and the
 * tool it is addressed inside. Routing and the per-kind fallback icon come from
 * `searchHitPath` / `hitIcon`, the same pair the search results use, so a kind
 * added server-side is drawn here without an edit.
 *
 * Pictures, the emoji and the colour are tried in that order and at most one of
 * them is set; a kind with none of the three draws as its own icon, which is
 * most of them. A file picks its mark from what sort of file it is, out
 * of the same helper the file card uses.
 *
 * **`compact`** is a line in a list rather than a tile: the same facts, at the
 * size a sidebar column or a dialog can afford.
 */
export const EntityCard = ({
  end,
  variant = "card",
  badge,
  linkedAt,
  state,
  isOpen,
  onRemove,
  removing,
  className,
}: EntityCardProps) => {
  // Both namespaces: the kind names live with search, which is where they are
  // already written down for all fifteen of them.
  const { t } = useTranslation(["relations", "search"]);
  const gp = useCommunityPath();
  const linked = useRelativeTime(linkedAt ?? null);

  const target = relatedTarget(end);
  // The direct address where the far end carried enough to build one, and the
  // resolver where it did not — a thing addressed inside a parent whose id
  // nobody told us still has a page, it just takes a redirect to reach.
  const refType = entityRefTypeFor(end.type);
  const path = searchHitPath(target) ?? (refType ? entityRefRoute(refType, end.id) : null);
  // A file is not one sort of thing, so it picks its mark from what sort it
  // is — the same rule the file card follows, out of the same helper.
  const file = end.type === SearchEntityType.file ? fileIcon(end) : null;
  const KindIcon = file?.Icon ?? hitIcon(target);
  const kindLabel = t(`search:types.${end.type}`, { defaultValue: end.type });
  const title = end.title?.trim() || t("untitled");
  const pictures = end.image_urls
    .map((url) => resolveUploadUrl(url))
    .filter((url): url is string => Boolean(url));
  const compact = variant === "compact";

  /** The picture, emoji, colour or icon, filling whatever box it is given. */
  const mark = pictures.length ? (
    pictures.length === 1 ? (
      <LazyImage
        src={pictures[0]}
        alt=""
        className="h-full w-full"
        imgClassName="transition duration-300 group-hover:scale-105"
      />
    ) : (
      // Several, because nobody picked one: a wall of them says what a catalog
      // is better than any single picture would.
      <div
        className={cn(
          "grid h-full w-full gap-0.5",
          pictures.length === 2 ? "grid-cols-2" : "grid-cols-2 grid-rows-2"
        )}
      >
        {pictures.map((src, index) => (
          <LazyImage
            key={src}
            src={src}
            alt=""
            // Three pictures: the first takes the whole left column.
            className={cn("h-full w-full", pictures.length === 3 && index === 0 && "row-span-2")}
            imgClassName="transition duration-300 group-hover:scale-105"
          />
        ))}
      </div>
    )
  ) : (
    <div className="flex h-full items-center justify-center">
      {/* Proportions of the box, not of the window: the card's own width is set
          by the space its section has. */}
      {end.icon ? (
        <span aria-hidden className={compact ? "text-sm" : "text-4xl"}>
          {end.icon}
        </span>
      ) : end.color ? (
        <span
          aria-hidden
          className={cn("rounded-full", compact ? "h-2.5 w-2.5" : "h-1/4 w-1/4")}
          style={{ backgroundColor: end.color }}
        />
      ) : (
        <KindIcon
          className={cn(
            compact ? "h-3.5 w-3.5" : "h-1/3 w-1/3",
            file?.colorClass ?? "text-muted-foreground"
          )}
        />
      )}
    </div>
  );

  const settled = isOpen === false;
  /** The live reading, drawn in the tone the server chose for it. */
  const stateChip = state?.text ? (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 font-medium text-2xs",
        CHIP_TONE_CLASSES[state.tone]
      )}
    >
      {state.text}
    </span>
  ) : null;

  const kindCaption = linkedAt
    ? t("card.kindLinked", { kind: kindLabel, date: linked })
    : kindLabel;
  // Where it lives, ahead of what it is: six tasks called "Do a thing" are all
  // tasks, and the project is the only thing that tells them apart.
  const where = end.tool_title?.trim();
  const caption = where ? `${where} · ${kindCaption}` : kindCaption;

  // A row is a line in a list of links, the way a wiki lists them: what it is,
  // where it lives, and its state. What sort of thing it is and when it was
  // linked are under the pointer rather than a second line.
  const body = compact ? (
    <div className="flex min-w-0 items-center gap-2 px-2 py-1">
      <div className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-sm">
        {mark}
      </div>
      <span
        className={cn("max-w-[75%] shrink-0 truncate text-sm", settled && "text-muted-foreground")}
      >
        {title}
      </span>
      {/* Gives way before the title does: the name is the thing being read. */}
      {where ? (
        <span className="min-w-0 truncate text-muted-foreground text-xs">{where}</span>
      ) : null}
      <span className="flex-1" />
      {stateChip}
    </div>
  ) : (
    <>
      {/* One fixed shape whatever the kind, so a grid of mixed things does not
          jump between rows. Shorter below `sm`, as a file card is. */}
      <div className="relative aspect-4/3 overflow-hidden border-b bg-muted sm:aspect-square">
        {mark}
        {badge ? (
          <span className="absolute bottom-1.5 left-1.5 rounded-full bg-background/85 px-2 py-0.5 font-medium text-2xs text-foreground shadow-sm">
            {badge}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-0.5 p-3">
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <h3
                className={cn(
                  "line-clamp-2 font-semibold text-sm leading-snug",
                  settled ? "text-muted-foreground" : "text-card-foreground"
                )}
              >
                {title}
              </h3>
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
              <p>{title}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        {/* Two lines: where a thing lives is often longer than the box, and
            cutting it at one can leave the project name a stub. */}
        <p className="line-clamp-2 text-muted-foreground text-xs">{caption}</p>
        {stateChip ? <div className="pt-1">{stateChip}</div> : null}
      </div>
    </>
  );

  const shell = compact
    ? "group block w-full rounded-md transition"
    : "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition";
  const rowHint = [badge, title, caption].filter(Boolean).join(" · ");

  return (
    <div className="group/row relative">
      {path ? (
        <Link
          to={gp(path)}
          className={cn(
            shell,
            settled && "opacity-70",
            compact
              ? "hover:bg-accent/50"
              : "hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
            onRemove && compact && "pr-8",
            className
          )}
          title={compact ? rowHint : undefined}
        >
          {body}
        </Link>
      ) : (
        /* A thing this build cannot address — a kind it does not know, or one
           whose parent did not come back. Shown, because the link is real, but
           not offered as somewhere to go. */
        <div
          className={cn(
            shell,
            "cursor-default opacity-60",
            onRemove && compact && "pr-8",
            className
          )}
          title={t("card.unreachable")}
        >
          {body}
        </div>
      )}
      {onRemove ? (
        /* Outside the anchor: a button inside a link is neither, and the anchor
           is the whole card. */
        <Button
          type="button"
          variant={compact ? "ghost" : "secondary"}
          size="icon"
          className={cn(
            "absolute z-10 rounded-full",
            compact
              ? "top-1/2 right-1 h-6 w-6 -translate-y-1/2 focus-visible:opacity-100 md:opacity-0 md:group-hover/row:opacity-100"
              : "top-2 right-2 h-7 w-7 shadow-sm"
          )}
          onClick={onRemove}
          disabled={removing}
          aria-label={t("card.remove", { title })}
        >
          <X className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
        </Button>
      ) : null}
    </div>
  );
};
