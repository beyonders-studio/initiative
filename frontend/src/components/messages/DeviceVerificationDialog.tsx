import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useVerification, useVerificationActions } from "@/hooks/useMyMessages";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

/**
 * A comparison between two of this account's devices, on whichever of them
 * this is: the one that started it from the new-device prompt, or the one it
 * arrived at. Mounted once for the whole app, so the device being verified
 * shows it wherever the person happens to be.
 *
 * The pictures are the text a person compares; the emoji is decoration, and a
 * screen reader reads the names in order, which is the same comparison.
 */
export const DeviceVerificationDialog = () => {
  const { t } = useTranslation(["messages", "common"]);
  const view = useVerification();
  const actions = useVerificationActions();

  if (view.phase === "idle") return null;
  const device = view.device.label ?? t("newDevice.unknownDevice");
  const running = view.phase === "waiting" || view.phase === "compare";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (open) return;
        if (running) actions.cancel.mutate();
        else actions.dismiss();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("verification.title", { device })}</DialogTitle>
          <DialogDescription>
            {view.phase === "waiting"
              ? t("verification.waiting")
              : view.phase === "compare"
                ? view.confirmed
                  ? t("verification.waitingForOther")
                  : t("verification.compare")
                : view.phase === "verified"
                  ? t("verification.verified")
                  : t(`verification.${view.reason}`)}
          </DialogDescription>
        </DialogHeader>

        {view.phase === "compare" ? (
          <ol className="flex justify-center gap-4 py-2" aria-label={t("verification.label")}>
            {view.emoji.map((entry, index) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: a code is a sequence, and the same picture can come up twice in it — position is the identity
                key={index}
                className="flex w-16 flex-col items-center gap-1"
              >
                <span className="text-4xl leading-none" aria-hidden>
                  {entry.emoji}
                </span>
                <span className="text-center text-muted-foreground text-xs leading-tight">
                  {t(`safetyEmoji.${entry.name}`)}
                </span>
              </li>
            ))}
          </ol>
        ) : view.phase === "verified" ? (
          <ShieldCheck className="mx-auto size-10 text-primary" aria-hidden />
        ) : view.phase === "failed" ? (
          <ShieldAlert className="mx-auto size-10 text-destructive" aria-hidden />
        ) : null}

        <DialogFooter>
          {view.phase === "compare" && !view.confirmed ? (
            <>
              <Button
                variant="outline"
                disabled={actions.reject.isPending}
                onClick={() => actions.reject.mutate()}
              >
                {t("verification.noMatch")}
              </Button>
              <Button disabled={actions.confirm.isPending} onClick={() => actions.confirm.mutate()}>
                {t("verification.match")}
              </Button>
            </>
          ) : running ? (
            <Button variant="outline" onClick={() => actions.cancel.mutate()}>
              {t("common:cancel")}
            </Button>
          ) : (
            <Button onClick={actions.dismiss}>{t("common:close")}</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
