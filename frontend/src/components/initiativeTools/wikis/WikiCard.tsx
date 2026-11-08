import { BookText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool, type WikiSummary } from "@/api/generated/initiativeAPI.schemas";
import { ToolCard } from "@/components/tools/ToolCard";
import { toolDetailRoute } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";

/**
 * One wiki in a list of them.
 *
 * Led by its name and what it covers rather than by a picture: a wiki is told
 * apart by its subject, and the one number worth showing from outside is how
 * many pages are in it — which is the difference between a handbook somebody
 * started and one the team actually keeps.
 */
export const WikiCard = ({ wiki }: { wiki: WikiSummary }) => {
  const { t } = useTranslation("wikis");
  const relativeUpdatedAt = useRelativeTime(wiki.updated_at);
  const commentCount = wiki.comments_enabled ? (wiki.comment_count ?? 0) : null;

  return (
    <ToolCard
      to={toolDetailRoute(Tool.wiki, wiki.initiative_id, wiki.id)}
      name={wiki.name}
      description={wiki.description}
      tags={wiki.tags}
      mark={
        <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground transition group-hover:text-foreground">
          <BookText className="size-5" aria-hidden />
        </span>
      }
    >
      {commentCount !== null && commentCount > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
        </div>
      )}
      <p className="text-muted-foreground text-xs">
        {t("card.updated", { date: relativeUpdatedAt })}
      </p>
    </ToolCard>
  );
};
