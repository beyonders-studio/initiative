/**
 * The banner a home view wears, picked from the reader's own decoration
 * library — the same banners their profile picker offers — so each view can
 * look its own way. The choice is saved as it is made.
 */

import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { SlotPicker } from "@/components/user/DecorationPicker";
import { useAuth } from "@/hooks/useAuth";
import { useMyDecorations } from "@/hooks/useUsers";
import { resolveDecoration } from "@/lib/profileDecorations";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

export interface HomeBannerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string | null;
  onChange: (banner: string | null) => void;
}

export function HomeBannerDialog({ open, onOpenChange, value, onChange }: HomeBannerDialogProps) {
  const { t } = useTranslation(["home", "common"]);
  const { user } = useAuth();
  const library = useMyDecorations({ enabled: open });
  const owned = library.data?.items;
  // The shortcut is offered only while the profile's banner is one this build
  // draws and the reader still has it.
  const profileBanner = user?.profile_decorations?.banner ?? null;
  const canUseProfile =
    !!resolveDecoration(profileBanner, "banner") &&
    !!owned?.some((item) => item.kind === "banner" && item.id === profileBanner);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("banner.title")}</DialogTitle>
          <DialogDescription>{t("banner.description")}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {canUseProfile ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange(profileBanner)}
              disabled={value === profileBanner}
            >
              {t("banner.useProfile")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange(null)}
            disabled={value === null}
          >
            {t("banner.none")}
          </Button>
        </div>
        {/* Only an answer is shown as the library: while it is on its way, or
            if it could not be read, the picker would say there is nothing in
            it, which is not true. */}
        {library.isError ? (
          <StatusMessage onRetry={library.refetch} />
        ) : owned ? (
          <SlotPicker kind="banner" value={value} onChange={onChange} owned={owned} />
        ) : (
          <div className="grid grid-cols-fill-32/4 gap-2" aria-busy="true">
            {Array.from({ length: 4 }).map((_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
              <Skeleton key={i} className="h-16 rounded-md" />
            ))}
          </div>
        )}
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <Button asChild variant="link" className="h-auto p-0">
            <Link to="/marketplace" onClick={() => onOpenChange(false)}>
              {t("banner.more")}
            </Link>
          </Button>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("common:done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
