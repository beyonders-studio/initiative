import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertySummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ItemDraftContext } from "@/hooks/useFieldSave";
import { useOwnedDefinitions } from "@/hooks/useProperties";
import { type DetailKind, DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import { missingRequired, type StoredRegions } from "@/lib/layouts/detailLayout";
import type { LayoutNode } from "@/lib/layouts/tree";
import type { DialogProps } from "@/types/dialog";

import { useItemDraft, type Written } from "./AddItemDialog";

type Item = { id: number; properties: PropertySummary[] };

type FillProps<I extends Item, C, P> = {
  detail: DetailKind<I, C, P>;
  /** The item as the change would leave it: of its new type, or in its new
   *  project. */
  item: I;
  context: C;
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
    <DialogContent className="@container w-full sm:max-w-2xl">
      <Filling {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts afresh.
const Filling = <I extends Item, C, P>({
  detail,
  item: start,
  context,
  keys,
  title,
  onConfirm,
  pending = false,
}: FillProps<I, C, P>) => {
  const { t } = useTranslation(["common", "layouts"]);
  const { item, holding, latest, draft, written } = useItemDraft<I, P>(start, {
    onSubmit: () => confirm(),
  });
  const home = detail.home(item, context);
  const definitions = useOwnedDefinitions({
    initiativeId: home.initiativeId ?? undefined,
    owner: home.owner,
    enabled: home.initiativeId !== null,
  }).data;
  const missingOf = (it: I) =>
    missingRequired(
      keys,
      (key) => detail.filled?.(it, key, latest.current.fields) ?? true,
      home.initiativeId === null ? [] : definitions
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
          disabled={pending || holding.size > 0 || missing.length > 0}
        >
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {t("layouts:required.confirm")}
        </Button>
      </DialogFooter>
    </>
  );
};

/** A change waiting on what its item's new page requires. */
export interface Asking<I, C, P> {
  item: I;
  context: C;
  keys: readonly string[];
  title: string;
  /** Makes the change with what was filled in; a failure keeps the dialog. */
  send: (written: Written<I, P>) => Promise<unknown>;
}

/**
 * Asks, for a change of an item of `detail`'s kind, for the fields its new
 * page requires that it leaves empty, then makes the change with them: `ask`
 * opens it, and `dialog` is drawn wherever the change is made from.
 */
export const useFillRequired = <I extends Item, C, P>(detail: DetailKind<I, C, P>) => {
  const [asking, setAsking] = useState<Asking<I, C, P> | null>(null);
  const [pending, setPending] = useState(false);
  const dialog = asking ? (
    <FillRequiredDialog
      detail={detail}
      item={asking.item}
      context={asking.context}
      keys={asking.keys}
      title={asking.title}
      open
      onOpenChange={(open) => {
        if (!open) setAsking(null);
      }}
      pending={pending}
      onConfirm={async (written) => {
        setPending(true);
        try {
          await asking.send(written);
          setAsking(null);
        } catch {
          // What failed has said so; what was filled in is still here.
        } finally {
          setPending(false);
        }
      }}
    />
  ) : null;
  return { ask: setAsking, dialog };
};
