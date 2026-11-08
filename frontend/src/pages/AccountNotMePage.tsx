import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { readAccountChange, signOutEverywhere, undoAccountChange } from "@/api/generated/auth/auth";
import type { AccountChangeDone, AccountChangeRead } from "@/api/generated/initiativeAPI.schemas";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useAuth } from "@/hooks/useAuth";
import { useEmailLinkToken } from "@/hooks/useEmailLinkToken";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";

type Step = "reading" | "ready" | "done" | "undone" | "invalid";

/** What each undo does, by the kind the server names. */
const UNDO_KEYS = {
  proved: "notMe.undo.proved",
  primary: "notMe.undo.primary",
  removed: "notMe.undo.removed",
  passkey: "notMe.undo.passkey",
  hold: "notMe.undo.hold",
} as const;

/** What each account notice was about, by the part of its name before the dot. */
const SUBJECT_KEYS = {
  address: "notMe.subject.address",
  passkey: "notMe.subject.passkey",
  secondFactor: "notMe.subject.secondFactor",
  passwordChanged: "notMe.subject.password",
  passwordRemoved: "notMe.subject.password",
  identity: "notMe.subject.identity",
} as const;

const subjectKey = (notice: string) => {
  const section = notice.split(".")[0];
  return section in SUBJECT_KEYS
    ? SUBJECT_KEYS[section as keyof typeof SUBJECT_KEYS]
    : "notMe.subject.account";
};

/**
 * Where the "This wasn't me" button in an account email lands.
 *
 * Opening the link changes nothing: mail scanners open links too. The page
 * reads the token, says what will happen, and only a button acts: signing the
 * account out everywhere, or, where this copy of the email may, undoing the
 * change as well. Either way the people who run the server are told; where
 * nobody is set up to hear it, the page names who to tell instead.
 */
export const AccountNotMePage = () => {
  const { t } = useTranslation("auth");
  const token = useEmailLinkToken();
  const { user, refreshUser } = useAuth();
  const [step, setStep] = useState<Step>(token ? "reading" : "invalid");
  const [answer, setAnswer] = useState<AccountChangeRead | null>(null);
  const [done, setDone] = useState<AccountChangeDone | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    readAccountChange({ token })
      .then((read) => {
        setAnswer(read);
        setStep("ready");
      })
      .catch(() => setStep("invalid"));
  }, [token]);

  const act = async (undo: boolean) => {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      setDone(await (undo ? undoAccountChange({ token }) : signOutEverywhere({ token })));
      setStep(undo ? "undone" : "done");
      // This browser may be one of the sessions just ended. Asking for its
      // own account finds out, and the usual expiry handling signs it out
      // here too; a browser signed in to somebody else stays as it is.
      if (user) void refreshUser().catch(() => undefined);
    } catch (err) {
      setError(getErrorMessage(err, "auth:notMe.failed"));
    } finally {
      setSubmitting(false);
    }
  };

  const subject = t(subjectKey(answer?.notice ?? ""));
  const undoKey =
    answer?.undo && answer.undo in UNDO_KEYS
      ? UNDO_KEYS[answer.undo as keyof typeof UNDO_KEYS]
      : null;
  const finished = step === "done" || step === "undone";
  // A change that is still waiting is cancelled rather than undone.
  const cancels = answer?.undo === "hold";

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        {finished ? (
          <CardHeader>
            <CardTitle>
              {step !== "undone"
                ? t("notMe.doneTitle")
                : cancels
                  ? t("notMe.cancelledTitle")
                  : t("notMe.undoneTitle")}
            </CardTitle>
            <CardDescription>{t("notMe.doneBody")}</CardDescription>
            {done?.platform_told ? (
              <p className="pt-2 text-sm">{t("notMe.told")}</p>
            ) : done?.contact ? (
              <p className="pt-2 text-sm">{t("notMe.tellThem", { contact: done.contact })}</p>
            ) : null}
          </CardHeader>
        ) : step === "invalid" ? (
          <CardHeader>
            <CardTitle>{t("notMe.invalidTitle")}</CardTitle>
            <CardDescription>{t("notMe.invalidBody")}</CardDescription>
          </CardHeader>
        ) : (
          <>
            <CardHeader>
              <CardTitle>{t("notMe.title")}</CardTitle>
              <CardDescription>{t("notMe.description", { subject })}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {undoKey ? (
                <p className="text-sm">{t(undoKey, { subject: answer?.subject ?? "" })}</p>
              ) : null}
              <p className="text-muted-foreground text-sm">{t("notMe.whatHappens")}</p>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              {undoKey ? (
                <Button
                  className="w-full"
                  onClick={() => void act(true)}
                  disabled={step !== "ready" || submitting}
                >
                  {cancels ? t("notMe.cancelConfirm") : t("notMe.undoConfirm")}
                </Button>
              ) : null}
              {answer?.sign_out !== false ? (
                <Button
                  className="w-full"
                  variant={undoKey ? "outline" : "default"}
                  onClick={() => void act(false)}
                  disabled={step !== "ready" || submitting}
                >
                  {undoKey ? t("notMe.signOutOnly") : t("notMe.confirm")}
                </Button>
              ) : null}
            </CardContent>
          </>
        )}
        {finished || step === "invalid" ? (
          <CardFooter className="flex flex-col gap-2 text-sm">
            <Button asChild className="w-full">
              <Link to="/login">{t("notMe.signIn")}</Link>
            </Button>
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("notMe.resetPassword")}
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
