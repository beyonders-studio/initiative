import { Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ServerChip, ServerPicker } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { AccountStep } from "@/components/start/AccountStep";
import { useSignUp } from "@/components/start/useSignUp";
import { type HandleCheck, UsernameField } from "@/components/UsernameField";
import { browserTimezone } from "@/lib/timezones";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";

/**
 * The first account on a fresh deployment, which becomes its owner. Everyone
 * after that signs up through the start flow; this page asks the same account
 * step, with the handle above it and no community to carry.
 */
export const RegisterPage = () => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  const router = useRouter();
  const signUp = useSignUp();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [handle, setHandle] = useState<HandleCheck>({ usable: true, offer: null });
  const [error, setError] = useState<string | null>(null);
  /** Made, but waiting on a letter or an approval before it can sign in. */
  const [held, setHeld] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  /** What both doors send about the person registering. */
  const details = () => ({
    email: email.toLowerCase().trim(),
    username: username.trim().toLowerCase(),
    username_offer: handle.offer ?? undefined,
    // The browser's IANA timezone, so the account starts on the person's wall
    // clock rather than the server's UTC default.
    timezone: browserTimezone(),
  });

  const submitPassword = async (password: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const { made, signedIn } = await signUp.withPassword(details(), password);
      if (signedIn) {
        void router.navigate({ to: "/", replace: true });
        return;
      }
      setHeld(
        made.status === "active" ? t("register.verifyEmailMessage") : t("register.pendingApproval")
      );
    } catch (err) {
      setError(signUp.failure(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submitPasskey = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await signUp.withPasskey(details(), undefined, setRecoveryCodes);
    } catch (err) {
      setError(signUp.failure(err, true));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("register.titleBootstrap")}</CardTitle>
          <CardDescription>{t("register.subtitleBootstrap")}</CardDescription>
        </CardHeader>
        <CardContent>
          {recoveryCodes ? (
            // The account exists and is signed in; what is left is the one
            // sight of the codes that are now its way back to a password.
            <RecoveryCodesPanel
              codes={recoveryCodes}
              note={t("register.recoveryCodesNote")}
              onDone={() => router.navigate({ to: "/", replace: true })}
            />
          ) : held ? (
            <p className="text-primary text-sm">{held}</p>
          ) : (
            <div className="space-y-4">
              <AccountStep
                email={email}
                onEmailChange={setEmail}
                busy={submitting}
                blocked={!username.trim()}
                onPassword={submitPassword}
                onPasskey={submitPasskey}
                onError={setError}
                firstAccount
              >
                <UsernameField
                  id="register-username"
                  value={username}
                  onChange={setUsername}
                  onChecked={setHandle}
                  disabled={submitting}
                />
              </AccountStep>
              {error ? (
                <p className="text-destructive text-sm" role="alert">
                  {error}
                </p>
              ) : null}
            </div>
          )}
        </CardContent>
        <CardFooter className="text-muted-foreground text-sm">
          {t("register.haveAccount")}{" "}
          <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
            {t("register.signIn")}
          </Link>
        </CardFooter>
        {/* Signed in by now, so the server is shown rather than changed. */}
        <CardFooter>
          {recoveryCodes ? <ServerChip /> : <ServerPicker className="w-full" />}
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
