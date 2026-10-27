import { FileSpreadsheet, FileText, Presentation } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type CollectionFileSummary,
  FileKind,
  type FileSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { SortHeader } from "@/components/SortIcon";
import { Badge } from "@/components/ui/badge";
import { RelativeTime } from "@/components/ui/relative-time";
import { isStoredFileType } from "@/lib/fileTypes";
import { getFileTypeLabel } from "@/lib/fileUtils";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

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
        cell: ({ row }) => {
          const doc = row.original;
          if (isStoredFileType(doc.file_type)) {
            const fileTypeLabel = getFileTypeLabel(doc.file_content_type, doc.original_filename);
            const Icon =
              doc.kind === FileKind.spreadsheet
                ? FileSpreadsheet
                : doc.kind === FileKind.presentation
                  ? Presentation
                  : FileText;
            return (
              <Badge variant="secondary" className="flex w-fit items-center gap-1">
                <Icon className="h-3 w-3" />
                {fileTypeLabel}
              </Badge>
            );
          }
          return doc.is_template ? (
            <Badge variant="outline">{t("type.template")}</Badge>
          ) : (
            <span className="text-muted-foreground">{t("type.file")}</span>
          );
        },
      },
    ],
    [t]
  );
};

/** The fields a collection's table also sorts by: when each file was made,
 *  and when it was added to the collection. */
export const COLLECTION_SORT_FIELDS: ReadonlySet<string> = new Set(["created_at", "added_at"]);

/** A collection's table: the files table's columns, and when each file was
 *  made and added to the collection. */
export const useCollectionFileColumns = (): AppColumnDef<CollectionFileSummary>[] => {
  const { t } = useTranslation("files");
  const fileColumns = useFileColumns() as AppColumnDef<CollectionFileSummary>[];

  return useMemo<AppColumnDef<CollectionFileSummary>[]>(
    () => [
      ...fileColumns,
      ...(["created_at", "added_at"] as const).map(
        (field): AppColumnDef<CollectionFileSummary> => ({
          id: field,
          accessorKey: field,
          header: ({ column }) => (
            <SortHeader
              column={column}
              label={t(field === "added_at" ? "columns.added" : "columns.created")}
            />
          ),
          cell: ({ row }) => (
            <RelativeTime date={row.original[field]} className="text-muted-foreground" />
          ),
          enableSorting: true,
        })
      ),
    ],
    [fileColumns, t]
  );
};
