import { Link } from "@tanstack/react-router";
import { BookText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool, type WikiSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";

interface WikiCardProps {
  wiki: WikiSummary;
  className?: string;
}

/**
 * One wiki in a list of them.
 *
 * Led by its name and what it covers rather than by a picture: a wiki is told
 * apart by its subject, and the one number worth showing from outside is how
 * many pages are in it — which is the difference between a handbook somebody
 * started and one the team actually keeps.
 */
export const WikiCard = ({ wiki, className }: WikiCardProps) => {
  const { t } = useTranslation("wikis");
  const gp = useCommunityPath();
  const relativeUpdatedAt = useRelativeTime(wiki.updated_at);
  const commentCount = wiki.comments_enabled ? (wiki.comment_count ?? 0) : null;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.wiki, wiki.initiative_id, wiki.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      {/* Short of the bookmark the list puts on the card's corner. */}
      <div className="flex items-start gap-3 p-4 pr-14">
        <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground transition group-hover:text-foreground">
          <BookText className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
            {wiki.name}
          </h3>
          {wiki.description ? (
            <p className="line-clamp-2 text-muted-foreground text-sm">{wiki.description}</p>
          ) : null}
          {commentCount !== null && commentCount > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
              <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
            </div>
          )}
          <p className="text-muted-foreground text-xs">
            {t("card.updated", { date: relativeUpdatedAt })}
          </p>
          <TagBadgeList
            tags={wiki.tags}
            tagHref={(tag) => gp(`/tags/${tag.id}`)}
            nested
            className="pt-1"
          />
        </div>
      </div>
    </Link>
  );
};
