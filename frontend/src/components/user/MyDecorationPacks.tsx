import { Loader2, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DecorationPack, OwnedDecoration } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { DecorationSwatch } from "@/components/user/DecorationSwatch";
import { PackContentsDialog, packPieces } from "@/components/user/PackContents";
import { useDecorationPacks, useRemoveDecorationPack } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { type Decoration, resolveDecoration } from "@/lib/profileDecorations";

/** Above this many, finding one by eye stops working and the filter appears. */
const FILTER_THRESHOLD = 8;

/** One of each slot, for the row's thumbnail strip. The rest is a click away. */
const pieces = (contents: OwnedDecoration[]): Decoration[] =>
  (["banner", "frame", "trophy"] as const)
    .map((kind) => resolveDecoration(contents.find((item) => item.kind === kind)?.id, kind))
    .filter((decoration): decoration is Decoration => Boolean(decoration));

/** One row: what the pack gave you, its name, and the way out. */
const PackRow = ({
  entry,
  busy,
  onRemove,
}: {
  entry: DecorationPack;
  busy: boolean;
  onRemove: () => void;
}) => {
  const { t } = useTranslation("profiles");
  const [open, setOpen] = useState(false);
  const count = packPieces(entry.contents).length;
  return (
    <li className="flex items-center gap-3 px-3 py-2">
      {/* The pieces at a glance. Small on purpose: this is a list you scan for
          one name, not a catalog — the catalog is the marketplace. */}
      <ul className="flex shrink-0 items-center gap-2">
        {pieces(entry.contents).map((decoration) => (
          <li key={decoration.id} className="flex size-8 items-center justify-center">
            <DecorationSwatch
              decoration={decoration}
              className={decoration.kind === "banner" ? "h-8 w-12" : "size-8"}
            />
            <span className="sr-only">{t(decoration.labelKey)}</span>
          </li>
        ))}
      </ul>
      {/* The name opens the whole pack: a row can show three pieces and some
          of these hold thirty. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t("store.see", { name: entry.name })}
        className="min-w-0 flex-1 truncate rounded-sm text-left font-medium text-sm hover:underline focus-visible:outline-2 focus-visible:outline-ring"
      >
        {entry.name}
        <span className="ml-2 font-normal text-muted-foreground text-xs">
          {t("store.pieces", { count })}
        </span>
      </button>
      <PackContentsDialog entry={entry} open={open} onOpenChange={setOpen} />
      <Button
        variant="destructive"
        size="sm"
        className="shrink-0"
        disabled={busy}
        onClick={onRemove}
        // Every row's button says the same three words; in a list this long the
        // name is the only thing that tells them apart when they are read out.
        aria-label={t("myPacks.removeNamed", { name: entry.name })}
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
        {t("myPacks.remove")}
      </Button>
    </li>
  );
};

/**
 * The packs this account has downloaded: what is in each one, and the way out.
 *
 * A row per pack rather than a card per pack, because this list only grows —
 * someone who collects packs the way people collect them will have hundreds,
 * and a wall of cards would bury the tab it lives on. Rows are a fixed height,
 * the list scrolls in place, and a filter appears once scanning by eye stops
 * being realistic.
 *
 * Removing is here too, and on the card in the marketplace: whichever of the
 * two you happen to be looking at is the one that should be able to do it.
 */
export const MyDecorationPacks = () => {
  const { t } = useTranslation(["profiles", "common"]);
  const { data, isLoading } = useDecorationPacks();
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<DecorationPack | null>(null);

  const remove = useRemoveDecorationPack({
    onSuccess: () => {
      setPending(null);
      toast.success(t("profiles:myPacks.removed"));
    },
    onError: (error: unknown) => {
      setPending(null);
      toast.error(getErrorMessage(error, "profiles:store.failed"));
    },
  });

  const owned = useMemo(
    () => (data?.items ?? []).filter((entry) => entry.installed),
    [data?.items]
  );
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return owned;
    return owned.filter((entry) => entry.name.toLowerCase().includes(needle));
  }, [owned, query]);

  if (isLoading) {
    return (
      <div className="flex h-24 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  if (owned.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("profiles:myPacks.empty")}</p>;
  }

  return (
    <div className="space-y-3">
      {owned.length > FILTER_THRESHOLD ? (
        <div className="relative">
          <Search
            className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("profiles:myPacks.filter", { count: owned.length })}
            aria-label={t("profiles:myPacks.filterLabel")}
            className="pl-9"
          />
        </div>
      ) : null}

      {shown.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("profiles:myPacks.noMatch")}</p>
      ) : (
        <ul className="max-h-96 divide-y overflow-y-auto rounded-lg border">
          {shown.map((entry) => (
            <PackRow
              key={entry.uid}
              entry={entry}
              busy={remove.isPending && remove.variables === entry.uid}
              onRemove={() => setPending(entry)}
            />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={Boolean(pending)}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        destructive
        title={t("profiles:myPacks.confirmTitle", { name: pending?.name ?? "" })}
        description={t("profiles:myPacks.confirmBody")}
        confirmLabel={t("profiles:myPacks.remove")}
        cancelLabel={t("common:cancel")}
        loadingLabel={t("profiles:myPacks.removing")}
        isLoading={remove.isPending}
        onConfirm={() => {
          if (pending) remove.mutate(pending.uid);
        }}
      />
    </div>
  );
};
