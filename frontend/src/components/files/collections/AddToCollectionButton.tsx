import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { AddToCollectionDialog } from "@/components/files/collections/AddToCollectionDialog";
import { Button } from "@/components/ui/button";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { COLLECTION_ICON } from "@/lib/collections";

interface AddToCollectionButtonProps {
  initiativeId: number;
  fileIds: number[];
  /** Called once the files are in. */
  onDone?: () => void;
}

/**
 * "Add to collection", for whoever's role creates files in the initiative —
 * the right that changes its collections, as the server says. Nothing for
 * anyone else.
 */
export const AddToCollectionButton = ({
  initiativeId,
  fileIds,
  onDone,
}: AddToCollectionButtonProps) => {
  const { t } = useTranslation("files");
  const [open, setOpen] = useState(false);
  const { canCreate } = useToolCreateAccess(Tool.file, { initiativeId });
  if (!canCreate) return null;

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={fileIds.length === 0}
        onClick={() => setOpen(true)}
      >
        <COLLECTION_ICON className="h-4 w-4" />
        {t("collections.addTo")}
      </Button>
      <AddToCollectionDialog
        initiativeId={initiativeId}
        fileIds={fileIds}
        open={open}
        onOpenChange={setOpen}
        onDone={onDone}
      />
    </>
  );
};
