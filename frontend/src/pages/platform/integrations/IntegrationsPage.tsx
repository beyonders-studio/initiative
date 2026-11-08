/**
 * Platform → Integrations: everything this deployment wires up to something
 * outside itself.
 *
 * Two halves under two capabilities. The AI settings and the marketplace
 * registry belong to `config.manage` and are a couple of choices each, so they
 * come first; the plug-in service registrations belong to `plugins.manage` and are a
 * list that grows, so they sit below. An operator holding one capability is shown that half alone rather
 * than the other half's refusal.
 */

import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";
import { AIPage } from "@/pages/platform/integrations/AIPage";
import { MarketplaceRegistrySection } from "@/pages/platform/integrations/MarketplaceRegistrySection";
import { PluginServicesPage } from "@/pages/platform/integrations/PluginServicesPage";

export const IntegrationsPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageConfig = hasCapability(user, Capability.configManage);
  const canManagePlugins = hasCapability(user, Capability.pluginsManage);

  if (!canManageConfig && !canManagePlugins) {
    return <p className="text-muted-foreground text-sm">{t("platformAI.platformOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      {canManageConfig ? <AIPage /> : null}
      {canManageConfig ? <MarketplaceRegistrySection /> : null}
      {canManagePlugins ? <PluginServicesPage /> : null}
    </div>
  );
};
