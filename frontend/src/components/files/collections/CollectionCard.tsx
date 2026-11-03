import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { CollectionRead } from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { COLLECTION_ICON } from "@/lib/collections";
import { useCommunityPath } from "@/lib/communityUrl";
import { fileIcon } from "@/lib/fileIcon";
import { collectionRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface CollectionCardProps {
  collection: CollectionRead;
  className?: string;
}

/**
 * One collection in a strip of them.
 *
 * Led by its cover — the file somebody chose, or the newest one the reader can
 * open — because a list of collections should itself be visual: "Store
 * assets" and "Live screen, round 4" are told apart by what is in them long
 * before by their names. The count is of the files the reader can open.
 */
export const CollectionCard = ({ collection, className }: CollectionCardProps) => {
  const { t } = useTranslation("files");
  const gp = useCommunityPath();
  const cover = collection.cover;
  // Its thumbnail, as every file's card shows; a picture itself until that
  // is drawn.
  const picture =
    cover?.thumbnail_url ??
    (cover?.file_content_type?.startsWith("image/") ? cover.file_url : null);
  const { Icon, colorClass } = cover
    ? fileIcon({ file_type: cover.file_type })
    : { Icon: COLLECTION_ICON, colorClass: "text-muted-foreground" };
  const commentCount = collection.comments_enabled ? collection.comment_count : 0;

  return (
    <Link
      to={gp(collectionRoute(collection.initiative_id, collection.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <div className="relative aspect-4/3 overflow-hidden border-b bg-muted">
        {picture ? (
          <LazyImage
            src={resolveUploadUrl(picture)}
            alt=""
            className="h-full w-full"
            imgClassName="transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Icon className={cn("h-10 w-10 sm:h-16 sm:w-16", colorClass)} aria-hidden />
          </div>
        )}
        {commentCount > 0 ? (
          <Badge variant="secondary" className="absolute right-2 bottom-2">
            {t("card.comments", { count: commentCount })}
          </Badge>
        ) : null}
      </div>
      <div className="space-y-1 p-4">
        <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
          {collection.name}
        </h3>
        <p className="text-muted-foreground text-xs">
          {t("collections.fileCount", { count: collection.file_count })}
        </p>
        <TagBadgeList
          tags={collection.tags}
          tagHref={(tag) => gp(`/tags/${tag.id}`)}
          nested
          className="pt-1"
        />
      </div>
    </Link>
  );
};
