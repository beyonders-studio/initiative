import { useTranslation } from "react-i18next";

import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/mascotToast";
import { Switch } from "@/ui/switch";

/**
 * Whether what this person opens and changes counts toward the levels their
 * communities' search orders by. On until they turn it off, and theirs alone:
 * a community's own switch turns the ordering off for everybody in it.
 */
export const EngagementRankingSection = () => {
  const { t } = useTranslation("settings");
  const { user, acceptUser } = useAuth();
  const update = useUpdateCurrentUser(
    {
      onSuccess: (saved) => {
        acceptUser(saved);
        toast.success(t("privacy.engagementRanking.saved"));
      },
    },
    "settings:privacy.engagementRanking.error"
  );

  if (!user) return null;

  return (
    <SettingsSection title={t("privacy.engagementRanking.title")}>
      <SettingsRow
        label={t("privacy.engagementRanking.label")}
        description={t("privacy.engagementRanking.help")}
      >
        <Switch
          checked={user.count_toward_engagement_ranking ?? true}
          disabled={update.isPending}
          onCheckedChange={(checked) => update.mutate({ count_toward_engagement_ranking: checked })}
        />
      </SettingsRow>
    </SettingsSection>
  );
};
