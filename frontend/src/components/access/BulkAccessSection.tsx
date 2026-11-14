import { Copy, Shield, Tags, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { FileType, TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type BulkAccessItem,
  BulkEditAccessDialog,
} from "@/components/access/BulkEditAccessDialog";
import { BulkExportButton } from "@/components/exports/BulkExportButton";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useDeleteTools, useDuplicateTools } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { toast } from "@/lib/mascotToast";
import { everyCan } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { SelectionBar } from "@/ui/selection-bar";

/** The slice of {@link useGridSelection} this section drives. */
interface GridSelectionLike<T> {
  active: boolean;
  selectedItems: T[];
  exit: () => void;
}

/** A selected row, as the bulk actions read it. */
type BulkItem = BulkAccessItem & {
  tags?: TagSummary[] | null;
  /** A file's type, which decides the formats it exports to. */
  file_type?: FileType;
};

interface BulkAccessSectionProps<T extends BulkItem> {
  /** The grid selection driving this page's cards. Its state stays on the page. */
  selection: GridSelectionLike<T>;
  /** The tool being listed — routes every bulk endpoint. */
  tool: Tool;
  /** Invalidate the tool's list caches after a successful change. */
  invalidate: () => void;
  /** The page's own actions, before the shared ones. */
  actions?: ReactNode;
}

/**
 * The bulk toolbar shared by the tool-list pages, shown while items are
 * selected: export, tags, duplicate, delete and access, each offered only when
 * the viewer may do it to every selected item. An archived item's sharing
 * cannot change, so a selection holding one says so. Entering selection mode
 * is the toolbar's overflow menu's job, so this renders nothing at all until
 * something is selected.
 */
export function BulkAccessSection<T extends BulkItem>({
  selection,
  tool,
  invalidate,
  actions,
}: BulkAccessSectionProps<T>) {
  const { t } = useTranslation(["access", "common"]);
  const communityId = useActiveCommunityId();
  const [accessOpen, setAccessOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const items = selection.selectedItems;
  const count = items.length;
  const archived = items.some((item) => item.archived_at);
  // Duplicating and tagging both ask for edit on every selected item.
  const canEdit = everyCan(items, "edit");
  const canDelete = everyCan(items, "delete");
  const canShare = everyCan(items, "share");
  // Read is enough to copy a template; anything else needs edit.
  const canDuplicate = count > 0 && items.every((item) => item.is_template || item.can.edit);

  const duplicate = useDuplicateTools(tool, {
    onSuccess: (copies) => {
      toast.success(t("common:bulkActions.duplicated", { count: copies.length }));
      selection.exit();
    },
  });
  const remove = useDeleteTools(tool, {
    onSuccess: (_, ids) => {
      toast.success(t("common:bulkActions.deleted", { count: ids.length }));
      selection.exit();
    },
  });

  return (
    <>
      {selection.active ? (
        <SelectionBar label={t("bulkBar.selected", { count })}>
          {actions}
          <BulkExportButton tool={tool} items={items} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setTagsOpen(true)}
            disabled={count === 0 || !canEdit}
            title={count > 0 && !canEdit ? t("common:bulkActions.needEdit") : undefined}
          >
            <Tags className="h-4 w-4" />
            {t("common:bulkActions.editTags")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => duplicate.mutate(items.map((item) => item.id))}
            pending={duplicate.isPending}
            disabled={!canDuplicate}
            title={count > 0 && !canDuplicate ? t("common:bulkActions.needEdit") : undefined}
          >
            <Copy className="h-4 w-4" />
            {t("common:bulkActions.duplicate")}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            pending={remove.isPending}
            disabled={count === 0 || !canDelete}
            title={count > 0 && !canDelete ? t("common:bulkActions.needDelete") : undefined}
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="h-4 w-4" />
            {t("common:delete")}
          </Button>
          <ConfirmDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            title={t("common:bulkActions.deleteConfirm", { count })}
            confirmLabel={t("common:delete")}
            destructive
            onConfirm={() => remove.mutate(items.map((item) => item.id))}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAccessOpen(true)}
            disabled={count === 0 || !canShare}
            title={
              count > 0 && !canShare
                ? t(archived ? "bulkBar.archived" : "bulkBar.needManage")
                : undefined
            }
          >
            <Shield className="h-4 w-4" />
            {t("bulkBar.editAccess")}
          </Button>
          <Button variant="ghost" size="sm" onClick={selection.exit}>
            {t("common:cancel")}
          </Button>
        </SelectionBar>
      ) : null}
      <BulkEditTagsDialog
        open={tagsOpen}
        onOpenChange={setTagsOpen}
        items={items}
        targetType={tool}
        communityId={communityId}
        onInvalidate={invalidate}
        onSuccess={selection.exit}
      />
      <BulkEditAccessDialog
        open={accessOpen}
        onOpenChange={setAccessOpen}
        items={items}
        resourceType={tool}
        invalidate={invalidate}
        onSuccess={selection.exit}
      />
    </>
  );
}
