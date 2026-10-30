/**
 * Platform → Security: whether a new password is checked against the list of
 * passwords already exposed in breaches.
 *
 * Only the first five characters of the password's hash leave the server.
 * Off is for a deployment that cannot reach the list.
 */

import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { usePlatformAuthSettings, useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

export const BreachedPasswordCheckSection = () => {
  const { t } = useTranslation("settings");
  const query = usePlatformAuthSettings();
  const update = useUpdatePlatformAuthSettings({
    onSuccess: (result) =>
      toast.success(
        result.breached_password_check_enabled
          ? t("auth.breachedPasswordCheck.enabledToast")
          : t("auth.breachedPasswordCheck.disabledToast")
      ),
    onError: (err) =>
      toast.error(getErrorMessage(err, "settings:auth.breachedPasswordCheck.error")),
  });

  const saved = query.data;
  if (!saved) return null;

  return (
    <SettingsSection
      title={t("auth.breachedPasswordCheck.title")}
      description={t("auth.breachedPasswordCheck.description")}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label htmlFor="breached-password-check" className="font-medium">
            {t("auth.breachedPasswordCheck.label")}
          </Label>
          <p className="text-muted-foreground text-sm">
            {saved.breached_password_check_enabled
              ? t("auth.breachedPasswordCheck.onHelp")
              : t("auth.breachedPasswordCheck.offHelp")}
          </p>
        </div>
        <Switch
          id="breached-password-check"
          checked={saved.breached_password_check_enabled}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate({ breached_password_check_enabled: Boolean(checked) })
          }
        />
      </div>
    </SettingsSection>
  );
};
