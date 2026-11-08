/**
 * Platform → Security: whether a new password is checked against the list of
 * passwords already exposed in breaches.
 *
 * Only the first five characters of the password's hash leave the server.
 * Off is for a deployment that cannot reach the list.
 */

import { useTranslation } from "react-i18next";

import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { usePlatformAuthSettings, useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Switch } from "@/ui/switch";

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
      <SettingsRow
        label={t("auth.breachedPasswordCheck.label")}
        description={
          saved.breached_password_check_enabled
            ? t("auth.breachedPasswordCheck.onHelp")
            : t("auth.breachedPasswordCheck.offHelp")
        }
      >
        <Switch
          checked={saved.breached_password_check_enabled}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate({ breached_password_check_enabled: Boolean(checked) })
          }
        />
      </SettingsRow>
    </SettingsSection>
  );
};
