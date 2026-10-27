import { type LibraryItemRead, TagTarget } from "@/api/generated/initiativeAPI.schemas";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { invalidateImages } from "@/hooks/useLibraries";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditImageTagsDialogProps extends DialogWithSuccessProps {
  libraryId: number;
  images: LibraryItemRead[];
}

/** Tagging a selection of pictures — the shared bulk-tag dialog, pointed at
 *  the library-item target and this library's caches. */
export function BulkEditImageTagsDialog({
  libraryId,
  images,
  ...dialogProps
}: BulkEditImageTagsDialogProps) {
  const communityId = useActiveCommunityId();

  return (
    <BulkEditTagsDialog
      {...dialogProps}
      items={images}
      targetType={TagTarget.library_item}
      communityId={communityId}
      onInvalidate={() => void invalidateImages(libraryId)}
    />
  );
}
