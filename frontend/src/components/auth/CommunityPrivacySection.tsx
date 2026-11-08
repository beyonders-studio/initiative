/**
 * Community → Security: what leaves the community, and what it keeps about
 * activity.
 *
 * The three notification questions the deployment answers for everybody,
 * asked again of one community; whether AI features may send its content to a
 * provider at all; and whether search orders its content by how many members
 * engaged with it lately. Each narrows what the server offers and never widens
 * it, so where the server has already answered, or set the answer for this
 * community, the row shows that answer instead of a switch.
 *
 * The bell inside the app is unaffected, and so is what an account is sent
 * about itself. Each switch saves as it is flipped.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityAuthSettingsRead,
  CommunityAuthSettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useUpdateCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Alert, AlertDescription } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Switch } from "@/ui/switch";

type PrivacyRule = keyof Pick<
  CommunityAuthSettingsUpdate,
  | "allow_push_notifications"
  | "allow_email_notifications"
  | "redact_notification_content"
  | "allow_ai"
  | "allow_engagement_ranking"
>;

export const CommunityPrivacySection = ({
  communityId,
  communityName,
  settings,
}: {
  communityId: number;
  communityName: string;
  settings: CommunityAuthSettingsRead;
}) => {
  const { t } = useTranslation("settings");
  const update = useUpdateCommunityAuthSettings(communityId);
  const [error, setError] = useState<string | null>(null);

  // What whoever runs the server sets for this community is shown, not offered.
  const fixed = (key: PrivacyRule) => settings.set_by_deployment.includes(key);

  const save = (key: PrivacyRule, next: boolean) => {
    setError(null);
    update.mutate({ [key]: next } as CommunityAuthSettingsUpdate, {
      onSuccess: () => {
        toast.success(t("communityPrivacy.saved"));
        if (key === "allow_ai") {
          // The AI buttons read whether AI is on here, and turning it off
          // turns the community's connections off.
          void invalidate(q.resolvedAISettings());
          void invalidate(q.communityAIConnections());
        }
      },
      onError: (err: unknown) => setError(getErrorMessage(err, "settings:communityPrivacy.error")),
    });
  };

  const push = settings.allow_push_notifications && settings.push_allowed_by_platform;
  const email = settings.allow_email_notifications && settings.email_allowed_by_platform;
  const redact = settings.redact_notification_content || settings.redacted_by_platform;
  const ranking =
    settings.allow_engagement_ranking && settings.engagement_ranking_allowed_by_platform;

  // `platform` is the server's answer for every community, which leaves
  // nothing here to decide; it says why in place of the row's own help.
  const rows: {
    key: PrivacyRule;
    label: string;
    on: boolean;
    help: string;
    platform: string | null;
  }[] = [
    {
      key: "allow_push_notifications",
      label: t("communityPrivacy.push.label"),
      on: push,
      help: push ? t("communityPrivacy.push.onHelp") : t("communityPrivacy.push.offHelp"),
      platform: settings.push_allowed_by_platform ? null : t("communityPrivacy.push.platformHelp"),
    },
    {
      key: "allow_email_notifications",
      label: t("communityPrivacy.email.label"),
      on: email,
      help: email ? t("communityPrivacy.email.onHelp") : t("communityPrivacy.email.offHelp"),
      platform: settings.email_allowed_by_platform
        ? null
        : t("communityPrivacy.email.platformHelp"),
    },
    {
      key: "redact_notification_content",
      label: t("communityPrivacy.redact.label"),
      on: redact,
      help: redact ? t("communityPrivacy.redact.onHelp") : t("communityPrivacy.redact.offHelp"),
      platform: settings.redacted_by_platform ? t("communityPrivacy.redact.platformHelp") : null,
    },
    ...(settings.ai_offered_by_platform
      ? [
          {
            key: "allow_ai" as const,
            label: t("communityPrivacy.ai.label"),
            on: settings.allow_ai,
            help: t("communityPrivacy.ai.help"),
            platform: null,
          },
        ]
      : []),
    {
      key: "allow_engagement_ranking",
      label: t("communityPrivacy.ranking.label"),
      on: ranking,
      help: t("communityPrivacy.ranking.help"),
      platform: settings.engagement_ranking_allowed_by_platform
        ? null
        : t("communityPrivacy.ranking.platformHelp"),
    },
  ];

  return (
    <SettingsSection
      title={t("communityPrivacy.title")}
      description={t("communityPrivacy.description", { community: communityName })}
    >
      {rows.map((row) =>
        row.platform !== null || fixed(row.key) ? (
          <SettingsRow
            key={row.key}
            label={row.label}
            description={
              <>
                <span className="text-foreground">
                  {row.on ? t("communityAuth.on") : t("communityAuth.off")}
                </span>
                {row.platform ? ` · ${row.platform}` : null}
              </>
            }
          >
            <Badge variant="secondary">{t("communityAuth.setByServer")}</Badge>
          </SettingsRow>
        ) : (
          <SettingsRow
            key={row.key}
            label={row.label}
            description={row.help}
            htmlFor={`community-${row.key}`}
          >
            <Switch
              id={`community-${row.key}`}
              checked={row.on}
              onCheckedChange={(next) => save(row.key, next)}
              disabled={update.isPending}
            />
          </SettingsRow>
        )
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </SettingsSection>
  );
};
