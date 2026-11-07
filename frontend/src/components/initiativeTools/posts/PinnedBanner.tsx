import { Pin } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PostRead } from "@/api/generated/initiativeAPI.schemas";
import { useSetPostPin } from "@/hooks/usePosts";
import { formatDateTime, fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { DateTimePicker } from "@/ui/date-time-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

interface PinnedBannerProps {
  post: PostRead;
  /** Whether this reader may pin — community admin or an initiative manager. */
  canPin?: boolean;
  className?: string;
}

/**
 * The line a pinned notice wears, and the way its end date is set.
 *
 * The end date lives here rather than on the pin button because this is the
 * sentence that describes it: pinning stays one click for the ordinary case,
 * and a manager who wants the pin to stop on Sunday says so next to the words
 * "Pinned to the top of this board".
 *
 * A dialog rather than a popover — the picker is itself a popover, and this
 * has to work on a phone, where a sheet-sized surface beats a floating one.
 */
export const PinnedBanner = ({ post, canPin = false, className }: PinnedBannerProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const [open, setOpen] = useState(false);
  const [expiresAt, setExpiresAt] = useState("");

  // Opening the dialog starts from what the pin actually says now, so a change
  // is an edit rather than a fresh answer.
  const [prev, setPrev] = useState({ open, expiresAt: post.pin_expires_at });
  if (prev.open !== open || prev.expiresAt !== post.pin_expires_at) {
    setPrev({ open, expiresAt: post.pin_expires_at });
    if (open) setExpiresAt(toLocalDateTimeInput(post.pin_expires_at));
  }

  const setPin = useSetPostPin(post.id, {
    onSuccess: () => {
      setOpen(false);
      toast.success(t("pin.pinnedToast"));
    },
  });

  if (!post.is_pinned) return null;

  const label = post.pin_expires_at
    ? t("pin.pinnedUntil", { date: formatDateTime(post.pin_expires_at) })
    : t("pin.pinnedBanner");

  return (
    <div
      className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-primary text-xs", className)}
    >
      <span className="inline-flex items-center gap-1.5">
        <Pin className="h-3.5 w-3.5" aria-hidden />
        {label}
      </span>
      {canPin && (
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          onClick={() => setOpen(true)}
        >
          {post.pin_expires_at ? t("pin.changeExpiry") : t("pin.addExpiry")}
        </Button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("pin.expiresLabel")}</DialogTitle>
            <DialogDescription>{t("pin.expiresHelp")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="pin-expires" className="sr-only">
              {t("pin.expiresLabel")}
            </Label>
            <DateTimePicker
              id="pin-expires"
              includeTime
              value={expiresAt}
              placeholder={t("pin.noExpiry")}
              onChange={setExpiresAt}
            />
          </div>

          <DialogFooter>
            {post.pin_expires_at && (
              <Button
                variant="ghost"
                disabled={setPin.isPending}
                onClick={() => setPin.mutate({ pinned: true, expires_at: null })}
              >
                {t("pin.removeExpiry")}
              </Button>
            )}
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              disabled={setPin.isPending || !expiresAt}
              onClick={() =>
                setPin.mutate({ pinned: true, expires_at: fromLocalDateTimeInput(expiresAt) })
              }
            >
              {t("common:save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
