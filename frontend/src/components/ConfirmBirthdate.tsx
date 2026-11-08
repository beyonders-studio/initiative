import { useTranslation } from "react-i18next";

import { BirthdateField } from "@/components/auth/BirthdateField";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

/**
 * The screen an account meets once, when no date of birth is on file.
 *
 * Plug-ins can carry a minimum age that differs by country, and the check needs
 * the date rather than a yes-or-no, so every account is asked a single time —
 * an account that signed up with one never sees this. The note under the field
 * says what is done with it and, where the deployment has a privacy policy,
 * links it. As on the handle and terms screens there is no decline: declining
 * is signing out.
 */
export const ConfirmBirthdate = () => {
  const { t } = useTranslation(["auth", "legal", "common"]);
  const { logout } = useAuth();
  const { birthdate, setBirthdate, submitting, error, confirm } = useAgeConfirmation();

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("auth:confirmAge.title")}</CardTitle>
          <CardDescription>{t("auth:confirmAge.scopeNote")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <BirthdateField
            id="confirm-birthdate"
            value={birthdate}
            onChange={setBirthdate}
            disabled={submitting}
          />
          {error && <p className="text-destructive text-sm">{error}</p>}
          <Button
            className="w-full"
            disabled={!birthdate || submitting}
            onClick={() => void confirm()}
          >
            {submitting ? t("common:submitting") : t("auth:confirmAge.submit")}
          </Button>
          <Button type="button" variant="ghost" className="w-full" onClick={() => void logout()}>
            {t("legal:accept.signOut")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
