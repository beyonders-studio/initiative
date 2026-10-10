import { useNavigate } from "@tanstack/react-router";
import { isAxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { redeemDemoLink, useReadDemoCopy } from "@/api/generated/demo/demo";
import { CaptchaWidget } from "@/components/auth/CaptchaWidget";
import { LegalNotice } from "@/components/auth/LegalNotice";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
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
import { useCommunities } from "@/hooks/useCommunities";
import { useDemoCopy } from "@/hooks/useDemoCopy";
import { getErrorMessage } from "@/lib/errorMessage";

/** Why the last start did not work: no copy free, which passes, or something
 *  else, said in its own words. */
type Refusal = { busy: true } | { busy: false; message: string };

/** How often a copy still being filled is asked about, and how long that is
 *  waited for before saying so. */
const READY_POLL_MS = 2_000;
const READY_TIMEOUT_MS = 120_000;

const detailOf = (error: unknown): unknown =>
  isAxiosError<{ detail?: unknown }>(error) ? error.response?.data?.detail : undefined;

/**
 * Where a demo link lands: `/demo#<token>`. The token is read from the
 * fragment and cleared from the address straight away, and Start trades it for
 * an account in a copy of its own.
 *
 * A visitor whose copy is still live goes straight back to it instead. Either
 * way the page waits on the copy's import before going in.
 */
export const DemoPage = () => {
  const { t } = useTranslation(["auth", "errors", "common"]);
  const navigate = useNavigate();
  const { user, loading, applySignIn } = useAuth();
  const { communities } = useCommunities();
  const copy = useDemoCopy();
  const { captcha } = useAppConfig();
  const [token] = useState(() => window.location.hash.replace(/^#/, ""));
  const [captchaToken, setCaptchaToken] = useState("");
  // A captcha token is spent by being checked, so every attempt gets a fresh
  // widget: bumping this remounts it.
  const [captchaKey, setCaptchaKey] = useState(0);
  const [starting, setStarting] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [deadLink, setDeadLink] = useState(!token);
  const [landing, setLanding] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [timedOut, setTimedOut] = useState(false);
  const emailId = useId();

  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname + window.location.search
      );
    }
  }, []);

  const live = copy !== null && new Date(copy.expiresAt).getTime() > Date.now();
  const destination = landing ?? (live ? (copy?.communityId ?? null) : null);

  const filling = useReadDemoCopy({
    query: {
      enabled: destination !== null && !timedOut,
      refetchInterval: (query) =>
        query.state.data?.ready || query.state.status === "error" ? false : READY_POLL_MS,
    },
  });
  const ready = filling.data?.ready === true && filling.data.community_id === destination;

  useEffect(() => {
    if (destination === null || ready || timedOut) return;
    const timer = window.setTimeout(() => setTimedOut(true), READY_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [destination, ready, timedOut]);

  useEffect(() => {
    if (destination === null || !ready) return;
    void navigate({
      to: "/c/$communityId",
      params: { communityId: String(destination) },
      replace: true,
    });
  }, [destination, ready, navigate]);

  const start = async (event: FormEvent) => {
    event.preventDefault();
    setStarting(true);
    setRefusal(null);
    try {
      const opened = await redeemDemoLink({
        token,
        captcha_token: captcha ? captchaToken : undefined,
        email: email.trim() || undefined,
      });
      await applySignIn(opened);
      setLanding(opened.community_id);
    } catch (error) {
      const detail = detailOf(error);
      if (detail === "DEMO_LINK_NOT_FOUND") {
        setDeadLink(true);
      } else {
        setRefusal(
          detail === "DEMO_BUSY"
            ? { busy: true }
            : { busy: false, message: getErrorMessage(error, "auth:demo.failed") }
        );
      }
    } finally {
      setStarting(false);
      if (captcha) {
        setCaptchaToken("");
        setCaptchaKey((key) => key + 1);
      }
    }
  };

  const stuck = destination !== null && (timedOut || filling.isError);

  if (stuck) {
    return (
      <SignInFrame>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("demo.title")}</CardTitle>
            <CardDescription role="alert">
              {filling.isError
                ? getErrorMessage(filling.error, "auth:demo.failed")
                : t("demo.slow")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              onClick={() => {
                setTimedOut(false);
                void filling.refetch();
              }}
            >
              {t("demo.checkAgain")}
            </Button>
          </CardContent>
        </Card>
      </SignInFrame>
    );
  }

  if (loading || destination !== null) {
    const name = communities.find((community) => community.id === destination)?.name;
    return (
      <SignInFrame>
        <p className="flex items-center gap-2 text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {destination === null
            ? t("common:loading")
            : name
              ? t("demo.settingUp", { community: name })
              : t("demo.settingUpDefault")}
        </p>
      </SignInFrame>
    );
  }

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("demo.title")}</CardTitle>
          <CardDescription>
            {deadLink ? t("errors:DEMO_LINK_NOT_FOUND") : t("demo.description")}
          </CardDescription>
        </CardHeader>
        {deadLink ? null : (
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => void start(event)}>
              {user && !user.demo_expires_at ? (
                <p className="text-muted-foreground text-sm">{t("demo.signedIn")}</p>
              ) : null}
              {captcha ? (
                <CaptchaWidget key={captchaKey} config={captcha} onToken={setCaptchaToken} />
              ) : null}
              {refusal ? (
                <p className="text-destructive text-sm" role="alert">
                  {refusal.busy ? t("errors:DEMO_BUSY") : refusal.message}
                </p>
              ) : null}
              {/* Immediately above the button: pressing it is the agreement. */}
              <LegalNotice />
              <Button
                type="submit"
                className="w-full"
                disabled={starting || (captcha !== null && !captchaToken)}
              >
                {starting ? t("demo.starting") : refusal?.busy ? t("demo.retry") : t("demo.start")}
              </Button>
              <div className="space-y-2">
                <Label htmlFor={emailId}>{t("demo.lead.optionalLabel")}</Label>
                <Input
                  id={emailId}
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
                <p className="text-muted-foreground text-sm">{t("demo.lead.pitch")}</p>
              </div>
            </form>
          </CardContent>
        )}
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
