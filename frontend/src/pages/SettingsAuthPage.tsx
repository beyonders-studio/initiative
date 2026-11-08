import { useTranslation } from "react-i18next";

import { AuthProvidersSection } from "@/components/platform/AuthProvidersSection";
import { PlatformAuthSection } from "@/components/platform/PlatformAuthSection";
import { ProviderDefaultsSection } from "@/components/platform/ProviderDefaultsSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useOidcSettings } from "@/hooks/useSettings";
import { Capability, hasCapability } from "@/lib/permissions";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

/**
 * Platform → Authentication.
 *
 * Two decisions that belong to the deployment — which ways in it permits, and
 * where sign-in is configured — then the providers, which are a list and
 * nothing else: the one an install started with is a row like any other, added
 * and edited the same way as the fifth. What is left beside the list belongs to
 * the install rather than to any provider: the two addresses every provider
 * shares.
 */
export const SettingsAuthPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const oidcQuery = useOidcSettings({ enabled: canManagePlatformConfig });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("auth.platformOnly")}</p>;
  }

  if (oidcQuery.isLoading) {
    return (
      <SkeletonRegion label={t("auth.loading")}>
        <FormSkeleton fields={5} />
      </SkeletonRegion>
    );
  }

  if (oidcQuery.isError || !oidcQuery.data) {
    return <StatusMessage onRetry={oidcQuery.refetch} />;
  }

  return (
    <div className="space-y-6">
      <PlatformAuthSection />

      <SettingsSection title={t("auth.deploymentTitle")}>
        {/* Shared by every provider, so stated once rather than on each. The
            per-provider callback lives on its row in the list below. */}
        <dl className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-muted-foreground">{t("auth.postLoginRedirect")}</dt>
            <dd>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {oidcQuery.data.post_login_redirect}
              </code>
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-muted-foreground">{t("auth.mobileCallback")}</dt>
            <dd>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {oidcQuery.data.mobile_redirect_uri}
              </code>
            </dd>
          </div>
        </dl>
      </SettingsSection>

      <AuthProvidersSection />

      <ProviderDefaultsSection />
    </div>
  );
};
