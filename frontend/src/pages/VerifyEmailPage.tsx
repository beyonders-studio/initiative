import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmVerification } from "@/api/generated/auth/auth";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useEmailLinkToken } from "@/hooks/useEmailLinkToken";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";

type VerificationStatus = "pending" | "success" | "error";

export const VerifyEmailPage = () => {
  const { t } = useTranslation("auth");
  const token = useEmailLinkToken();
  const [status, setStatus] = useState<VerificationStatus>("pending");
  const [message, setMessage] = useState(t("verifyEmail.verifying"));

  useEffect(() => {
    const verify = async () => {
      if (!token) {
        setStatus("error");
        setMessage(t("verifyEmail.missingLink"));
        return;
      }
      try {
        await confirmVerification({ token });
        setStatus("success");
        setMessage(t("verifyEmail.success"));
      } catch {
        setStatus("error");
        setMessage(t("verifyEmail.error"));
      }
    };
    void verify();
  }, [token, t]);

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("verifyEmail.title")}</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "pending" ? (
            <p className="text-muted-foreground text-sm">{t("verifyEmail.hangTight")}</p>
          ) : null}
        </CardContent>
        <CardFooter className="flex flex-col gap-2 text-muted-foreground text-sm">
          {status === "success" ? (
            <Button asChild className="w-full">
              <Link to="/login">{t("verifyEmail.goToSignIn")}</Link>
            </Button>
          ) : (
            <Link className="text-primary underline-offset-4 hover:underline" to="/start">
              {t("verifyEmail.needToRegister")}
            </Link>
          )}
        </CardFooter>
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
