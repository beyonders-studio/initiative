import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { recoverWithCode, requestPasswordReset } from "@/api/generated/auth/auth";
import { NewPasswordFields } from "@/components/auth/NewPasswordFields";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useAppConfig } from "@/hooks/useAppConfig";
import { getErrorMessage } from "@/lib/errorMessage";
import { checkNewPassword } from "@/lib/passwordPolicy";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/**
 * Two ways back in, on one card.
 *
 * The mailed link is the usual one. An account that signs in with a passkey
 * has no password to reset and may be on a deployment that sends no mail at
 * all, so the other way is a recovery code: it sets a password rather than
 * opening a session, and that password is what signs the account in next.
 */
export const ForgotPasswordPage = () => {
  // ``errors`` comes along so a server code — a code that did not match, a
  // password the policy refuses — is localized without a mid-submit load.
  const { t } = useTranslation(["auth", "common", "errors"]);
  const { passwordLoginEnabled } = useAppConfig();
  const [mode, setMode] = useState<"reset" | "recover">("reset");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const request = useApiMutation(
    { mutationFn: requestPasswordReset },
    { onError: () => setError(t("forgotPassword.error")) }
  );

  const [recoveryCode, setRecoveryCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const recover = useApiMutation(
    { mutationFn: recoverWithCode },
    { onError: (err) => setError(getErrorMessage(err, "auth:forgotPassword.recoverError")) }
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    request.mutate({ email: email.toLowerCase().trim() });
  };

  const handleRecover = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const passwordError = checkNewPassword(password, confirmPassword);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    setError(null);
    recover.mutate({
      email: email.toLowerCase().trim(),
      recovery_code: recoveryCode.trim(),
      password,
    });
  };

  const switchMode = (next: "reset" | "recover") => {
    setMode(next);
    setError(null);
    request.reset();
    recover.reset();
    setRecoveryCode("");
    setPassword("");
    setConfirmPassword("");
  };

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        {/* Both ways end in a password, which this deployment may not take:
          the server refuses them then, so the page says so instead. */}
        {!passwordLoginEnabled ? (
          <CardHeader>
            <CardTitle>{t("passwordsOff.title")}</CardTitle>
            <CardDescription>{t("passwordsOff.description")}</CardDescription>
          </CardHeader>
        ) : (
          <CardHeader>
            <CardTitle>
              {mode === "recover" ? t("forgotPassword.recoverTitle") : t("forgotPassword.title")}
            </CardTitle>
            <CardDescription>
              {mode === "recover"
                ? t("forgotPassword.recoverSubtitle")
                : t("forgotPassword.subtitle")}
            </CardDescription>
          </CardHeader>
        )}
        {passwordLoginEnabled ? (
          <CardContent>
            {mode === "reset" ? (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <Field label={t("forgotPassword.emailLabel")}>
                  <Input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    autoComplete="email"
                    autoCapitalize="none"
                  />
                </Field>
                <Button className="w-full" type="submit" disabled={request.isPending}>
                  {request.isPending ? t("forgotPassword.submitting") : t("forgotPassword.submit")}
                </Button>
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
                {request.isSuccess ? (
                  <p className="text-primary text-sm">{t("forgotPassword.sent")}</p>
                ) : null}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => switchMode("recover")}
                >
                  {t("forgotPassword.useRecoveryCode")}
                </button>
              </form>
            ) : recover.isSuccess ? (
              <div className="space-y-4 text-primary text-sm">
                <p>{t("forgotPassword.recovered")}</p>
                <Button className="w-full" asChild>
                  <Link to="/login">{t("resetPassword.goToSignIn")}</Link>
                </Button>
              </div>
            ) : (
              <form className="space-y-4" onSubmit={handleRecover}>
                <Field label={t("forgotPassword.emailLabel")}>
                  <Input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    autoComplete="email"
                    autoCapitalize="none"
                  />
                </Field>
                <Field label={t("forgotPassword.recoveryCodeLabel")}>
                  <Input
                    value={recoveryCode}
                    onChange={(event) => setRecoveryCode(event.target.value)}
                    placeholder={t("forgotPassword.recoveryCodePlaceholder")}
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    required
                  />
                </Field>
                <NewPasswordFields
                  id="recover-password"
                  label={t("resetPassword.newPasswordLabel")}
                  password={password}
                  confirm={confirmPassword}
                  onPasswordChange={setPassword}
                  onConfirmChange={setConfirmPassword}
                />
                <Button className="w-full" type="submit" disabled={recover.isPending}>
                  {recover.isPending
                    ? t("forgotPassword.recovering")
                    : t("forgotPassword.recoverSubmit")}
                </Button>
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => switchMode("reset")}
                >
                  {t("forgotPassword.backToReset")}
                </button>
              </form>
            )}
          </CardContent>
        ) : null}
        <CardFooter className="text-muted-foreground text-sm">
          {passwordLoginEnabled ? `${t("forgotPassword.remembered")} ` : null}
          <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
            {t("forgotPassword.backToSignIn")}
          </Link>
        </CardFooter>
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
