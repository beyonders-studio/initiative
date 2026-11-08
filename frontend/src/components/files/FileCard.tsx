import { useTranslation } from "react-i18next";

import { type FileSummary, FileType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { ToolCard } from "@/components/tools/ToolCard";
import { fileIcon } from "@/lib/fileIcon";
import { isStoredFileType } from "@/lib/fileTypes";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";
import { toolDetailRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { Badge } from "@/ui/badge";
import { LazyImage } from "@/ui/lazy-image";
import { filePicture, getFileTypeLabel } from "@/ui/lib/fileUtils";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";

export const FileCard = ({ file }: { file: FileSummary }) => {
  const { t } = useTranslation("files");
  const relativeUpdatedAt = useRelativeTime(file.updated_at);
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
  const picture = filePicture(file);
  const smartLinkMatch =
    file.file_type === FileType.url && file.smart_link_url
      ? matchSmartLinkProvider(file.smart_link_url)
      : null;
  const propertyChips = nonEmptyPropertySummaries(file.properties);

  return (
    <ToolCard
      to={toolDetailRoute(Tool.file, file.initiative_id, file.id)}
      name={file.name}
      tags={file.tags}
      preview={
        // Squarer thumbnails cost a phone most of a card each while showing,
        // for the usual file, one centred icon. Shorter below `sm`.
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
      }
    >
      <p className="text-muted-foreground text-xs">
        {t("card.updated", { date: relativeUpdatedAt })}
      </p>
      {propertyChips.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {propertyChips.map((summary) => (
            <PropertyValueCell key={summary.property_id} summary={summary} variant="chip" nested />
          ))}
        </div>
      ) : null}
    </ToolCard>
  );
};
