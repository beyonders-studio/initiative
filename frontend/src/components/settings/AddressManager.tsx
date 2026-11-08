import { Mail, Star, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { UserEmailRead } from "@/api/generated/initiativeAPI.schemas";
import {
  isOnlyProvenAddress,
  useAddAddress,
  useMakeAddressPrimary,
  useMyAddresses,
  useRemoveAddress,
  visibleAddresses,
} from "@/hooks/useAddresses";
import { isHeld, useAnnounceHeld } from "@/hooks/useHeldChange";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

/** A change to the list waiting on its confirmation. */
type Change =
  | { kind: "add"; email: string }
  | { kind: "primary"; address: UserEmailRead }
  | { kind: "remove"; address: UserEmailRead };

/**
 * The addresses an account holds.
 *
 * An account has several, any proven one signs in, and account mail reaches
 * all of them — so this is a list rather than a field. The primary is the one
 * shown back to a community.
 *
 * Changing the list changes how the account is signed into, so each change is
 * confirmed with the current password where the server asks for one. Where it
 * does not, the change goes straight through and a recent sign-in answers; the
 * step-up dialog opens if the one in hand is too old.
 */
export const AddressManager = () => {
  const { t } = useTranslation(["settings", "errors", "common"]);
  const [pending, setPending] = useState("");
  const [change, setChange] = useState<Change | null>(null);
  const [password, setPassword] = useState("");
  const [changeError, setChangeError] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useMyAddresses();
  const announceHeld = useAnnounceHeld();
  const addresses = visibleAddresses(data);
  // Asking is the safe guess while the answer is still on its way.
  const passwordRequired = data?.password_required ?? true;

  const closeChange = () => {
    setChange(null);
    setPassword("");
    setChangeError(null);
  };

  // A refusal inside the dialog is said there, so a mistyped password can be
  // corrected without starting over.
  const refuse = (error: unknown, fallbackKey: string) => {
    const message = getErrorMessage(error, fallbackKey);
    if (change) setChangeError(message);
    else toast.error(message);
  };

  const addAddress = useAddAddress({
    onSuccess: () => {
      setPending("");
      closeChange();
      // One message whatever happened at the other end. Somebody may already
      // hold this address, in which case the letter went to them and nothing
      // was recorded here; the reader is told what to do next either way.
      toast.success(t("settings:addresses.checkYourMail"));
    },
    onError: (error) => refuse(error, "settings:addresses.addFailed"),
  });

  const removeAddress = useRemoveAddress({
    onSuccess: (result) => {
      closeChange();
      if (result.held) announceHeld(result.held);
      else toast.success(t("settings:addresses.removed"));
    },
    onError: (error) => refuse(error, "settings:addresses.removeFailed"),
  });

  const makePrimary = useMakeAddressPrimary({
    onSuccess: (result) => {
      closeChange();
      if (isHeld(result)) announceHeld(result);
      else toast.success(t("settings:addresses.primaryChanged"));
    },
    onError: (error) => refuse(error, "settings:addresses.primaryFailed"),
  });

  const apply = (target: Change, currentPassword: string | null) => {
    if (target.kind === "add") addAddress.mutate({ email: target.email, currentPassword });
    else if (target.kind === "primary")
      makePrimary.mutate({ addressId: target.address.id, currentPassword });
    else removeAddress.mutate({ addressId: target.address.id, currentPassword });
  };

  // Removing is confirmed either way; the others only when there is a
  // password to type.
  const begin = (target: Change) => {
    setPassword("");
    setChangeError(null);
    if (passwordRequired || target.kind === "remove") setChange(target);
    else apply(target, null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const email = pending.trim();
    if (email) begin({ kind: "add", email });
  };

  const confirm = (event: FormEvent) => {
    event.preventDefault();
    if (change) apply(change, passwordRequired ? password : null);
  };

  const confirming = addAddress.isPending || makePrimary.isPending || removeAddress.isPending;
  const changeEmail = change?.kind === "add" ? change.email : (change?.address.email ?? "");

  return (
    <div className="space-y-4">
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : isError ? (
        // Said, not drawn as an empty list. A request that did not arrive and
        // an account holding nothing render the same way otherwise, and the
        // second is alarming on the page that says how you get in.
        <StatusMessage onRetry={refetch} />
      ) : (
        <ul className="space-y-2">
          {addresses.map((address) => {
            const lastProven = isOnlyProvenAddress(address, addresses);
            return (
              <li
                key={address.id}
                className="flex flex-wrap items-center gap-2 rounded-md border p-3"
              >
                <Mail className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">{address.email}</span>
                {address.is_primary && <Badge>{t("settings:addresses.primary")}</Badge>}
                {!address.verified && (
                  <Badge variant="secondary">{t("settings:addresses.unverified")}</Badge>
                )}
                {/* Only a proven address can take account mail, so promoting an
                    unproven one is not offered. */}
                {!address.is_primary && address.verified && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => begin({ kind: "primary", address })}
                    disabled={makePrimary.isPending}
                  >
                    <Star className="size-4" aria-hidden />
                    {t("settings:addresses.makePrimary")}
                  </Button>
                )}
                {/* The primary goes by being replaced, and the last proven
                    address does not go at all. */}
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("settings:addresses.removeLabel", {
                    email: address.email,
                  })}
                  onClick={() => begin({ kind: "remove", address })}
                  disabled={address.is_primary || lastProven}
                  title={
                    address.is_primary
                      ? t("settings:addresses.primaryCannotBeRemoved")
                      : lastProven
                        ? t("settings:addresses.lastCannotBeRemoved")
                        : undefined
                  }
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <form onSubmit={submit}>
        <Field label={t("settings:addresses.addLabel")} hint={t("settings:addresses.addHelp")}>
          <div className="flex flex-wrap gap-2">
            <Input
              type="email"
              className="min-w-48 flex-1"
              value={pending}
              onChange={(event) => setPending(event.target.value)}
              placeholder={t("settings:addresses.addPlaceholder")}
              autoComplete="email"
            />
            <Button type="submit" disabled={!pending.trim() || addAddress.isPending}>
              {t("settings:addresses.addAction")}
            </Button>
          </div>
        </Field>
      </form>

      <Dialog open={change !== null} onOpenChange={(open) => !open && closeChange()}>
        <DialogContent>
          <form className="space-y-4" onSubmit={confirm}>
            <DialogHeader>
              <DialogTitle>
                {change ? t(`settings:addresses.${change.kind}DialogTitle`) : null}
              </DialogTitle>
              <DialogDescription>
                {change ? (
                  <Trans
                    i18nKey={`addresses.${change.kind}DialogDescription`}
                    ns="settings"
                    values={{ email: changeEmail }}
                    components={{ strong: <strong /> }}
                  />
                ) : null}
              </DialogDescription>
            </DialogHeader>
            {passwordRequired ? (
              <Field label={t("settings:addresses.passwordLabel")}>
                <Input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </Field>
            ) : null}
            {changeError ? <p className="text-destructive text-sm">{changeError}</p> : null}
            <DialogFooter
              submitLabel={change ? t(`settings:addresses.${change.kind}Confirm`) : null}
              pending={confirming}
            />
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};
