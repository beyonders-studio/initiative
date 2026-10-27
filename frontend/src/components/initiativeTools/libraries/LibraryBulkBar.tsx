import { Loader2, Tags, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

interface LibraryBulkBarProps {
  count: number;
  /** How many pictures are on the wall right now — what "select all" takes. */
  total: number;
  onSelectAll: () => void;
  onClear: () => void;
  onEditTags: () => void;
  onDelete: () => void;
  deleting?: boolean;
  onExit: () => void;
}

/**
 * The bar above the wall while pictures are selected.
 *
 * Two actions, because two are what a selection of pictures is for: tag them
 * — "these forty are the rejected round" — and remove them. Both are the
 * library's write gate, which is the one the wall already asked for.
 */
export const LibraryBulkBar = ({
  count,
  total,
  onSelectAll,
  onClear,
  onEditTags,
  onDelete,
  deleting = false,
  onExit,
}: LibraryBulkBarProps) => {
  const { t } = useTranslation(["libraries", "common"]);
  const allSelected = count > 0 && count >= total;

  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary bg-primary/5 p-3 backdrop-blur">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium text-sm">{t("bulk.selected", { count })}</span>
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0"
          onClick={allSelected ? onClear : onSelectAll}
        >
          {allSelected ? t("bulk.clear") : t("bulk.selectAll", { count: total })}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" disabled={count === 0} onClick={onEditTags}>
          <Tags className="size-4" />
          {t("bulk.editTags")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="text-destructive"
          disabled={count === 0 || deleting}
          onClick={onDelete}
        >
          {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
          {t("bulk.delete")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onExit}>
          {t("common:cancel")}
        </Button>
      </div>
    </div>
  );
};
