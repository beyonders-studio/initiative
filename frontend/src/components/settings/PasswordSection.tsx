import { useState } from "react";
import { useTranslation } from "react-i18next";

import { setAuthToken } from "@/api/client";
import {
  getListPasskeysQueryKey,
  getReadSecondFactorQueryKey,
  useListPasskeys,
  useRemovePassword,
} from "@/api/generated/auth/auth";
import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { NewPasswordFields } from "@/components/auth/NewPasswordFields";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useServer } from "@/hooks/useServer";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { checkNewPassword } from "@/lib/passwordPolicy";
import { queryClient } from "@/lib/queryClient";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

interface PasswordSectionProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * The account's password: set a first one, change it, or give it up.
 *
 * Left out entirely where this deployment signs nobody in with a password.
 */
export const PasswordSection = ({ user, refreshUser }: PasswordSectionProps) => {
  // Pull in ``auth`` and ``errors`` so the password-policy hint and the
  // server's ``PASSWORD_BREACHED`` code map without lazy-loading those
  // namespaces mid-submit.
  const { t } = useTranslation(["settings", "auth", "errors", "common"]);
  const { isNativePlatform } = useServer();
  const { passwordLoginEnabled } = useAppConfig();
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [removeOpen, setRemoveOpen] = useState(false);
  const [removeCurrentPassword, setRemoveCurrentPassword] = useState("");
  const [removeCodes, setRemoveCodes] = useState<string[] | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const updateAccount = useUpdateCurrentUser({
    onSuccess: async (_data, variables) => {
      // A password change rotates token_version server-side and re-sets the
      // session cookie. On web the stale in-memory bearer would otherwise still
      // be sent and 401 us out, so drop it and let the fresh cookie carry the
      // session. (Native has no cookie to fall back on, so it re-authenticates
      // instead — left as-is.)
      if (variables.password && !isNativePlatform) {
        setAuthToken(null);
      }
      setPassword("");
      setCurrentPassword("");
      setConfirmPassword("");
      setError(null);
      await refreshUser();
      toast.success(t("account.passwordSaved"));
    },
    onError: (err: unknown) => {
      // Map server password-policy codes (``PASSWORD_TOO_SHORT``,
      // ``PASSWORD_BREACHED``) and other backend errors via the shared
      // helper; fall back to the generic update-error string.
      setError(getErrorMessage(err, "settings:profile.updateError"));
    },
  });

  // Giving the password up is a browser errand — the server takes it there and
  // not from the app. An account that holds no password has nothing to give up
  // either.
  const offersRemoval = passwordLoginEnabled && user.has_password && !isNativePlatform;
  // What else the account could sign in with, asked for only where the offer
  // stands.
  const passkeys = useListPasskeys({
    query: { enabled: offersRemoval },
  });
  const canRemovePassword =
    offersRemoval &&
    (passkeys.data?.offered ?? false) &&
    (passkeys.data?.passkeys?.length ?? 0) > 0;

  const closeRemove = () => {
    setRemoveOpen(false);
    // The codes are readable here and nowhere the page can reach again.
    setRemoveCurrentPassword("");
    setRemoveCodes(null);
    setRemoveError(null);
  };

  const removePassword = useRemovePassword({
    mutation: {
      onSuccess: async (data) => {
        setRemoveError(null);
        setRemoveCurrentPassword("");
        // A set arrives only where the account held none, and this is the one
        // place it is ever readable. It goes on screen before anything that
        // can fail runs, and stays there whatever the rest of this does.
        const issued = data.codes.length > 0;
        if (issued) {
          setRemoveCodes(data.codes);
        }
        // This device is carried over on fresh cookies; the in-memory bearer
        // that was minted with the old ones is not the one to send.
        if (!isNativePlatform) {
          setAuthToken(null);
        }
        void queryClient.invalidateQueries({
          queryKey: getReadSecondFactorQueryKey(),
        });
        void queryClient.invalidateQueries({
          queryKey: getListPasskeysQueryKey(),
        });
        try {
          await refreshUser();
        } catch {
          // The page holds a stale copy of the account for a moment. The codes
          // above are what this dialog is for, so they stay put.
        }
        if (issued) {
          return;
        }
        toast.success(t("account.passwordRemoved"));
        closeRemove();
      },
      onError: (err) =>
        setRemoveError(getErrorMessage(err, "settings:account.removePasswordError")),
    },
  });

  if (!passwordLoginEnabled) {
    return null;
  }

  const resetPasswordFields = () => {
    setPassword("");
    setCurrentPassword("");
    setConfirmPassword("");
    setError(null);
  };

  const passwordReady =
    password.length > 0 && confirmPassword.length > 0 && (!user.has_password || !!currentPassword);

  return (
    <>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (user.has_password && !currentPassword) {
            setError(t("profile.currentPasswordRequired"));
            return;
          }
          const passwordError = checkNewPassword(password, confirmPassword);
          if (passwordError) {
            setError(passwordError);
            return;
          }
          const payload: UserSelfUpdate = { password };
          // Changing a password asks for the one being replaced. An account
          // that holds none is setting a first one.
          if (user.has_password) {
            payload.current_password = currentPassword;
          }
          updateAccount.mutate(payload);
        }}
      >
        <SettingsSection
          title={user.has_password ? t("account.passwordTitle") : t("account.setPasswordTitle")}
          description={
            user.has_password
              ? t("account.passwordDescription")
              : t("account.setPasswordDescription")
          }
          footer={
            <>
              <Button type="submit" disabled={!passwordReady || updateAccount.isPending}>
                {updateAccount.isPending
                  ? t("profile.saving")
                  : user.has_password
                    ? t("account.changePassword")
                    : t("account.setPasswordTitle")}
              </Button>
              {password || currentPassword || confirmPassword ? (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={updateAccount.isPending}
                  onClick={resetPasswordFields}
                >
                  {t("common:cancel")}
                </Button>
              ) : null}
            </>
          }
        >
          {user.has_password ? (
            <div className="space-y-2 sm:max-w-sm">
              <Label htmlFor="current-password">{t("profile.currentPasswordLabel")}</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </div>
          ) : null}

          <div className="grid grid-cols-pair gap-4">
            <NewPasswordFields
              id="password"
              label={t("profile.newPasswordLabel")}
              password={password}
              confirm={confirmPassword}
              onPasswordChange={setPassword}
              onConfirmChange={setConfirmPassword}
            />
          </div>

          {error ? <p className="text-destructive text-sm">{error}</p> : null}

          {user.has_password && isNativePlatform ? (
            <p className="border-t pt-4 text-muted-foreground text-sm">
              {t("account.removePasswordFromBrowser")}
            </p>
          ) : null}

          {canRemovePassword ? (
            <div className="border-t pt-4">
              <Button
                type="button"
                variant="outline"
                className="border-destructive/50 text-destructive hover:bg-destructive/10"
                onClick={() => {
                  setRemoveError(null);
                  setRemoveCurrentPassword("");
                  setRemoveCodes(null);
                  setRemoveOpen(true);
                }}
              >
                {t("account.removePassword")}
              </Button>
            </div>
          ) : null}
        </SettingsSection>
      </form>

      <Dialog
        open={removeOpen}
        onOpenChange={(open) => (open ? setRemoveOpen(true) : closeRemove())}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("account.removePasswordTitle")}</DialogTitle>
            <DialogDescription>{t("account.removePasswordBody")}</DialogDescription>
          </DialogHeader>
          {removeCodes ? (
            <RecoveryCodesPanel
              codes={removeCodes}
              note={t("account.removePasswordCodes")}
              onDone={closeRemove}
            />
          ) : (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                removePassword.mutate({
                  data: { current_password: removeCurrentPassword || null },
                });
              }}
            >
              {/* Where the password is not asked for, a recent sign-in answers
                  instead, and the dialog that asks for one is raised on
                  refusal. */}
              {user.password_required ? (
                <div className="space-y-2">
                  <Label htmlFor="remove-current-password">
                    {t("profile.currentPasswordLabel")}
                  </Label>
                  <Input
                    id="remove-current-password"
                    type="password"
                    autoComplete="current-password"
                    value={removeCurrentPassword}
                    onChange={(event) => setRemoveCurrentPassword(event.target.value)}
                    required
                  />
                </div>
              ) : null}
              {removeError ? <p className="text-destructive text-sm">{removeError}</p> : null}
              <DialogFooter className="gap-2">
                <Button type="button" variant="outline" onClick={closeRemove}>
                  {t("common:cancel")}
                </Button>
                <Button
                  type="submit"
                  variant="destructive"
                  disabled={
                    removePassword.isPending || (user.password_required && !removeCurrentPassword)
                  }
                >
                  {t("account.removePassword")}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
};
