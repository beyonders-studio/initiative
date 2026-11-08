import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { AgeConfirmationForm } from "@/components/connections/UnreachableEmptyState";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useDmSettings, useUpdateDmSettings } from "@/hooks/useDirectMessages";
import { usePrivacySections } from "@/hooks/usePrivacySections";
import { toast } from "@/lib/mascotToast";
import { ConnectionRequestsSection } from "@/pages/my/settings/privacy/ConnectionRequestsSection";
import { ConnectionsSection } from "@/pages/my/settings/privacy/ConnectionsSection";
import { CookieChoicesSection } from "@/pages/my/settings/privacy/CookieChoicesSection";
import { DirectMessagePolicyField } from "@/pages/my/settings/privacy/DirectMessagePolicyField";
import { EngagementRankingSection } from "@/pages/my/settings/privacy/EngagementRankingSection";
import { IgnoredAccountsSection } from "@/pages/my/settings/privacy/IgnoredAccountsSection";
import { Switch } from "@/ui/switch";

/**
 * What this account keeps to itself: who may reach it, whether its activity
 * counts toward search ranking, and what this browser allows. Each section
 * shows where it has something to set (``usePrivacySections``).
 */
export const PrivacyPage = () => {
  const shown = usePrivacySections();
  return (
    <div className="space-y-6">
      {shown.messages && <MessagingSections />}
      {shown.ranking && <EngagementRankingSection />}
      {shown.cookies && <CookieChoicesSection />}
    </div>
  );
};

/**
 * Who may reach this account.
 *
 * The policy says who may ask; the three lists under it are the standing
 * exceptions to it — connections ask whatever it says, pending requests are
 * asking to become one of those, and ignored accounts are the refusal that
 * outranks all of it. Read top to bottom the sections answer one question.
 */
const MessagingSections = () => {
  const { t } = useTranslation("settings");
  const { data, isLoading } = useDmSettings();
  const updateSettings = useUpdateDmSettings();

  // The age question gates everything where the deployment checks age — there
  // is no policy to choose while it is owed.
  const ageConfirmed = data !== undefined && !data.age_answer_required;

  const save = (body: Parameters<typeof updateSettings.mutate>[0]["data"]) =>
    updateSettings.mutate(
      { data: body },
      { onSuccess: () => toast.success(t("privacy.dm.saved")) }
    );

  return (
    <>
      <SettingsSection title={t("privacy.dm.title")} description={t("privacy.dm.description")}>
        {/* The age question gates the policy, so it is answered here, where
            the policy is set. */}
        {!ageConfirmed && !isLoading && (
          <div className="space-y-3 rounded-md border border-dashed p-3">
            <p className="max-w-prose text-muted-foreground text-sm">{t("privacy.dm.ageLocked")}</p>
            <AgeConfirmationForm id="settings-age" />
          </div>
        )}
        <DirectMessagePolicyField
          policy={(data?.dm_policy ?? "private") as DmPolicy}
          communities={data?.communities ?? []}
          disabled={!ageConfirmed || updateSettings.isPending}
          onPolicyChange={(policy) => save({ dm_policy: policy })}
          onCommunityChange={(communityId, enabled) =>
            save({ communities: [{ community_id: communityId, enabled }] })
          }
        />
        <div className="border-t pt-4">
          <SettingsRow label={t("privacy.receipts.label")} description={t("privacy.receipts.help")}>
            <Switch
              checked={data?.send_receipts ?? true}
              disabled={isLoading || updateSettings.isPending}
              onCheckedChange={(checked) => save({ send_receipts: checked })}
            />
          </SettingsRow>
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("privacy.connections.title")}
        description={t("privacy.connections.description")}
      >
        <ConnectionsSection />
        <div className="space-y-2 border-t pt-4">
          <p className="font-medium text-sm">{t("privacy.requests.title")}</p>
          <ConnectionRequestsSection />
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("privacy.ignored.title")}
        description={t("privacy.ignored.description")}
      >
        <IgnoredAccountsSection />
      </SettingsSection>
    </>
  );
};
