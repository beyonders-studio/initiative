import { useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { useResumeAfterSignIn } from "@/hooks/useResumeAfterSignIn";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

export const OidcCallbackPage = () => {
  const { t } = useTranslation(["auth", "errors"]);
  const searchParams = useSearch({ strict: false }) as {
    error?: string;
    next?: string;
  };
  const { completeOidcLogin } = useAuth();
  const resumeAfterSignIn = useResumeAfterSignIn();
  const [status, setStatus] = useState(t("oidcCallback.finishing"));
  // The exchange is a one-shot side effect that also changes auth state, which
  // re-renders this page. Guard it so the callback is only ever consumed once,
  // however the effect's dependencies churn.
  const startedRef = useRef(false);

  useEffect(() => {
    const error = searchParams.error;
    if (error) {
      // The backend redirects with a machine-readable code. Show what it means
      // where we have a sentence for it, and the code itself where we do not.
      const explained = t(error, { ns: "errors", defaultValue: "" });
      setStatus(explained || t("oidcCallback.failedWithError", { error }));
      return;
    }
    if (startedRef.current) {
      return;
    }
    startedRef.current = true;
    const run = async () => {
      try {
        // The server's redirect set this browser's session cookie. The app's
        // sign-ins are finished by useDeepLinks and only land here to explain
        // a failure.
        await completeOidcLogin();
        // A step-up sign-in returns to the page it interrupted.
        await resumeAfterSignIn(searchParams.next);
      } catch {
        setStatus(t("oidcCallback.error"));
      }
    };
    void run();
  }, [completeOidcLogin, resumeAfterSignIn, searchParams, t]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("oidcCallback.title")}</CardTitle>
          <CardDescription>{t("oidcCallback.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{status}</p>
        </CardContent>
      </Card>
    </div>
  );
};
