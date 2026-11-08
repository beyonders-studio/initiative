import { Link, useRouter } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { resetPassword } from "@/api/generated/auth/auth";
import { NewPasswordFields } from "@/components/auth/NewPasswordFields";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useEmailLinkToken } from "@/hooks/useEmailLinkToken";
import { getErrorMessage } from "@/lib/errorMessage";
import { checkNewPassword } from "@/lib/passwordPolicy";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";

export const ResetPasswordPage = () => {
  // Include ``errors`` so ``getErrorMessage`` can map server codes
  // like ``PASSWORD_BREACHED`` without the namespace having to
  // lazy-load mid-submit.
  const { t } = useTranslation(["auth", "errors"]);
  const { passwordLoginEnabled } = useAppConfig();
  const router = useRouter();
  const token = useEmailLinkToken();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reset = useApiMutation(
    { mutationFn: resetPassword },
    {
      // ``getErrorMessage`` maps server codes like ``PASSWORD_BREACHED``
      // to the localized string from ``errors.json``; falls back to the
      // generic reset-page error when the code isn't recognized.
      onError: (err) => setError(getErrorMessage(err, "auth:resetPassword.error")),
    }
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) {
      setError(t("resetPassword.missingToken"));
      return;
    }
    const passwordError = checkNewPassword(password, confirmPassword);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    setError(null);
    reset.mutate({ token, password });
  };

  // A link mailed before passwords were withdrawn still arrives here, and
  // the server refuses the reset it asks for.
  if (!passwordLoginEnabled) {
    return (
      <SignInFrame>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("passwordsOff.title")}</CardTitle>
            <CardDescription>{t("passwordsOff.description")}</CardDescription>
          </CardHeader>
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/login">
              {t("forgotPassword.backToSignIn")}
            </Link>
          </CardFooter>
          <CardFooter>
            <ServerChip />
          </CardFooter>
        </Card>
      </SignInFrame>
    );
  }

  if (!token) {
    return (
      <SignInFrame>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("resetPassword.titleInvalid")}</CardTitle>
            <CardDescription>{t("resetPassword.subtitleInvalid")}</CardDescription>
          </CardHeader>
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("resetPassword.requestReset")}
            </Link>
          </CardFooter>
          <CardFooter>
            <ServerChip />
          </CardFooter>
        </Card>
      </SignInFrame>
    );
  }

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("resetPassword.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {reset.isSuccess ? (
            <div className="space-y-4 text-primary text-sm">
              <p>{t("resetPassword.success")}</p>
              <Button className="w-full" onClick={() => router.navigate({ to: "/login" })}>
                {t("resetPassword.goToSignIn")}
              </Button>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <NewPasswordFields
                id="new-password"
                label={t("resetPassword.newPasswordLabel")}
                password={password}
                confirm={confirmPassword}
                onPasswordChange={setPassword}
                onConfirmChange={setConfirmPassword}
              />
              <Button className="w-full" type="submit" disabled={reset.isPending}>
                {reset.isPending ? t("resetPassword.submitting") : t("resetPassword.submit")}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          )}
        </CardContent>
        {!reset.isSuccess ? (
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("resetPassword.needNewLink")}
            </Link>
          </CardFooter>
        ) : null}
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
