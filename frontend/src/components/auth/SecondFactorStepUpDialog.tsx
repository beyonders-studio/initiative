import { Link, useLocation, useNavigate, useRouter } from "@tanstack/react-router";
import { isAxiosError } from "axios";
import { KeyRound, Mail } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import { sendStepUpCode, useListPasskeys, useReadSecondFactor } from "@/api/generated/auth/auth";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useAuthChallenge } from "@/hooks/useAuthChallenge";
import { isAnsweredVisitRead } from "@/hooks/useNotifications";
import { getErrorMessage } from "@/lib/errorMessage";
import { describePasskeyPromptError } from "@/lib/passkeys";
import { queryClient } from "@/lib/queryClient";
import { returnPath } from "@/lib/returnPath";
import { compactCode } from "@/lib/secondFactorAnswer";
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

/**
 * Global handler for a community that requires a factor of the account's own.
 *
 * When any request is refused for want of one (dispatched by the API client as
 * a window event), this asks for it and adds it to the session already open.
 * The requests that were refused are refetched once it succeeds, so the page
 * the person was on fills in behind the dialog rather than needing a reload.
 *
 * Two factors can be asked for, and the event says which: a code from the
 * account's authenticator app, or a passkey. Both work in the app too: the
 * code is typed against the live session, and the passkey's prompt runs
 * wherever `lib/passkeys` can run it.
 *
 * A third ask arrives from the account's own settings rather than a community:
 * a change to how it signs in wants a session opened a moment ago. A passkey
 * opens one, so does a code sent to the account's proved address where the
 * deployment sends them, and so does signing in again — which is the whole
 * offer for an account that holds no passkey because a provider signs it in.
 *
 * A fourth comes from the deployment: it asks this account to hold a second
 * factor, and it holds none. The same answer — a code, or a passkey — with two
 * differences. It says who is asking, and it offers to sign out rather than to
 * carry on, because a refusal from the deployment is every request rather than
 * one page's.
 */
