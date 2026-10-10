import { useNavigate } from "@tanstack/react-router";
import { isAxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { redeemDemoLink } from "@/api/generated/demo/demo";
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
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useDemoCopy } from "@/hooks/useDemoCopy";
import { getErrorMessage } from "@/lib/errorMessage";

/** Why the last start did not work: no copy free, which passes, or something
 *  else, said in its own words. */
type Refusal = { busy: true } | { busy: false; message: string };

const detailOf = (error: unknown): unknown =>
  isAxiosError<{ detail?: unknown }>(error) ? error.response?.data?.detail : undefined;

/**
 * Where a demo link lands: `/demo#<token>`. The token is read from the
 * fragment and cleared from the address straight away, and Start trades it for
 * an account in a copy of its own.
 *
 * A visitor whose copy is still live goes straight back to it instead.
 */
export const DemoPage = () => {
  const { t } = useTranslation(["auth", "errors", "common"]);
  const navigate = useNavigate();
  const { loading, applySignIn } = useAuth();
  const { communities, loading: communitiesLoading } = useCommunities();
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
  const destination = landing ?? (live ? (copy?.community?.id ?? null) : null);

  useEffect(() => {
    if (destination === null) return;
    void navigate({
      to: "/c/$communityId",
      params: { communityId: String(destination) },
      replace: true,
    });
  }, [destination, navigate]);

  const start = async () => {
    setStarting(true);
    setRefusal(null);
    try {
      const opened = await redeemDemoLink({
        token,
        captcha_token: captcha ? captchaToken : undefined,
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

  if (loading || destination !== null || (live && communitiesLoading)) {
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
          <CardContent className="space-y-4">
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
              className="w-full"
              onClick={() => void start()}
              disabled={starting || (captcha !== null && !captchaToken)}
            >
              {starting ? t("demo.starting") : refusal?.busy ? t("demo.retry") : t("demo.start")}
            </Button>
          </CardContent>
        )}
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
