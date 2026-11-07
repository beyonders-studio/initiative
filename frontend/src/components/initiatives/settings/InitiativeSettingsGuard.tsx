/**
 * The answer a settings section gives someone who reached it without the
 * standing to see it.
 *
 * Each section route renders this for itself rather than trusting the tab bar
 * to have hidden the link: a typed URL reaches the route directly, and the
 * server would refuse the calls behind it anyway — this says so in words
 * instead of a screen of failed requests.
 */

import { useTranslation } from "react-i18next";

import { Card, CardDescription, CardHeader, CardTitle } from "@/ui/card";

export const InitiativeSettingsPermissionRequired = () => {
  const { t } = useTranslation("initiatives");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.permissionRequired")}</CardTitle>
        <CardDescription>{t("settings.permissionRequiredDescription")}</CardDescription>
      </CardHeader>
    </Card>
  );
};
