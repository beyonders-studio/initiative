import { useState } from "react";
import { useTranslation } from "react-i18next";

import { acceptLegalDocuments } from "@/api/generated/users/users";
import { LegalDocumentLinks } from "@/components/auth/LegalNotice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * The screen an account meets when it has never agreed to this deployment's
 * terms and privacy policy.
 *
 * Almost nobody sees it. Signing up through the form is the agreement, and it
 * is recorded as the account is created. This is for the way in that had no
 * form to put a notice above: an account an identity provider provisioned on
 * first sign-in.
 *
 * So the button here is explicit where the signup form's is implicit — there
 * was no sentence over a Create account button for this person to have read.
 * As on the handle and age screens there is no decline: declining is signing
 * out, which they can already do.
 */
export const AcceptTerms = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { refreshUser, logout } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await acceptLegalDocuments();
      await refreshUser();
    } catch (err) {
      setError(getErrorMessage(err, "legal:acceptError"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-app items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("legal:accept.title")}</CardTitle>
          <CardDescription>{t("legal:accept.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <LegalDocumentLinks />
          {error && <p className="text-destructive text-sm">{error}</p>}
          <Button className="w-full" disabled={submitting} onClick={() => void accept()}>
            {submitting ? t("common:submitting") : t("legal:accept.submit")}
          </Button>
          <Button type="button" variant="ghost" className="w-full" onClick={() => void logout()}>
            {t("legal:accept.signOut")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
