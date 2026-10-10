/**
 * Signing in — or up — with a code sent to an address.
 *
 * Three steps in one card, because the address box cannot know which of the
 * two it is until the code comes back: the address, then the code, then (only
 * for somebody new) the handle they want.
 *
 * The card holds the challenge and the ticket in memory and nowhere else.
 * Neither is a credential on its own — the other half of each is in the
 * mailbox — and neither outlives the card.
 *
 * Where the deployment runs a captcha, the address step carries it: asking
 * for a code is the step that posts mail to an address nobody has proved
 * yet, and it is the one the server checks a token on.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { registerWithCode, sendSignInCode } from "@/api/generated/auth/auth";
import type { EmailOtpRegister, Token } from "@/api/generated/initiativeAPI.schemas";
import { CaptchaWidget } from "@/components/auth/CaptchaWidget";
import { LegalNotice } from "@/components/auth/LegalNotice";
import { ServerChip } from "@/components/auth/ServerChoice";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { browserTimezone } from "@/lib/timezones";

type Step = "address" | "code" | "handle";

interface Props {
  /** Back to the other ways in. */
  onCancel: () => void;
  /** Where to go once there is a session; `registered` when the code made a
   *  new account rather than signing in to one. */
  onSignedIn: (registered: boolean) => void;
  /** An invite this deployment asked for, carried from the URL. */
  inviteCode?: string | null;
  /** What the start flow already asked: the handle fills the last step, and
   *  the rest is sent with the account the code makes. */
  registration?: Omit<Partial<EmailOtpRegister>, "registration_ticket" | "invite_code">;
}

/** Strip the spaces a pasted code brings with it. */
const compact = (value: string) => value.replace(/\s+/g, "");

export const EmailOtpCard = ({ onCancel, onSignedIn, inviteCode, registration }: Props) => {
  const { t } = useTranslation("auth");
  const { applySignIn } = useAuth();
  // Null on the deployments that run no captcha, which is most of them.
  const { captcha } = useAppConfig();

  const [step, setStep] = useState<Step>("address");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [username, setUsername] = useState(registration?.username ?? "");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [ticket, setTicket] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captchaToken, setCaptchaToken] = useState("");
  // A token is spent by being checked, so every attempt gets a fresh widget:
  // bumping this remounts it and clears the solve the server already took.
  const [captchaKey, setCaptchaKey] = useState(0);

  const askForCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (captcha && !captchaToken) {
      setError(t("emailOtp.captchaRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const sent = await sendSignInCode({
        email: email.toLowerCase().trim(),
        ...(inviteCode ? { invite_code: inviteCode } : {}),
        ...(captcha ? { captcha_token: captchaToken } : {}),
      });
      setChallenge(sent.challenge);
      setStep("code");
    } catch (err) {
      setError(getErrorMessage(err, "auth:emailOtp.sendError"));
    } finally {
      setBusy(false);
      if (captcha) {
        setCaptchaToken("");
        setCaptchaKey((key) => key + 1);
      }
    }
  };

  const answerCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!challenge) return;
    setBusy(true);
    setError(null);
    try {
      const response = await apiClient.post<Partial<Token> & { registration_ticket?: string }>(
        "/auth/email-otp/verify",
        { challenge, code: compact(code) }
      );
      // 202 means the code was right and the address belongs to nobody yet,
      // so what is left is to say who this is.
      if (response.status === 202 && response.data.registration_ticket) {
        setTicket(response.data.registration_ticket);
        setStep("handle");
        return;
      }
      if (response.data.access_token) {
        await applySignIn({ ...response.data, access_token: response.data.access_token });
        onSignedIn(false);
      }
    } catch (err) {
      setError(getErrorMessage(err, "auth:emailOtp.codeError"));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const chooseHandle = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      const token = await registerWithCode({
        timezone: browserTimezone(),
        ...registration,
        registration_ticket: ticket,
        username: username.trim(),
        ...(inviteCode ? { invite_code: inviteCode } : {}),
      });
      await applySignIn(token);
      onSignedIn(true);
    } catch (err) {
      setError(getErrorMessage(err, "auth:emailOtp.registerError"));
    } finally {
      setBusy(false);
    }
  };

  const title =
    step === "handle"
      ? t("emailOtp.handleTitle")
      : step === "code"
        ? t("emailOtp.codeTitle")
        : t("emailOtp.title");
  const description =
    step === "handle"
      ? t("emailOtp.handleSubtitle")
      : step === "code"
        ? t("emailOtp.codeSubtitle", { email })
        : t("emailOtp.subtitle");

  return (
    <Card className="w-full max-w-md shadow-lg">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="mb-4 text-destructive text-sm" role="alert">
            {error}
          </p>
        ) : null}

        {step === "address" ? (
          <form className="space-y-4" onSubmit={askForCode}>
            <div className="space-y-2">
              <Label htmlFor="email-otp-address">{t("emailOtp.addressLabel")}</Label>
              <Input
                id="email-otp-address"
                type="email"
                autoComplete="email"
                autoFocus
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={t("emailOtp.addressPlaceholder")}
              />
            </div>
            {captcha ? (
              <CaptchaWidget key={captchaKey} config={captcha} onToken={setCaptchaToken} />
            ) : null}
            <Button
              type="submit"
              className="w-full"
              disabled={busy || (captcha !== null && !captchaToken)}
            >
              {busy ? t("login.submitting") : t("emailOtp.sendAction")}
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={onCancel}>
              {t("emailOtp.back")}
            </Button>
          </form>
        ) : null}

        {step === "code" ? (
          <form className="space-y-4" onSubmit={answerCode}>
            <div className="space-y-2">
              <Label htmlFor="email-otp-code">{t("emailOtp.codeLabel")}</Label>
              <Input
                id="email-otp-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                required
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder={t("emailOtp.codePlaceholder")}
              />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? t("login.submitting") : t("emailOtp.codeAction")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => {
                setStep("address");
                setChallenge(null);
                setCode("");
                setError(null);
              }}
            >
              {t("emailOtp.wrongAddress")}
            </Button>
          </form>
        ) : null}

        {step === "handle" ? (
          <form className="space-y-4" onSubmit={chooseHandle}>
            <div className="space-y-2">
              <Label htmlFor="email-otp-username">{t("emailOtp.usernameLabel")}</Label>
              <Input
                id="email-otp-username"
                autoComplete="username"
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={t("emailOtp.usernamePlaceholder")}
              />
            </div>
            {/* Pressing the button below is the agreement, so the notice sits
              right above it. */}
            <LegalNotice />
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? t("login.submitting") : t("emailOtp.registerAction")}
            </Button>
          </form>
        ) : null}
      </CardContent>
      <CardFooter>
        <ServerChip />
      </CardFooter>
    </Card>
  );
};
