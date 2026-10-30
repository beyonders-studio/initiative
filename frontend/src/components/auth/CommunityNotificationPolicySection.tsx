/**
 * Community → Security: what this community's notifications may leave the app
 * carrying.
 *
 * The same three questions the deployment answers for everybody, asked again
 * of one community. The stricter of the pair applies, so this surface only
 * ever narrows: where the deployment has already declined a channel, or
 * already asked for redacted notifications, the switch says so instead of
 * offering the same answer twice.
 *
 * The bell inside the app is unaffected, and so is what an account is sent
 * about itself.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityAuthSettingsUpdate } from "@/api/generated/initiativeAPI.schemas";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useCommunityAuthSettings,
  useUpdateCommunityAuthSettings,
} from "@/hooks/useCommunityAuthPolicy";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

export const CommunityNotificationPolicySection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const query = useCommunityAuthSettings(communityId);
  const update = useUpdateCommunityAuthSettings(communityId);
  const [error, setError] = useState<string | null>(null);

  const saved = query.data;
  if (!saved) return null;

  // What whoever runs the server sets for this community is shown, not offered.
  const fixed = (key: string) => saved.set_by_deployment.includes(key);
  const fixedHelp = t("communityAuth.setByDeployment");

  // Each switch saves as it is flipped, sending only its own answer.
  const flip = (patch: CommunityAuthSettingsUpdate) => {
    setError(null);
    update.mutate(patch, {
      onSuccess: () => {
        toast.success(t("communityNotifications.saved"));
      },
      onError: (err: unknown) => {
        setError(getErrorMessage(err, "settings:communityNotifications.error"));
      },
    });
  };

  const rows = [
    {
      id: "community-push-notifications",
      label: t("communityNotifications.push.label"),
      // A deployment that sends no push at all has already answered this, so
      // the line says that rather than describing a choice nobody has.
      help: !saved.push_allowed_by_platform
        ? t("communityNotifications.push.platformHelp")
        : fixed("allow_push_notifications")
          ? fixedHelp
          : saved.allow_push_notifications
            ? t("communityNotifications.push.onHelp")
            : t("communityNotifications.push.offHelp"),
      checked: saved.allow_push_notifications && saved.push_allowed_by_platform,
      settled: !saved.push_allowed_by_platform || fixed("allow_push_notifications"),
      change: (next: boolean) => flip({ allow_push_notifications: next }),
    },
    {
      id: "community-email-notifications",
      label: t("communityNotifications.email.label"),
      help: !saved.email_allowed_by_platform
        ? t("communityNotifications.email.platformHelp")
        : fixed("allow_email_notifications")
          ? fixedHelp
          : saved.allow_email_notifications
            ? t("communityNotifications.email.onHelp")
            : t("communityNotifications.email.offHelp"),
      checked: saved.allow_email_notifications && saved.email_allowed_by_platform,
      settled: !saved.email_allowed_by_platform || fixed("allow_email_notifications"),
      change: (next: boolean) => flip({ allow_email_notifications: next }),
    },
    {
      id: "community-redact-notifications",
      label: t("communityNotifications.redact.label"),
      help: saved.redacted_by_platform
        ? t("communityNotifications.redact.platformHelp")
        : fixed("redact_notification_content")
          ? fixedHelp
          : saved.redact_notification_content
            ? t("communityNotifications.redact.onHelp")
            : t("communityNotifications.redact.offHelp"),
      checked: saved.redact_notification_content || saved.redacted_by_platform,
      settled: saved.redacted_by_platform || fixed("redact_notification_content"),
      change: (next: boolean) => flip({ redact_notification_content: next }),
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityNotifications.title")}</CardTitle>
        <CardDescription>{t("communityNotifications.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {rows.map((row) => (
          <div key={row.id} className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor={row.id} className="font-medium">
                {row.label}
              </Label>
              <p className="text-muted-foreground text-sm">{row.help}</p>
            </div>
            <Switch
              id={row.id}
              checked={row.checked}
              onCheckedChange={row.change}
              disabled={update.isPending || row.settled}
            />
          </div>
        ))}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
