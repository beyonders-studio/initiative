import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import type { PropertyDefinition } from "@/ui/properties/propertyHelpers";

import { type DetailItem, type DetailKind, DetailLayoutView } from "./DetailLayoutView";
import { missingRequired, type StoredRegions } from "./detailLayout";
import { ItemDraftContext, useItemDraft, type Written } from "./editing";
import type { LayoutNode } from "./tree";

type FillProps<I extends DetailItem, C, P> = {
  detail: DetailKind<I, C, P, object, PropertyDefinition>;
  /** The item as the change would leave it: of its new type, or in its new
   *  project. */
  item: I;
  context: C;
  /** The properties and metadata its new place offers; undefined until they
   *  are read. A required one among `keys` that is not among them was
   *  deleted, and is not asked for. */
  definitions: PropertyDefinition[] | undefined;
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
export const FillRequiredDialog = <I extends DetailItem, C, P>({
  open,
  onOpenChange,
  ...props
}: { open: boolean; onOpenChange: (open: boolean) => void } & FillProps<I, C, P>) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="@container sm:max-w-2xl">
      <Filling {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts afresh.
const Filling = <I extends DetailItem, C, P>({
  detail,
  item: start,
  context,
  definitions,
  keys,
  title,
  onConfirm,
  pending = false,
}: FillProps<I, C, P>) => {
  const { t } = useTranslation("layouts");
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
        <DialogDescription>{t("required.ask")}</DialogDescription>
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
          {t("required.confirm")}
        </Button>
      </DialogFooter>
    </>
  );
};
