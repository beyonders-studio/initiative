import { type CatalogItemRead, TagTarget } from "@/api/generated/initiativeAPI.schemas";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { invalidateImages } from "@/hooks/useCatalogs";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditImageTagsDialogProps extends DialogWithSuccessProps {
  catalogId: number;
  images: CatalogItemRead[];
}

/** Tagging a selection of pictures — the shared bulk-tag dialog, pointed at
 *  the catalog-item target and this catalog's caches. */
export function BulkEditImageTagsDialog({
  catalogId,
  images,
  ...dialogProps
}: BulkEditImageTagsDialogProps) {
  const communityId = useActiveCommunityId();

  return (
    <BulkEditTagsDialog
      {...dialogProps}
      items={images}
      targetType={TagTarget.catalog_item}
      communityId={communityId}
      onInvalidate={() => void invalidateImages(catalogId)}
    />
  );
}
