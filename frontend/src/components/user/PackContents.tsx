import { useTranslation } from "react-i18next";

import type { DecorationPack, OwnedDecoration } from "@/api/generated/initiativeAPI.schemas";
import { DecorationSwatch } from "@/components/user/DecorationSwatch";
import { type Decoration, type DecorationKind, resolveDecoration } from "@/lib/profileDecorations";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";

/** The slots, in the order a profile wears them. */
const SLOTS = ["banner", "frame", "trophy"] as const;

/**
 * Everything in a pack this build can draw, in slot order.
 *
 * A pack is not three things any more — one of them carries thirty-two flags —
 * so this returns all of them rather than the first of each. Anything this
 * deployment has no artwork for is left out: the catalog is shared across
 * deployments and this one is not obliged to have a picture for everything in
 * it.
 */
export const packPieces = (contents: OwnedDecoration[]): Decoration[] =>
  SLOTS.flatMap((kind) =>
    contents
      .filter((item) => item.kind === kind)
      .map((item) => resolveDecoration(item.id, kind))
      .filter((decoration): decoration is Decoration => Boolean(decoration))
  );

/** The first of a slot, for a card that has room to show one of each. */
export const firstOfSlot = (contents: OwnedDecoration[], kind: DecorationKind) =>
  resolveDecoration(contents.find((item) => item.kind === kind)?.id, kind);

/**
 * What a pack carries, in full.
 *
 * The card outside can only show one of each slot, which stopped being the
 * whole story the moment a pack could hold thirty-four pieces. This is where
 * the rest of it is: every piece, grouped by the slot it goes in, drawn at the
 * size that slot is worn at and named.
 */
export const PackContentsDialog = ({
  entry,
  open,
  onOpenChange,
  footer,
}: {
  entry: DecorationPack;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whatever the surface that opened this does about the pack. */
  footer?: React.ReactNode;
}) => {
  const { t } = useTranslation("profiles");
  const pieces = packPieces(entry.contents);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{entry.name}</DialogTitle>
          <DialogDescription>{entry.description}</DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-xs">
          {t("store.by", { publisher: entry.publisher })}
        </p>
        <div className="space-y-5">
          {SLOTS.map((kind) => {
            const ofKind = pieces.filter((piece) => piece.kind === kind);
            if (ofKind.length === 0) return null;
            return (
              <section key={kind} className="space-y-2">
                <h3 className="font-medium text-muted-foreground text-xs">
                  {t(`decorationPicker.${kind}`)} · {ofKind.length}
                </h3>
                <ul
                  className={
                    kind === "banner"
                      ? "grid grid-cols-pair gap-2"
                      : "flex flex-wrap gap-x-3 gap-y-3"
                  }
                >
                  {ofKind.map((piece) => (
                    <li
                      key={piece.id}
                      className={kind === "banner" ? "space-y-1" : "w-16 space-y-1 text-center"}
                    >
                      <DecorationSwatch
                        decoration={piece}
                        className={kind === "banner" ? "h-14 w-full" : "size-12"}
                      />
                      <span className="block truncate text-muted-foreground text-xs">
                        {t(piece.labelKey)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
        {footer ? <div className="pt-2">{footer}</div> : null}
      </DialogContent>
    </Dialog>
  );
};
