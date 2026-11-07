import { Clock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useListPasskeys } from "@/api/generated/auth/auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useApplyHeldChange, useCancelHeldChange, useHeldChange } from "@/hooks/useHeldChange";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { describePasskeyPromptError, passkeysRunHere } from "@/lib/passkeys";

/** What each waiting change will do, by the kind the server names. */
const CHANGE_KEYS = {
  primary: "heldChange.primary",
  remove_address: "heldChange.removeAddress",
  second_factor_off: "heldChange.secondFactorOff",
  last_passkey: "heldChange.lastPasskey",
} as const;

/**
 * The change this account has waiting, if any: what it will do and when,
 * with Cancel. An account with a passkey can make it now by signing in again
 * with one.
 */
export const HeldChangeNotice = () => {
  const { t } = useTranslation(["settings", "auth"]);
  const { stepUpWithPasskey } = useAuth();
  const { data: held } = useHeldChange();
  const passkeys = useListPasskeys();
  const [steppingUp, setSteppingUp] = useState(false);

  const cancel = useCancelHeldChange({
    onSuccess: () => toast.success(t("heldChange.cancelled")),
    onError: (error) => toast.error(getErrorMessage(error, "settings:heldChange.cancelFailed")),
  });
  const apply = useApplyHeldChange({
    onSuccess: () => toast.success(t("heldChange.applied")),
    onError: (error) => toast.error(getErrorMessage(error, "settings:heldChange.applyFailed")),
  });

  if (!held) return null;

  const makeNow = async () => {
    setSteppingUp(true);
    try {
      await stepUpWithPasskey();
    } catch (error) {
      const message = describePasskeyPromptError(error);
      if (message) toast.error(t(message));
      return;
    } finally {
      setSteppingUp(false);
    }
    apply.mutate(held.id);
  };

  const canMakeNow = passkeysRunHere() && (passkeys.data?.passkeys?.length ?? 0) > 0;
  const busy = steppingUp || cancel.isPending || apply.isPending;

  return (
    <Alert>
      <Clock className="h-4 w-4" />
      <AlertTitle>{t("heldChange.title")}</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>
          {t(CHANGE_KEYS[held.kind], {
            subject: held.subject ?? "",
            date: formatDateTime(held.applies_at),
          })}
        </p>
        <p className="text-muted-foreground">{t("heldChange.description")}</p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => cancel.mutate(held.id)}
          >
            {t("heldChange.cancel")}
          </Button>
          {canMakeNow ? (
            <Button size="sm" disabled={busy} onClick={() => void makeNow()}>
              {t("heldChange.applyNow")}
            </Button>
          ) : null}
        </div>
      </AlertDescription>
    </Alert>
  );
};