export const SecondFactorStepUpDialog = () => {
  // The array form, so the line a put-down prompt deserves — named by
  // `describePasskeyPromptError` as a fully qualified key — is one `t` accepts.
  const { t } = useTranslation(["auth", "common"]);
  const { logout, stepUpWithFactor, stepUpWithPasskey, stepUpWithEmailCode } = useAuth();
  const { emailOtpLoginEnabled } = useAppConfig();
  const router = useRouter();
  const navigate = useNavigate();
  // Everything is accepted except the deployment's own ask while the person
  // is on the page that answers it: the shell around that page makes requests
  // of its own, and each would put this dialog back over the thing it is
  // asking them to do. Their next request elsewhere raises it again.
  const onSecurityPage = useLocation({
    select: (location) => location.pathname.startsWith("/profile/security"),
  });
  const { challenge, clear, open } = useAuthChallenge<FactorChallengeDetail>(
    AUTH_FACTOR_REQUIRED_EVENT,
    (detail) => !(detail?.platform === true && onSecurityPage)
  );
  const wantsPasskey = challenge?.kind === "passkey";
  const wantsProof = challenge?.kind === "proof";
  /** The deployment asking, rather than one community. */
  const fromPlatform = challenge?.platform === true;
  /** Both asks are answered by presenting a passkey, so both read the same
   *  side of this dialog and ask the account the same question. */
  const presentsPasskey = wantsPasskey || wantsProof;
  /** A code to the account's address answers the proof, where the deployment
   *  sends them. Typed back, so it works in the app as well as a browser. */
  const offersEmailCode = wantsProof && emailOtpLoginEnabled;
  // The handle the send route handed back; set once a code is on its way.
  const [emailChallenge, setEmailChallenge] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only asked once there is something to answer, and only for the factor that
  // was asked for. Both routes are platform-scoped, so neither is itself
  // refused by the community that raised the challenge.
  const statusQuery = useReadSecondFactor({
    query: { enabled: open && !presentsPasskey },
  });
  // Asked on both sides now. On the passkey side it decides what to offer; on
  // the code side it is the other way to answer the same ask — a user-verified
  // passkey records the factor too, so an account with a key and no
  // authenticator app has one already.
  const passkeyQuery = useListPasskeys({
    query: { enabled: open },
  });
  // Three states, not two. While the answer is in flight, offer the way in:
  // the refusal that opened this dialog is the common case and an account that
  // can answer is what it assumes. Only a definite "nothing to present with"
  // swaps it for the way to get one — and when the account cannot be read at
  // all, the way in stays but the way to get one is offered beside it, so
  // neither audience is stranded.
  const hasNoFactor = statusQuery.data?.enrolled === false;
  const statusUnknown = statusQuery.isError;
  const hasNoPasskey = passkeyQuery.isSuccess && (passkeyQuery.data.passkeys ?? []).length === 0;
  /** A key to present, where the ask is for a code and the account has none. */
  const canPresentPasskey = passkeyQuery.isSuccess && (passkeyQuery.data.passkeys ?? []).length > 0;
  const passkeysUnknown = passkeyQuery.isError;

  const dismiss = () => {
    clear();
    setCode("");
    setUseRecoveryCode(false);
    setEmailChallenge(null);
    setError(null);
  };

  /** What both answers do once the session carries the factor: every query
   *  refused while it did not should ask again, and the dialog is done. The
   *  page's own read of what was unread is kept, since asking it again would
   *  find nothing and clear it. */
  const settle = async () => {
    await queryClient.invalidateQueries({ predicate: (query) => !isAnsweredVisitRead(query) });
    dismiss();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const entered = code.trim();
      await stepUpWithFactor(
        useRecoveryCode ? { recoveryCode: entered } : { code: compactCode(entered) }
      );
      await settle();
    } catch (err) {
      setError(getErrorMessage(err, "auth:factorStepUp.error"));
    } finally {
      setSubmitting(false);
    }
  };

  const presentPasskey = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await stepUpWithPasskey();
      await settle();
    } catch (err) {
      if (isAxiosError(err)) {
        setError(getErrorMessage(err, "auth:factorStepUp.passkeyError"));
      } else {
        // A prompt that produced nothing is the browser's news, not the
        // server's — and one this page put down itself has no line at all.
        const key = describePasskeyPromptError(err);
        setError(key ? t(key) : null);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const sendEmailCode = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const sent = await sendStepUpCode();
      setCode("");
      setEmailChallenge(sent.challenge);
    } catch (err) {
      setError(getErrorMessage(err, "auth:factorStepUp.emailCodeError"));
    } finally {
      setSubmitting(false);
    }
  };

  const submitEmailCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!emailChallenge) return;
    setSubmitting(true);
    setError(null);
    try {
      await stepUpWithEmailCode({ challenge: emailChallenge, code: code.trim() });
      await settle();
    } catch (err) {
      setError(getErrorMessage(err, "auth:factorStepUp.emailCodeError"));
    } finally {
      setSubmitting(false);
    }
  };

  /** The other way to open a fresh session, for an account with no passkey to
   *  present: start one over, and come back to the page this was raised on. */
  const signInAgain = async () => {
    const next = returnPath(router.state.location.href);
    setSubmitting(true);
    try {
      await logout();
      dismiss();
      await navigate({ to: "/login", search: next && next !== "/" ? { next } : {} });
    } finally {
      setSubmitting(false);
    }
  };

  const presentDescription = offersEmailCode
    ? t("factorStepUp.proofEmail")
    : hasNoPasskey
      ? t(wantsProof ? "factorStepUp.proofSignIn" : "factorStepUp.passkeyNone")
      : t(wantsProof ? "factorStepUp.proofDescription" : "factorStepUp.passkeyDescription");

  return (
    <Dialog open={open} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent>
        {emailChallenge ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("factorStepUp.proofTitle")}</DialogTitle>
              <DialogDescription>{t("factorStepUp.emailCodeSent")}</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={submitEmailCode}>
              <div className="space-y-2">
                <Label htmlFor="step-up-email-code">{t("factorStepUp.emailCodeLabel")}</Label>
                <Input
                  id="step-up-email-code"
                  name="step-up-email-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  required
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              {/* A code lasts minutes and a few tries; a spent one is replaced
                  here rather than by starting the change over. */}
              <button
                type="button"
                className="text-primary text-sm underline-offset-4 hover:underline"
                onClick={sendEmailCode}
                disabled={submitting}
              >
                {t("factorStepUp.emailCodeResend")}
              </button>
              <DialogFooter
                cancel={t("factorStepUp.dismiss")}
                submitLabel={t("factorStepUp.submit")}
                pendingLabel={t("login.submitting")}
                pending={submitting}
                disabled={!code.trim()}
              />
            </form>
          </>
        ) : presentsPasskey ? (
          <>
            <DialogHeader>
              <DialogTitle>
                {t(wantsProof ? "factorStepUp.proofTitle" : "factorStepUp.passkeyTitle")}
              </DialogTitle>
              <DialogDescription>{presentDescription}</DialogDescription>
            </DialogHeader>

            {error && <p className="text-destructive text-sm">{error}</p>}

            <DialogFooter>
              <Button variant="outline" onClick={dismiss}>
                {t("factorStepUp.dismiss")}
              </Button>
              {offersEmailCode && (
                <Button type="button" onClick={sendEmailCode} disabled={submitting}>
                  <Mail className="h-4 w-4" aria-hidden="true" />
                  {t("factorStepUp.emailCode")}
                </Button>
              )}
              {hasNoPasskey ? (
                wantsProof ? (
                  <Button type="button" onClick={signInAgain} disabled={submitting}>
                    {t("factorStepUp.signInAgain")}
                  </Button>
                ) : (
                  <Button asChild>
                    <Link to="/profile/security" onClick={dismiss}>
                      {t("factorStepUp.passkeyAdd")}
                    </Link>
                  </Button>
                )
              ) : (
                <Button type="button" onClick={presentPasskey} disabled={submitting}>
                  <KeyRound className="h-4 w-4" aria-hidden="true" />
                  {submitting ? t("factorStepUp.passkeyWorking") : t("factorStepUp.passkeyPresent")}
                </Button>
              )}
            </DialogFooter>

            {passkeysUnknown &&
              (wantsProof ? (
                <p className="text-muted-foreground text-sm">
                  <button
                    type="button"
                    onClick={signInAgain}
                    disabled={submitting}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {t("factorStepUp.signInAgain")}
                  </button>
                </p>
              ) : (
                <p className="text-muted-foreground text-sm">
                  <Link
                    to="/profile/security"
                    onClick={dismiss}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {t("factorStepUp.passkeyAdd")}
                  </Link>
                </p>
              ))}
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>
                {t(fromPlatform ? "factorStepUp.platformTitle" : "factorStepUp.title")}
              </DialogTitle>
              <DialogDescription>
                {hasNoFactor
                  ? t(
                      fromPlatform ? "factorStepUp.platformNotEnrolled" : "factorStepUp.notEnrolled"
                    )
                  : useRecoveryCode
                    ? t("factorStepUp.recoveryDescription")
                    : t(
                        fromPlatform
                          ? "factorStepUp.platformDescription"
                          : "factorStepUp.description"
                      )}
              </DialogDescription>
            </DialogHeader>

            {hasNoFactor ? (
              <DialogFooter>
                {fromPlatform ? (
                  <Button variant="outline" onClick={signInAgain} disabled={submitting}>
                    {t("factorStepUp.signOut")}
                  </Button>
                ) : (
                  <Button variant="outline" onClick={dismiss}>
                    {t("factorStepUp.dismiss")}
                  </Button>
                )}
                {canPresentPasskey && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={presentPasskey}
                    disabled={submitting}
                  >
                    <KeyRound className="h-4 w-4" aria-hidden="true" />
                    {t("factorStepUp.passkeyPresent")}
                  </Button>
                )}
                <Button asChild>
                  <Link to="/profile/security" onClick={dismiss}>
                    {t("factorStepUp.setUp")}
                  </Link>
                </Button>
              </DialogFooter>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="step-up-code">
                    {useRecoveryCode
                      ? t("secondFactor.recoveryLabel")
                      : t("secondFactor.codeLabel")}
                  </Label>
                  <Input
                    id="step-up-code"
                    name="step-up-code"
                    // A recovery code carries letters and dashes; a live code is
                    // six digits, and the numeric keypad is what a phone should
                    // offer for it.
                    inputMode={useRecoveryCode ? "text" : "numeric"}
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    autoFocus
                    placeholder={
                      useRecoveryCode
                        ? t("secondFactor.recoveryPlaceholder")
                        : t("secondFactor.codePlaceholder")
                    }
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                </div>
                {error && <p className="text-destructive text-sm">{error}</p>}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => {
                    setUseRecoveryCode((previous) => !previous);
                    setCode("");
                    setError(null);
                  }}
                >
                  {useRecoveryCode
                    ? t("secondFactor.useAuthenticator")
                    : t("secondFactor.useRecoveryCode")}
                </button>
                <DialogFooter>
                  {fromPlatform ? (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={signInAgain}
                      disabled={submitting}
                    >
                      {t("factorStepUp.signOut")}
                    </Button>
                  ) : (
                    <Button type="button" variant="outline" onClick={dismiss}>
                      {t("factorStepUp.dismiss")}
                    </Button>
                  )}
                  <Button type="submit" disabled={submitting || !code.trim()}>
                    {submitting ? t("login.submitting") : t("factorStepUp.submit")}
                  </Button>
                </DialogFooter>
                {statusUnknown && (
                  <p className="text-muted-foreground text-sm">
                    {t("factorStepUp.noFactorHint")}{" "}
                    <Link
                      to="/profile/security"
                      onClick={dismiss}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {t("factorStepUp.setUp")}
                    </Link>
                  </p>
                )}
              </form>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
