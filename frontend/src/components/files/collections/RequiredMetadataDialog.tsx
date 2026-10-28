import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CollectionRead, PropertyValueInput } from "@/api/generated/initiativeAPI.schemas";
import {
  EMPTY_REQUIRED,
  missingIn,
  RequiredValues,
  valuesOf,
} from "@/components/layouts/RequiredValues";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { DialogProps } from "@/types/dialog";

/** Whether files going into the collection need values from whoever puts
 *  them there: its file page requires metadata it still has. */
export const asksForMetadata = (
  collection: Pick<CollectionRead, "metadata">,
  keys: readonly string[]
): boolean => missingIn(keys, EMPTY_REQUIRED, collection.metadata).length > 0;

/**
 * What a collection's file page requires of the files going in, asked once
 * for all of them: each of its metadata it requires, by the order the page
 * places them. Every file put in starts with these values.
 */
export const RequiredMetadataDialog = ({
  collection,
  keys,
  open,
  onOpenChange,
  onConfirm,
  pending = false,
}: DialogProps & {
  collection: Pick<CollectionRead, "name" | "initiative_id" | "metadata">;
  /** What the collection's file page requires (`requiredKeys`). */
  keys: readonly string[];
  onConfirm: (metadata: PropertyValueInput[]) => void;
  pending?: boolean;
}) => {
  const { t } = useTranslation(["files", "common"]);
  const [draft, setDraft] = useState(EMPTY_REQUIRED);
  useEffect(() => {
    if (!open) setDraft(EMPTY_REQUIRED);
  }, [open]);
  const missing = missingIn(keys, draft, collection.metadata);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("collections.required.title", { name: collection.name })}</DialogTitle>
          <DialogDescription>{t("collections.required.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RequiredValues
            keys={keys}
            definitions={collection.metadata}
            draft={draft}
            onChange={setDraft}
            initiativeId={collection.initiative_id}
            idPrefix="collection-required"
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            type="button"
            disabled={missing.length > 0 || pending}
            onClick={() => onConfirm(valuesOf(draft))}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {t("collections.required.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
