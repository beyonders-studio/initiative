import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { PersonRow } from "@/components/connections/PersonRow";
import { AgeConfirmationForm } from "@/components/connections/UnreachableEmptyState";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useConsent } from "@/hooks/useConsent";
import {
  useDmSettings,
  useIgnoreAccountByHandle,
  useIgnoredAccounts,
  useStopIgnoring,
  useUpdateDmSettings,
} from "@/hooks/useDirectMessages";
import { usePrivacySections } from "@/hooks/usePrivacySections";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { reopenConsent } from "@/lib/consent";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Switch } from "@/ui/switch";

import { ConnectionRequestsSection } from "./ConnectionRequestsSection";
import { ConnectionsSection } from "./ConnectionsSection";
import { DirectMessagePolicyField } from "./DirectMessagePolicyField";
import { HandleField } from "./HandleField";

/**
 * Whether what this person opens and changes counts toward the levels their
 * communities' search orders by. On until they turn it off, and theirs alone:
 * a community's own switch turns the ordering off for everybody in it.
 */
const EngagementRankingSection = () => {
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

/**
 * What this browser is currently allowing, and the way to change it.
 *
 * Here because a landing-page footer is no use to somebody already signed in
 * and three pages deep, and taking an answer back has to stay as easy as
 * giving one.
 *
 * Shown where ``usePrivacySections`` says there is something to change. It
 * reads this browser, which is what governs what loads here. The answer
 * also belongs to the account (see `useConsentSync`), so changing it here
 * reaches the other browsers this account signs in from.
 */
const CookieChoicesSection = () => {
  const { t } = useTranslation(["settings", "legal"]);
  const { cookieCategories } = useAppConfig();
  const { unanswered, granted } = useConsent();

  const allowed = cookieCategories.filter((category) => granted.includes(category));

  return (
    <SettingsSection title={t("settings:privacy.cookies.title")}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="max-w-prose text-muted-foreground text-sm">
            {unanswered
              ? t("settings:privacy.cookies.unanswered")
              : allowed.length === 0
                ? t("settings:privacy.cookies.noneAllowed")
                : t("settings:privacy.cookies.allowed", {
                    categories: allowed
                      .map((category) => t(`legal:cookies.categories.${category}.name`))
                      .join(", "),
                  })}
          </p>
          <p className="max-w-prose text-muted-foreground text-xs">
            {t("settings:privacy.cookies.perBrowser")}
          </p>
        </div>
        <Button variant="outline" onClick={reopenConsent} className="shrink-0">
          {t("settings:privacy.cookies.change")}
        </Button>
      </div>
    </SettingsSection>
  );
};

/** The accounts this person has chosen not to hear from. */
const IgnoredAccountsSection = () => {
  const { t } = useTranslation("settings");
  const { data } = useIgnoredAccounts();
  const ignoreByHandle = useIgnoreAccountByHandle();
  const stopIgnoring = useStopIgnoring();

  const items = data?.items ?? [];

  return (
    <div className="space-y-3">
      <HandleField
        label={t("privacy.ignored.add")}
        placeholder={t("privacy.connections.addPlaceholder")}
        hint={t("privacy.connections.addHint")}
        submitLabel={t("privacy.ignored.ignore")}
        errorFallback="errors:DM_USER_NOT_FOUND"
        pending={ignoreByHandle.isPending}
        onSubmit={(handle) => ignoreByHandle.mutateAsync({ data: handle })}
      />
      {items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("privacy.ignored.empty")}</p>
      ) : (
        <ul className="divide-y">
          {items.map((account) => (
            <PersonRow
              key={account.user_id}
              user={{
                id: account.user_id,
                username: account.username,
                discriminator: account.discriminator,
                avatar_url: account.avatar_url,
              }}
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => stopIgnoring.mutate({ userId: account.user_id })}
                disabled={stopIgnoring.isPending}
              >
                {t("privacy.ignored.stop")}
              </Button>
            </PersonRow>
          ))}
        </ul>
      )}
    </div>
  );
};

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
