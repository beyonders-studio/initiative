import { type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GetLayoutsParams } from "@/api/generated/initiativeAPI.schemas";
import { useOwnedDefinitions } from "@/hooks/useProperties";
import { useSetItemLinks } from "@/hooks/useRelationships";
import { useToolLayouts } from "@/hooks/useToolLayouts";
import { AddingLinks, type InitiativeDetail } from "@/lib/layouts/initiativeExtension";
import type { LinkedRef } from "@/lib/relationships";
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
import { type DetailItem, DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import { missingRequired, requiredKeys, type StoredRegions } from "@/ui/layouts/detailLayout";
import { ItemDraftContext, useItemDraft, type Written } from "@/ui/layouts/editing";
import { detailLayoutOf } from "@/ui/layouts/layoutSet";
import { cn } from "@/ui/lib/utils";

type AddItemProps<I extends DetailItem, C, P, R extends { id: number }> = {
  detail: InitiativeDetail<I, C, P>;
  /** The item as it starts, before anything is changed. */
  blank: I;
  context: C;
  /** Where its kind's layout is kept, given the item as it stands (an event's
   *  is its calendar's initiative's); none draws it as shipped. */
  layouts: (item: I) => GetLayoutsParams | null;
  /** Drawn above its layout, given the item: what it is added to, where
   *  that is picked here. */
  before?: (item: I) => ReactNode;
  /** The dialog's title, and what its button says. */
  title: string;
  /** Whether it can be added as it stands: it has a name. What its layout
   *  requires is asked here as well. */
  ready: (item: I) => boolean;
  /** Makes it from what was changed, answering it. */
  create: (written: Written<I, P>) => Promise<R>;
  /** Once it is made, and its links with it. */
  onAdded: (made: R) => void;
};

/**
 * Adding an item, drawn as its kind's layout lays it out with each field's own
 * editor. Nothing is saved until Add, which makes it from everything changed
 * and then writes the links picked; closing the dialog drops it all.
 */
export const AddItemDialog = <I extends DetailItem, C, P, R extends { id: number }>({
  open,
  onOpenChange,
  ...props
}: DialogProps & AddItemProps<I, C, P, R>) => {
  // Once something is changed, a stray click outside does not drop it; Esc
  // and the close button still do.
  const changed = useRef(false);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Its own container, so the detail's columns follow the dialog's
          width rather than the screen's, as they follow the page area's on
          the item's own page. */}
      <DialogContent
        className={cn(
          "@container",
          // One column needs no room for a second.
          props.detail.addingUpFront ? "sm:max-w-2xl" : "sm:max-w-5xl"
        )}
        onInteractOutside={(event) => {
          if (changed.current) event.preventDefault();
        }}
        // Escape in a field with a list open under it closes the list.
        onEscapeKeyDown={(event) => {
          if ((event.target as Element | null)?.closest?.("[data-picking]")) {
            event.preventDefault();
          }
        }}
      >
        <Adding {...props} changed={changed} />
      </DialogContent>
    </Dialog>
  );
};

// Drawn only while the dialog is open, so each opening starts blank.
const Adding = <I extends DetailItem, C, P, R extends { id: number }>({
  detail,
  blank,
  context,
  layouts,
  before,
  title,
  ready,
  create,
  onAdded,
  changed,
}: AddItemProps<I, C, P, R> & { changed: RefObject<boolean> }) => {
  const { t } = useTranslation(["common", "layouts"]);
  const [links, setLinks] = useState<LinkedRef[]>([]);
  const [adding, setAdding] = useState(false);
  const { item, holding, latest, draft, written } = useItemDraft<I, P>(blank, {
    onEdit: () => {
      changed.current = true;
    },
    onSubmit: () => void submit.current(),
  });
  const laidOut = useToolLayouts(layouts(item));
  const layout = detailLayoutOf(laidOut.data, detail.spec.kind, detail.typed?.typeOf(item));
  const home = detail.home(item, context);
  const definitions = useOwnedDefinitions({
    initiativeId: home.initiativeId ?? undefined,
    owner: home.owner,
    enabled: home.initiativeId !== null,
  }).data;
  // What its layout requires that it leaves empty, which Add waits for.
  const missingOf = (it: I) =>
    missingRequired(
      requiredKeys(layout as StoredRegions | null),
      (key) => detail.filled?.(it, key, latest.current.fields) ?? true,
      home.initiativeId === null ? [] : definitions
    );
  const missing = missingOf(item);
  const target = home.links.target;
  const setLinksOn = useSetItemLinks(home.canOpen.tool, home.canOpen.id);
  // The item this sitting made, whose links did not all land: Add again
  // finishes it rather than making a second. And the links last asked for,
  // which a retry writes against.
  const made = useRef<R | null>(null);
  const asked = useRef<LinkedRef[]>([]);

  const finish = async (item: R) => {
    if (target && (links.length > 0 || asked.current.length > 0)) {
      const previous = asked.current;
      asked.current = links;
      await setLinksOn.mutateAsync({
        item: { type: target.type, id: item.id },
        links,
        previous,
        force: previous.length > 0,
      });
    }
    onAdded(item);
  };

  const add = async () => {
    const { item: now, holding: held } = latest.current;
    if (adding || held.size > 0 || !ready(now) || laidOut.isLoading || missingOf(now).length > 0)
      return;
    setAdding(true);
    try {
      if (made.current === null) {
        // A new item was written over nothing, so it names no base.
        const { fields, ...rest } = written();
        made.current = await create({
          ...rest,
          fields: Object.fromEntries(
            Object.entries(fields).filter(([key]) => !key.endsWith("_base"))
          ) as Partial<P>,
        });
      }
      await finish(made.current);
    } catch {
      // What failed has said so; everything changed is still here to try again.
    } finally {
      setAdding(false);
    }
  };
  const submit = useRef(add);
  submit.current = add;

  useEffect(() => {
    changed.current = false;
  }, [changed]);
  const picking = useMemo(
    () => ({
      value: links,
      onChange: (next: LinkedRef[]) => {
        changed.current = true;
        setLinks(next);
      },
    }),
    [links, changed]
  );

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription className="sr-only">{title}</DialogDescription>
      </DialogHeader>
      <ItemDraftContext.Provider value={draft}>
        {before?.(item)}
        <AddingLinks.Provider value={picking}>
          <DetailLayoutView
            detail={detail}
            item={item}
            context={context}
            layout={layout as StoredRegions | null}
          />
        </AddingLinks.Provider>
      </ItemDraftContext.Provider>
      <DialogFooter className="items-center">
        {missing.length > 0 ? (
          <p className="text-muted-foreground text-xs">{t("layouts:required.toAdd")}</p>
        ) : null}
        <Button
          type="button"
          onClick={() => void add()}
          disabled={
            holding.size > 0 ||
            !ready(item) ||
            // Until its layout is read, what it requires is not known.
            laidOut.isLoading ||
            missing.length > 0
          }
          pending={adding}
        >
          {adding ? t("adding") : title}
        </Button>
      </DialogFooter>
    </>
  );
};
