import { useState } from "react";

import type { PropertySummary } from "@/api/generated/initiativeAPI.schemas";
import type { Written } from "@/components/layouts/AddItemDialog";
import { FillRequiredDialog } from "@/components/layouts/FillRequiredDialog";
import { NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import type { DetailKind } from "@/lib/layouts/DetailLayoutView";

type Item = { id: number; properties: PropertySummary[] };

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
 * opens it, and `dialog` is drawn wherever the change is made from. The
 * dialog is given the definitions of the place the item is going to.
 */
export const useFillRequired = <I extends Item, C, P>(detail: DetailKind<I, C, P>) => {
  const [asking, setAsking] = useState<Asking<I, C, P> | null>(null);
  const [pending, setPending] = useState(false);
  const home = asking ? detail.home(asking.item, asking.context) : null;
  const definitions = useOwnedDefinitions({
    initiativeId: home?.initiativeId ?? undefined,
    owner: home?.owner,
    enabled: home !== null && home.initiativeId !== null,
  }).data;
  const dialog = asking ? (
    <FillRequiredDialog
      detail={detail}
      item={asking.item}
      context={asking.context}
      // Without an initiative, an item holds no properties.
      definitions={home?.initiativeId === null ? NO_DEFINITIONS : definitions}
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
