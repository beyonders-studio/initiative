import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { CaptchaWidget } from "@/components/auth/CaptchaWidget";
import { LegalNotice } from "@/components/auth/LegalNotice";
import { NewPasswordFields } from "@/components/auth/NewPasswordFields";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useLegalIndex } from "@/hooks/useLegalDocuments";
import { passkeysRunHere } from "@/lib/passkeys";
import { checkNewPassword } from "@/lib/passwordPolicy";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/**
 * The ways in this deployment offers: an address with a password and/or a
 * passkey, or a code sent to the address.
 *
 * The start flow's last step, and the whole of the first-owner page, which
 * puts its handle field above the address and offers no emailed code.
 */
export const AccountStep = ({
  email,
  onEmailChange,
  busy,
  blocked,
  onPassword,
  onPasskey,
  onEmailCode,
  onError,
  firstAccount = false,
  children,
}: {
  email: string;
  onEmailChange: (email: string) => void;
  busy: boolean;
  /** Something earlier in the flow still needs fixing (an invite that no
   *  longer works, a handle not yet typed). */
  blocked: boolean;
  onPassword: (password: string, captchaToken: string) => Promise<void>;
  onPasskey: (captchaToken: string) => Promise<void>;
  /** Opens the emailed-code door; without it, that door is not offered. */
  onEmailCode?: () => void;
  onError: (message: string) => void;
  /** The deployment's first account, which the server asks no captcha of. */
  firstAccount?: boolean;
  /** Fields asked before the address. */
  children?: ReactNode;
}) => {
  const { t } = useTranslation("auth");
  const config = useAppConfig();
  const { passwordLoginEnabled, passkeyLoginEnabled } = config;
  const captcha = firstAccount ? null : config.captcha;
  const emailCodeOffered = config.emailOtpLoginEnabled && onEmailCode !== undefined;
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  // A captcha token is spent by being checked, so every attempt gets a fresh
  // widget: bumping this remounts it.
  const [captchaKey, setCaptchaKey] = useState(0);
  const keysOffered = passkeyLoginEnabled && passkeysRunHere();
  const formDoor = passwordLoginEnabled || keysOffered;
  const incomplete = !email.trim() || (captcha !== null && !captchaToken) || blocked;
  // Its notice is still being read: wait, so it's there to agree to.
  const legalPending = useLegalIndex().pending && formDoor;

  const attempt = async (run: () => Promise<void>) => {
    try {
      await run();
    } finally {
      if (captcha) {
        setCaptchaToken("");
        setCaptchaKey((key) => key + 1);
      }
    }
  };

  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const passwordError = checkNewPassword(password, confirmPassword);
    if (passwordError) {
      onError(passwordError);
      return;
    }
    void attempt(() => onPassword(password, captchaToken));
  };

  return (
    <form className="space-y-4" onSubmit={submitPassword}>
      {children}
      {formDoor ? (
        <Field label={t("register.emailLabel")}>
          <Input
            type="email"
            value={email}
            onChange={(event) => onEmailChange(event.target.value)}
            autoComplete="email"
            autoCapitalize="none"
            required
          />
        </Field>
      ) : null}
      {passwordLoginEnabled ? (
        <NewPasswordFields
          id="start-password"
          label={t("register.passwordLabel")}
          password={password}
          confirm={confirmPassword}
          onPasswordChange={setPassword}
          onConfirmChange={setConfirmPassword}
        />
      ) : null}
      {formDoor && captcha ? (
        <CaptchaWidget key={captchaKey} config={captcha} onToken={setCaptchaToken} />
      ) : null}
      {/* Immediately above the buttons: pressing one is the agreement. */}
      {formDoor ? <LegalNotice /> : null}
      {passwordLoginEnabled ? (
        <Button type="submit" className="w-full" disabled={busy || incomplete || legalPending}>
          {busy ? t("register.submitting") : t("register.submit")}
        </Button>
      ) : null}
      {keysOffered ? (
        <Button
          type="button"
          className="w-full"
          variant={passwordLoginEnabled ? "outline" : "default"}
          onClick={() => void attempt(() => onPasskey(captchaToken))}
          disabled={busy || incomplete || legalPending}
        >
          {busy ? t("register.submitting") : t("register.submitPasskey")}
        </Button>
      ) : null}
      {emailCodeOffered ? (
        <Button
          type="button"
          className="w-full"
          variant={formDoor ? "ghost" : "default"}
          onClick={onEmailCode}
          disabled={busy || blocked}
        >
          {t("start.account.emailCode")}
        </Button>
      ) : null}
      {!formDoor && !emailCodeOffered ? (
        <p className="text-muted-foreground text-sm">{t("register.noDoorHere")}</p>
      ) : null}
    </form>
  );
};
