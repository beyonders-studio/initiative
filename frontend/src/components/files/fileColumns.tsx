import { FileSpreadsheet, FileText, Presentation } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { FileKind, type FileSummary } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { isStoredFileType } from "@/lib/fileTypes";
import { getFileTypeLabel } from "@/lib/fileUtils";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

/** What kind of file it is: its stored format, or a template or a file of the
 *  app's own. */
export const FileTypeBadge = ({ file }: { file: FileSummary }) => {
  const { t } = useTranslation("files");
  if (isStoredFileType(file.file_type)) {
    const fileTypeLabel = getFileTypeLabel(file.file_content_type, file.original_filename);
    const Icon =
      file.kind === FileKind.spreadsheet
        ? FileSpreadsheet
        : file.kind === FileKind.presentation
          ? Presentation
          : FileText;
    return (
      <Badge variant="secondary" className="flex w-fit items-center gap-1">
        <Icon className="h-3 w-3" />
        {fileTypeLabel}
      </Badge>
    );
  }
  return file.is_template ? (
    <Badge variant="outline">{t("type.template")}</Badge>
  ) : (
    <span className="text-muted-foreground">{t("type.file")}</span>
  );
};

/** What the files table shows beside the columns every tool's table has:
 *  its owner and its type. */
export const useFileColumns = (): AppColumnDef<FileSummary>[] => {
  const { t } = useTranslation("files");

  return useMemo<AppColumnDef<FileSummary>[]>(
    () => [
      {
        id: "owner",
        header: t("columns.owner"),
        cell: ({ row }) => {
          // An installed plug-in owns what it made; its name is the owner's name.
          if (row.original.owner_plugin) {
            return <span>{row.original.owner_plugin.name}</span>;
          }
          const ownerGrant = (row.original.grants ?? []).find((g) => g.level === "owner");
          if (!ownerGrant || ownerGrant.user_id == null) {
            return <span className="text-muted-foreground">—</span>;
          }
          const ownerName = row.original.owner ? getUserDisplayName(row.original.owner) : undefined;
          return <span>{ownerName || t("columns.ownerFallback", { id: ownerGrant.user_id })}</span>;
        },
      },
      {
        id: "type",
        header: t("columns.type"),
        cell: ({ row }) => <FileTypeBadge file={row.original} />,
      },
    ],
    [t]
  );
};

/** The fields a collection's table also sorts by: when each file was made,
 *  and when it was added to the collection. */
export const COLLECTION_SORT_FIELDS: ReadonlySet<string> = new Set(["created_at", "added_at"]);
