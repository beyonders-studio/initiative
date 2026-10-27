import { Link } from "@tanstack/react-router";
import { Images } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  type LibraryCover,
  type LibrarySummary,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface LibraryCardProps {
  library: LibrarySummary;
  className?: string;
}

/**
 * One library in a list of them.
 *
 * Led by its cover — the picture somebody chose, or the newest one — because
 * a list of libraries should itself be visual: "Store assets" and "Live
 * screen, round 4" are told apart by what is in them long before by their
 * names. A library with nothing in it yet shows the tool's icon instead.
 */
export const LibraryCard = ({ library, className }: LibraryCardProps) => {
  const { t } = useTranslation("libraries");
  const gp = useCommunityPath();
  const relativeUpdatedAt = useRelativeTime(library.updated_at);
  // The chosen cover stands alone. Without one, the newest few as a small
  // grid: a wall of forty says what it is better than any one of them would.
  const cover = library.cover;
  const preview = cover ? [cover] : library.preview;
  const srcOf = (picture: LibraryCover) =>
    resolveUploadUrl(picture.thumbnail_url ?? picture.file_url);
  const commentCount = library.comments_enabled ? (library.comment_count ?? 0) : null;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.library, library.initiative_id, library.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <div className="relative aspect-4/3 overflow-hidden border-b bg-muted">
        {preview.length === 1 ? (
          <LazyImage
            src={srcOf(preview[0])}
            alt=""
            className="h-full w-full"
            imgClassName="transition duration-300 group-hover:scale-105"
          />
        ) : preview.length > 1 ? (
          <div
            className={cn(
              "grid h-full w-full gap-0.5",
              preview.length === 2 ? "grid-cols-2" : "grid-cols-2 grid-rows-2"
            )}
          >
            {preview.map((picture, index) => (
              <LazyImage
                key={picture.item_id}
                src={srcOf(picture)}
                alt=""
                // Three pictures: the first takes the whole left column.
                className={cn("h-full w-full", preview.length === 3 && index === 0 && "row-span-2")}
                imgClassName="transition duration-300 group-hover:scale-105"
              />
            ))}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Images className="h-10 w-10 text-muted-foreground sm:h-16 sm:w-16" />
          </div>
        )}
        <div className="absolute right-2 bottom-2 flex flex-col items-end gap-1 text-xs">
          {commentCount !== null && commentCount > 0 && (
            <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
          )}
        </div>
      </div>
      <div className="space-y-1 p-4">
        <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
          {library.name}
        </h3>
        {library.description ? (
          <p className="line-clamp-2 text-muted-foreground text-sm">{library.description}</p>
        ) : null}
        <p className="text-muted-foreground text-xs">
          {t("card.updated", { date: relativeUpdatedAt })}
        </p>
        <TagBadgeList
          tags={library.tags}
          tagHref={(tag) => gp(`/tags/${tag.id}`)}
          nested
          className="pt-1"
        />
      </div>
    </Link>
  );
};
