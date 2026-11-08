import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { ItemDraftContext } from "@/hooks/useFieldSave";
import { type DetailKind, DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import { missingRequired, type StoredRegions } from "@/lib/layouts/detailLayout";
import type { LayoutNode } from "@/lib/layouts/tree";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

import { useItemDraft, type Written } from "./AddItemDialog";

type Item = { id: number; properties: PropertySummary[] };

type FillProps<I extends Item, C, P> = {
  detail: DetailKind<I, C, P>;
  /** The item as the change would leave it: of its new type, or in its new
   *  project. */
  item: I;
  context: C;
  /** The properties and metadata its new place offers; undefined until they
   *  are read. A required one among `keys` that is not among them was
   *  deleted, and is not asked for. */
  definitions: PropertyDefinitionRead[] | undefined;
  /** What its new page requires that it leaves empty, by `requiredKey`. */
  keys: readonly string[];
  /** What is being changed, as a heading. */
  title: string;
  /** Makes the change with what was filled in. */
  onConfirm: (written: Written<I, P>) => void;
  pending?: boolean;
};

/**
 * What a change of an item's type or place asks for first: the fields its new
 * page requires that it leaves empty, each drawn with its own editor and
 * nothing saved, then handed to `onConfirm` to send with the change.
 */
export const FillRequiredDialog = <I extends Item, C, P>({
  open,
  onOpenChange,
  ...props
}: DialogProps & FillProps<I, C, P>) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="@container sm:max-w-2xl">
      <Filling {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts afresh.
const Filling = <I extends Item, C, P>({
  detail,
  item: start,
  context,
  definitions,
  keys,
  title,
  onConfirm,
  pending = false,
}: FillProps<I, C, P>) => {
  const { t } = useTranslation(["common", "layouts"]);
  const { item, holding, latest, draft, written } = useItemDraft<I, P>(start, {
    onSubmit: () => confirm(),
  });
  const missingOf = (it: I) =>
    missingRequired(
      keys,
      (key) => detail.filled?.(it, key, latest.current.fields) ?? true,
      definitions
    );
  const missing = missingOf(item);
  const confirm = () => {
    if (pending || latest.current.holding.size > 0 || missingOf(latest.current.item).length > 0)
      return;
    onConfirm(written());
  };
  // Just the fields asked for, each marked, in one column.
  const layout: StoredRegions = {
    header: [],
    main: keys.map(
      (key): LayoutNode =>
        detail.spec.requiredParts?.has(key)
          ? { type: key, props: { required: true } }
          : { type: "field", props: { field: key, required: true } }
    ),
    side: [],
  };
  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{t("layouts:required.ask")}</DialogDescription>
      </DialogHeader>
      <ItemDraftContext.Provider value={draft}>
        <DetailLayoutView detail={detail} item={item} context={context} layout={layout} />
      </ItemDraftContext.Provider>
      <DialogFooter>
        <Button
          type="button"
          onClick={confirm}
          disabled={holding.size > 0 || missing.length > 0}
          pending={pending}
        >
          {t("layouts:required.confirm")}
        </Button>
      </DialogFooter>
    </>
  );
};
