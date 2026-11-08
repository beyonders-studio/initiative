import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DecorationPack, UserRead } from "@/api/generated/initiativeAPI.schemas";
import { firstOfSlot, PackContentsDialog, packPieces } from "@/components/user/PackContents";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  useDecorationPacks,
  useInstallDecorationPack,
  useRemoveDecorationPack,
} from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { decorationSrc, resolveDecoration } from "@/lib/profileDecorations";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";

/**
 * One pack, shown as the profile it would make.
 *
 * The card is the profile page in miniature — the banner running, the frame
 * around the reader's own face, the trophy beside the name — because that is
 * the only question worth answering first: what would I look like wearing this.
 * A swatch grid could not answer it.
 *
 * It can only show one of each slot, though, and a pack can hold thirty-four
 * pieces. So the card is a button, and what it opens is the whole of it.
 *
 * A pack already downloaded keeps its card in the same place in the same grid,
 * and the card offers the way back out — you find a pack here, so this is where
 * you look to be rid of it.
 */
const PackCard = ({
  entry,
  user,
  busy,
  onInstall,
  onRemove,
}: {
  entry: DecorationPack;
  user: UserRead;
  busy: boolean;
  onInstall: () => void;
  onRemove: () => void;
}) => {
  const { t } = useTranslation("profiles");
  const [open, setOpen] = useState(false);
  const banner = firstOfSlot(entry.contents, "banner");
  const frameId = entry.contents.find((item) => item.kind === "frame")?.id ?? null;
  const trophy = firstOfSlot(entry.contents, "trophy");
  const count = packPieces(entry.contents).length;

  const get = (
    <Button size="sm" className="w-full" pending={busy} onClick={onInstall}>
      {t("store.get")}
    </Button>
  );
  const had = (
    <div className="flex items-center justify-between gap-3">
      <p className="flex min-w-0 items-center gap-1.5 font-medium text-sm">
        <Check className="size-4 shrink-0" aria-hidden="true" />
        <span className="truncate">{t("store.installed")}</span>
      </p>
      <Button
        variant="outline"
        size="sm"
        className="shrink-0"
        pending={busy}
        onClick={onRemove}
        // Every card's button says the same word; the name is what tells them
        // apart when the grid is read out.
        aria-label={t("myPacks.removeNamed", { name: entry.name })}
      >
        {t("myPacks.remove")}
      </Button>
    </div>
  );

  return (
    <li className="overflow-hidden rounded-lg border bg-card">
      {/* The preview is the button: a card that looks like a profile invites a
          click, and what it owes that click is the rest of the pack. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t("store.see", { name: entry.name })}
        className="block w-full text-left outline-none transition-colors hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div
          className="h-24 w-full bg-center bg-cover bg-muted"
          style={banner ? { backgroundImage: `url(${banner.src})` } : undefined}
        />
        <div className="space-y-2 p-4 pb-3">
          {/* Only the picture laps onto the banner. The name reads against the
              card, because a banner is a whole illustration and some of them
              are pale where the words would land. */}
          <div className="flex items-center gap-3">
            <ProfileAvatar
              user={user}
              decorations={{
                banner: null,
                frame_tint: [],
                frame: frameId,
                trophies: [],
                grad_year: null,
              }}
              className="-mt-14 size-16 shrink-0 rounded-full ring-4 ring-card"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <h3 className="truncate font-semibold">{entry.name}</h3>
                {trophy ? (
                  <img src={decorationSrc(trophy)} alt="" aria-hidden="true" className="size-7" />
                ) : null}
              </div>
              <p className="text-muted-foreground text-xs">{t("store.pieces", { count })}</p>
            </div>
          </div>
          <p className="text-muted-foreground text-sm">{entry.description}</p>
        </div>
      </button>
      <div className="px-4 pb-4">{entry.installed ? had : get}</div>
      <PackContentsDialog
        entry={entry}
        open={open}
        onOpenChange={setOpen}
        footer={entry.installed ? had : get}
      />
    </li>
  );
};

/**
 * The decoration store.
 *
 * Every pack this build ships, for getting one — and for giving one back. A
 * pack already downloaded is marked rather than offered again, and its card
 * carries the way out, so browsing is enough to change your mind. Removing is
 * asked about first, because the pieces go with it.
 *
 * What a pack contains and whether you have it is the server's answer; a pack
 * this build has no artwork for is left out rather than shown as an empty card.
 */
export const DecorationStore = ({ user }: { user: UserRead }) => {
  const { t } = useTranslation(["profiles", "common", "errors"]);
  const { data, isLoading } = useDecorationPacks();
  const [pending, setPending] = useState<DecorationPack | null>(null);

  const onError = (error: unknown) => toast.error(getErrorMessage(error, "profiles:store.failed"));
  const install = useInstallDecorationPack({
    onSuccess: () => toast.success(t("profiles:store.got")),
    onError,
  });
  const remove = useRemoveDecorationPack({
    onSuccess: () => {
      setPending(null);
      toast.success(t("profiles:myPacks.removed"));
    },
    onError: (error: unknown) => {
      setPending(null);
      onError(error);
    },
  });

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  // A pack whose pieces this build has no artwork for would be a card of
  // blanks; the catalog is shared across deployments and this one is not
  // obliged to have art for everything in it.
  const packs = (data?.items ?? []).filter((entry) =>
    entry.contents.some((item) =>
      resolveDecoration(item.id, item.kind as "banner" | "frame" | "trophy")
    )
  );

  if (packs.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("store.empty")}</p>;
  }

  return (
    <>
      <ul className="grid grid-cols-fill-64/3 gap-4">
        {packs.map((entry) => (
          <PackCard
            key={entry.uid}
            entry={entry}
            user={user}
            busy={
              (install.isPending && install.variables === entry.uid) ||
              (remove.isPending && remove.variables === entry.uid)
            }
            onInstall={() => install.mutate(entry.uid)}
            onRemove={() => setPending(entry)}
          />
        ))}
      </ul>

      <ConfirmDialog
        open={Boolean(pending)}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        destructive
        title={t("profiles:myPacks.confirmTitle", { name: pending?.name ?? "" })}
        description={t("profiles:myPacks.confirmBody")}
        confirmLabel={t("profiles:myPacks.remove")}
        loadingLabel={t("profiles:myPacks.removing")}
        isLoading={remove.isPending}
        onConfirm={() => {
          if (pending) remove.mutate(pending.uid);
        }}
      />
    </>
  );
};
