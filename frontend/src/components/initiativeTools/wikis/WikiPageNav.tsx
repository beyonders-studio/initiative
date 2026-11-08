import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { WikiPageKind } from "@/api/generated/initiativeAPI.schemas";
import { useWikiPages } from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { wikiFileRoute, wikiPageRoute } from "@/lib/tools";
import { cn } from "@/ui/lib/utils";

interface WikiPageNavProps {
  wikiId: number;
  initiativeId: number;
  /** The row being read — its id, and which kind of row it is. */
  currentId: number;
  currentKind?: WikiPageKind;
  className?: string;
}

/**
 * The way on, at the foot of a page.
 *
 * A wiki is written to be read through, not only searched, so the end of a page
 * says what comes next — in the wiki's own reading order, which is the order the
 * navigation draws: each page, then what is filed under it. A page filed inside
 * another is simply the next one; the order is a walk of the tree, not of the
 * top level.
 *
 * Both neighbours are named rather than labelled "previous" and "next" alone:
 * the title is what tells somebody whether to keep going.
 */
export const WikiPageNav = ({
  wikiId,
  initiativeId,
  currentId,
  currentKind = WikiPageKind.page,
  className,
}: WikiPageNavProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useCommunityPath();
  const { data } = useWikiPages(Number.isFinite(wikiId) ? wikiId : null);

  const items = data?.items ?? [];
  const here = items.findIndex((row) => row.id === currentId && row.kind === currentKind);
  if (here < 0) return null;

  const previous = items[here - 1];
  const next = items[here + 1];
  // The only page in the wiki: there is nowhere to go, so nothing is offered.
  if (!previous && !next) return null;

  const hrefOf = (row: (typeof items)[number]) =>
    gp(
      row.kind === WikiPageKind.file
        ? wikiFileRoute(initiativeId, wikiId, row.id)
        : wikiPageRoute(initiativeId, wikiId, row.id)
    );

  return (
    <nav
      aria-label={t("pages.nav")}
      className={cn("mt-10 flex items-stretch gap-3 border-t pt-4", className)}
    >
      {previous ? (
        <Link
          to={hrefOf(previous)}
          className="group flex min-w-0 flex-1 items-center gap-2 rounded-md border p-3 hover:bg-accent"
        >
          <ChevronLeft className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-muted-foreground text-xs">{t("common:previous")}</span>
            <span className="block truncate font-medium text-sm">
              {previous.title || t("common:untitled")}
            </span>
          </span>
        </Link>
      ) : (
        // Held open, so the way on does not slide across the screen when there
        // is nothing behind you.
        <span className="hidden flex-1 sm:block" />
      )}

      {next ? (
        <Link
          to={hrefOf(next)}
          className="group flex min-w-0 flex-1 items-center gap-2 rounded-md border p-3 text-right hover:bg-accent"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-muted-foreground text-xs">{t("common:next")}</span>
            <span className="block truncate font-medium text-sm">
              {next.title || t("common:untitled")}
            </span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </Link>
      ) : (
        <span className="hidden flex-1 sm:block" />
      )}
    </nav>
  );
};
