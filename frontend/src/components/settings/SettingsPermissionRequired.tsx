/**
 * What a section of a tool's or an initiative's settings shows someone without
 * the standing to see it. Each section renders it for itself, since its route
 * opens from an address as well as from its tab.
 */

import { useTranslation } from "react-i18next";

import { Card, CardDescription, CardHeader, CardTitle } from "@/ui/card";

export interface SettingsPermissionRequiredProps {
  /** Whose settings the section belongs to, which picks the words. */
  scope: "tool" | "initiative";
}

export const SettingsPermissionRequired = ({ scope }: SettingsPermissionRequiredProps) => {
  const { t } = useTranslation(["common", "initiatives"]);
  const initiative = scope === "initiative";

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {initiative
            ? t("initiatives:settings.permissionRequired")
            : t("common:toolSettings.permissionRequired")}
        </CardTitle>
        <CardDescription>
          {initiative
            ? t("initiatives:settings.permissionRequiredDescription")
            : t("common:toolSettings.permissionRequiredDescription")}
        </CardDescription>
      </CardHeader>
    </Card>
  );
};
