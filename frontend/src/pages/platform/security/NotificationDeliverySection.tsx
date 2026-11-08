/**
 * Platform → Security: what a notification may leave the app carrying.
 *
 * Three answers — whether one may reach a phone, whether one may reach a
 * mailbox, and whether what it says may name the thing it is about. Every
 * community is asked the same three on its own Security page, and the stricter
 * of the pair applies, so these are the ceiling for the whole deployment.
 *
 * None of it touches the bell inside the app, and none of it touches what an
 * account is sent about itself: a sign-in code, an address to confirm and a
 * password reset are not notifications.
 */

import { useTranslation } from "react-i18next";

import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useNotificationSettings, useUpdateNotificationSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Switch } from "@/ui/switch";

export const NotificationDeliverySection = () => {
  const { t } = useTranslation("settings");
  const query = useNotificationSettings();
  const update = useUpdateNotificationSettings({
    onSuccess: () => toast.success(t("notificationDelivery.saved")),
  });

  const saved = query.data;
  if (!saved) return null;

  // Each switch saves as it is flipped, and the three go in one write, so the
  // other two are sent as they stand.
  const flip = (patch: {
    push_notifications_enabled?: boolean;
    email_notifications_enabled?: boolean;
    redact_notification_content?: boolean;
  }) => {
    update.mutate({
      push_notifications_enabled: saved.push_notifications_enabled,
      email_notifications_enabled: saved.email_notifications_enabled,
      redact_notification_content: saved.redact_notification_content,
      ...patch,
    });
  };

  const rows = [
    {
      id: "platform-push-notifications",
      label: t("notificationDelivery.push.label"),
      help: saved.push_notifications_enabled
        ? t("notificationDelivery.push.onHelp")
        : t("notificationDelivery.push.offHelp"),
      checked: saved.push_notifications_enabled,
      change: (next: boolean) => flip({ push_notifications_enabled: next }),
    },
    {
      id: "platform-email-notifications",
      label: t("notificationDelivery.email.label"),
      help: saved.email_notifications_enabled
        ? t("notificationDelivery.email.onHelp")
        : t("notificationDelivery.email.offHelp"),
      checked: saved.email_notifications_enabled,
      change: (next: boolean) => flip({ email_notifications_enabled: next }),
    },
    {
      id: "platform-redact-notifications",
      label: t("notificationDelivery.redact.label"),
      help: saved.redact_notification_content
        ? t("notificationDelivery.redact.onHelp")
        : t("notificationDelivery.redact.offHelp"),
      checked: saved.redact_notification_content,
      change: (next: boolean) => flip({ redact_notification_content: next }),
    },
  ];

  return (
    <SettingsSection
      title={t("notificationDelivery.title")}
      description={t("notificationDelivery.description")}
    >
      {rows.map((row) => (
        <SettingsRow key={row.id} label={row.label} description={row.help}>
          <Switch checked={row.checked} onCheckedChange={row.change} disabled={update.isPending} />
        </SettingsRow>
      ))}
    </SettingsSection>
  );
};
