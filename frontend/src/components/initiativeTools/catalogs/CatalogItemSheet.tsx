import { Download, Loader2, MoreHorizontal, Star, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useReadCatalogItem } from "@/api/generated/catalogs/catalogs";
import { type CatalogItemRead, TagTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { catalogItemSaves, useDeleteCatalogItem } from "@/hooks/useCatalogs";
import { usePendingShown } from "@/hooks/useFieldSave";
import { detailLayoutOf, instanceTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { imageLabel, imageSrc } from "@/lib/catalogs";
import { CATALOG_ITEM_DETAIL } from "@/lib/layouts/catalogItemLayout";
import { DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { usePluginMenuActions } from "@/lib/layouts/plugins";
import { toast } from "@/lib/mascotToast";

interface CatalogItemSheetProps {
  catalogId: number;
  /** The catalog's initiative — links are only made inside one. */
  initiativeId: number | null;
  image: CatalogItemRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  canDeleteVersions: boolean;
  /** Whether this reader moderates the catalog's initiative. */
  canModerate?: boolean;
  isCover: boolean;
  onSetCover: (imageId: number) => void;
  onRemoved: (imageId: number) => void;
}

/**
 * One picture, beside the wall it is on, drawn as its catalog lays its
 * pictures out, each field saved on its own.
 *
 * A side panel rather than a page: a picture has no address of its own.
 */
export const CatalogItemSheet = ({ image, ...props }: CatalogItemSheetProps) =>
  image ? <PictureSheet listed={image} {...props} /> : null;

const PictureSheet = ({
  catalogId,
  initiativeId,
  listed,
  open,
  onOpenChange,
  canEdit,
  canDeleteVersions,
  canModerate = false,
  isCover,
  onSetCover,
  onRemoved,
}: Omit<CatalogItemSheetProps, "image"> & { listed: CatalogItemRead }) => {
  const { t } = useTranslation(["catalogs", "common"]);
  const communityId = useActiveCommunityId();
  // The wall's picture is drawn until its own read, which also carries the
  // plug-ins' values, answers.
  const read = useReadCatalogItem(communityId, listed.id, {
    query: { placeholderData: listed, enabled: open },
  });
  const image = usePendingShown(catalogItemSaves(catalogId), listed.id, read.data) ?? listed;
  // A community's own catalog has no layouts of its own: it draws the shipped one.
  const layouts = useToolLayouts(
    open && initiativeId !== null ? instanceTarget(Tool.catalog, catalogId) : null
  );
  const pluginActions = usePluginMenuActions("catalog_item", image.id, initiativeId);
  const leaving = useRef(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const remove = useDeleteCatalogItem(catalogId, {
    onSuccess: (_, removedId) => {
      setConfirmRemove(false);
      leaving.current = true;
      onOpenChange(false);
      toast.success(t("sheet.removed"));
      onRemoved(removedId);
    },
  });

  const actions = (
    <div className="flex shrink-0 items-center gap-1">
      <ReportButton
        targetType={TagTarget.catalog_item}
        targetId={image.id}
        authorId={image.created_by}
      />
      {/* Taken down or held, the picture is gone from the wall, so the panel
          about it goes with it. */}
      <ModerationMenu
        targetType={TagTarget.catalog_item}
        targetId={image.id}
        canModerate={canModerate}
        communityId={image.community_id}
        onGone={() => {
          onOpenChange(false);
          onRemoved(image.id);
        }}
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={t("common:toolbar.moreActions")}
            aria-busy={remove.isPending}
          >
            {remove.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MoreHorizontal className="h-4 w-4" />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <a href={imageSrc(image)} download={image.original_filename ?? undefined}>
              <Download className="h-4 w-4" />
              {t("sheet.download")}
            </a>
          </DropdownMenuItem>
          {canEdit ? (
            <DropdownMenuItem disabled={isCover} onSelect={() => onSetCover(image.id)}>
              <Star className="h-4 w-4" />
              {isCover ? t("sheet.isCover") : t("sheet.setCover")}
            </DropdownMenuItem>
          ) : null}
          {pluginActions.items.length > 0 ? <DropdownMenuSeparator /> : null}
          {pluginActions.items}
          {canEdit ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => setConfirmRemove(true)}
              >
                <Trash2 className="h-4 w-4" />
                {t("sheet.remove")}
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-xl">
        <SheetTitle className="sr-only">
          {imageLabel(image) || t("common:lightbox.title")}
        </SheetTitle>
        <SheetDescription className="sr-only">{t("sheet.description")}</SheetDescription>
        <div className="py-4">
          <DetailLayoutView
            detail={CATALOG_ITEM_DETAIL}
            item={image}
            layout={detailLayoutOf(layouts.data, "catalog_item") as StoredRegions | null}
            context={{
              readOnly: !canEdit,
              catalogId,
              initiativeId,
              canDeleteVersions,
              leaving,
              actions,
            }}
          />
        </div>
        {pluginActions.dialog}
        <ConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title={t("sheet.removeTitle")}
          description={t("sheet.removeDescription")}
          confirmLabel={t("sheet.remove")}
          cancelLabel={t("common:cancel")}
          isLoading={remove.isPending}
          destructive
          onConfirm={() => remove.mutate(image.id)}
        />
      </SheetContent>
    </Sheet>
  );
};
