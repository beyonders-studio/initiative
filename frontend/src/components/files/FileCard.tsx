import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { FileKind, type FileSummary, FileType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { LazyImage } from "@/components/shared/LazyImage";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useCommunityPath } from "@/lib/communityUrl";
import { fileIcon } from "@/lib/fileIcon";
import { isStoredFileType } from "@/lib/fileTypes";
import { getFileTypeLabel } from "@/lib/fileUtils";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";
import { toolDetailRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface FileCardProps {
  file: FileSummary;
  className?: string;
}

export const FileCard = ({ file, className }: FileCardProps) => {
  const { t } = useTranslation("files");
  const relativeUpdatedAt = useRelativeTime(file.updated_at);
  const gp = useCommunityPath();
  // A file with comments off shows no thread anywhere, so it shows no count.
  const commentCount = file.comments_enabled ? (file.comment_count ?? 0) : null;
  const isUploadedFile = isStoredFileType(file.file_type);
  const fileTypeLabel = isUploadedFile
    ? getFileTypeLabel(file.file_content_type, file.original_filename)
    : null;

  // The mark this file draws, by what sort of file it is — shared with
  // the relations card so the two cannot drift apart.
  const { Icon: FileIcon, colorClass: fileIconColor } = fileIcon({
    file_type: file.file_type,
    smart_link_url: file.smart_link_url,
  });
  // A picture is shown as itself; any other file by its featured image.
  const picture = file.kind === FileKind.image ? file.file_url : file.featured_image_url;
  const smartLinkMatch =
    file.file_type === FileType.url && file.smart_link_url
      ? matchSmartLinkProvider(file.smart_link_url)
      : null;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.file, file.initiative_id, file.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
      // style={{ aspectRatio: "2 / 3" }}
    >
      {/* Squarer thumbnails cost a phone most of a card each while showing, for
          the usual file, one centred icon. Shorter below `sm`. */}
      <div className="relative aspect-4/3 overflow-hidden border-b bg-muted sm:aspect-square">
        {picture ? (
          <LazyImage
            src={resolveUploadUrl(picture)}
            alt=""
            className="h-full w-full"
            imgClassName="transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <FileIcon
              className={cn(
                "h-10 w-10 sm:h-20 sm:w-20 md:h-24 md:w-24 lg:h-28 lg:w-28",
                fileIconColor
              )}
            />
          </div>
        )}
        <div className="absolute right-2 bottom-2 flex flex-col items-end gap-1 text-muted-foreground text-xs">
          {isUploadedFile && fileTypeLabel ? (
            <Badge variant="secondary">{fileTypeLabel}</Badge>
          ) : null}
          {file.file_type === FileType.excalidraw ? (
            <Badge variant="secondary">{t("card.whiteboardLabel")}</Badge>
          ) : null}
          {file.file_type === FileType.sheet ? (
            <Badge variant="secondary">{t("card.spreadsheetLabel")}</Badge>
          ) : null}
          {smartLinkMatch ? <Badge variant="secondary">{smartLinkMatch.label}</Badge> : null}
          {file.is_template ? <Badge variant="outline">{t("card.template")}</Badge> : null}
          {commentCount !== null && (
            <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
          )}
        </div>
      </div>
      <div className="flex h-full flex-col gap-3 p-4">
        <div className="space-y-1">
          {/* The unread mark is the list's to draw, on the card's corner. */}
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
                  {file.name}
                </h3>
              </TooltipTrigger>
              <TooltipContent side="top" align="start">
                <p>{file.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <p className="text-muted-foreground text-xs">
            {t("card.updated", { date: relativeUpdatedAt })}
          </p>
          <TagBadgeList tags={file.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
          {(() => {
            const propertyChips = nonEmptyPropertySummaries(file.properties);
            if (propertyChips.length === 0) return null;
            return (
              <div className="flex flex-wrap gap-1">
                {propertyChips.map((summary) => (
                  <PropertyValueCell
                    key={summary.property_id}
                    summary={summary}
                    variant="chip"
                    nested
                  />
                ))}
              </div>
            );
          })()}
        </div>
      </div>
    </Link>
  );
};
