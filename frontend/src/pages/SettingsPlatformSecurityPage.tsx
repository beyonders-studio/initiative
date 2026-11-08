/**
 * Platform → Security.
 *
 * What the deployment asks of everybody's sign-in, rather than how anybody
 * signs in — that is Authentication, next door. How long a session may last,
 * whether a new password is checked against known breaches, who has to hold a
 * second factor, the captcha asked of somebody new, and what a notification
 * may leave the app carrying.
 */

import { useTranslation } from "react-i18next";

import { BreachedPasswordCheckSection } from "@/components/platform/BreachedPasswordCheckSection";
import { CaptchaSection } from "@/components/platform/CaptchaSection";
import { NotificationDeliverySection } from "@/components/platform/NotificationDeliverySection";
import { SecondFactorMethodSection } from "@/components/platform/SecondFactorMethodSection";
import { SecondFactorRequirementSection } from "@/components/platform/SecondFactorRequirementSection";
import { SessionLifetimeSection } from "@/components/platform/SessionLifetimeSection";
import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";

export const SettingsPlatformSecurityPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();

  if (!hasCapability(user, Capability.configManage)) {
    return <p className="text-muted-foreground text-sm">{t("auth.platformOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">{t("platformSecurity.description")}</p>
      <SessionLifetimeSection />
      <BreachedPasswordCheckSection />
      {/* Offered first, then required: a rule needs something to answer it. */}
      <SecondFactorMethodSection />
      <SecondFactorRequirementSection />
      <CaptchaSection />
      <NotificationDeliverySection />
    </div>
  );
};
