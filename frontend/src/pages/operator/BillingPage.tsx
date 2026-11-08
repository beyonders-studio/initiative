/**
 * The operator dashboard's Billing tab: the ways into the billing service's
 * platform-wide pages.
 *
 * - **Insights** (`billing.insights`): how the business is doing, across every
 *   community. Read-only.
 * - **Contracts** (`billing.contracts`): the enterprise payers invoiced by
 *   hand — their terms, their invoices, and a dedicated deployment's
 *   registration key file. It writes, so it is its own capability.
 * - **Directory** (`billing.directory`, owners only): every account that pays,
 *   its communities, what comes next and what reconciliation found.
 *   Read-only; acting on an account goes through the consoles.
 * - **Control** (`billing.control`, owners only): where the deployment's plans
 *   are defined — what each allows, its words, the prices that sell it.
 *
 * Unlike the per-community billing buttons on the Communities tab, none
 * opens a community or takes an access grant: the handoff names only the
 * person opening it, and each page's audience is its own.
 */

import { BarChart3, BookUser, ExternalLink, FileText, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createBillingContractsHandoff,
  createBillingControlHandoff,
  createBillingDirectoryHandoff,
  createBillingInsightsHandoff,
} from "@/api/generated/settings/settings";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { openExternal, reserveTab } from "@/lib/openExternal";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";

type Door = "insights" | "contracts" | "directory" | "control";

const MINT: Record<Door, () => Promise<{ handoff_token: string }>> = {
  insights: createBillingInsightsHandoff,
  contracts: createBillingContractsHandoff,
  directory: createBillingDirectoryHandoff,
  control: createBillingControlHandoff,
};

const OPEN_ERROR: Record<Door, string> = {
  insights: "settings:billingInsights.openError",
  contracts: "settings:billingContracts.openError",
  directory: "settings:billingDirectory.openError",
  control: "settings:billingControl.openError",
};

export const BillingPage = () => {
  const { t, i18n } = useTranslation("settings");
  const { user } = useAuth();
  const { billing } = useAppConfig();
  const [opening, setOpening] = useState<Door | null>(null);

  const canInsights = hasCapability(user, Capability.billingInsights);
  const canContracts = hasCapability(user, Capability.billingContracts);
  const canDirectory = hasCapability(user, Capability.billingDirectory);
  const canControl = hasCapability(user, Capability.billingControl);
  if (!canInsights && !canContracts && !canDirectory && !canControl) {
    return <p className="text-muted-foreground text-sm">{t("billingInsights.platformOnly")}</p>;
  }

  const open = async (door: Door) => {
    if (!billing) return;
    setOpening(door);
    // Opened inside the click, before the request, so it is not a popup.
    const tab = reserveTab();
    try {
      const { handoff_token } = await MINT[door]();
      const lang = i18n.resolvedLanguage ?? i18n.language;
      // The token rides in the fragment, which never leaves the browser.
      const url = `${billing.url.replace(/\/+$/, "")}/${door}?lang=${encodeURIComponent(
        lang
      )}#${door}_handoff=${encodeURIComponent(handoff_token)}`;
      openExternal(url, tab);
    } catch (err) {
      tab?.close();
      toast.error(getErrorMessage(err, OPEN_ERROR[door]));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="space-y-6">
      {canInsights && (
        <SettingsSection
          title={
            <span className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" aria-hidden />
              {t("billingInsights.title")}
            </span>
          }
          description={t("billingInsights.description")}
        >
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground text-sm">
            <li>{t("billingInsights.fromPaddle")}</li>
            <li>{t("billingInsights.fromBilling")}</li>
            <li>{t("billingInsights.noCommunity")}</li>
          </ul>
          {billing?.insights ? (
            <Button onClick={() => void open("insights")} disabled={opening !== null}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              {opening === "insights" ? t("billingInsights.opening") : t("billingInsights.open")}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("billingInsights.notConfigured")}</p>
          )}
        </SettingsSection>
      )}
      {canContracts && (
        <SettingsSection
          title={
            <span className="flex items-center gap-2">
              <FileText className="h-5 w-5" aria-hidden />
              {t("billingContracts.title")}
            </span>
          }
          description={t("billingContracts.description")}
        >
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground text-sm">
            <li>{t("billingContracts.invoices")}</li>
            <li>{t("billingContracts.keys")}</li>
            <li>{t("billingContracts.noCommunity")}</li>
          </ul>
          {billing?.contracts ? (
            <Button onClick={() => void open("contracts")} disabled={opening !== null}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              {opening === "contracts" ? t("billingInsights.opening") : t("billingContracts.open")}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("billingInsights.notConfigured")}</p>
          )}
        </SettingsSection>
      )}
      {canDirectory && (
        <SettingsSection
          title={
            <span className="flex items-center gap-2">
              <BookUser className="h-5 w-5" aria-hidden />
              {t("billingDirectory.title")}
            </span>
          }
          description={t("billingDirectory.description")}
        >
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground text-sm">
            <li>{t("billingDirectory.lists")}</li>
            <li>{t("billingDirectory.readOnly")}</li>
            <li>{t("billingDirectory.ownersOnly")}</li>
          </ul>
          {billing?.directory ? (
            <Button onClick={() => void open("directory")} disabled={opening !== null}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              {opening === "directory" ? t("billingInsights.opening") : t("billingDirectory.open")}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("billingInsights.notConfigured")}</p>
          )}
        </SettingsSection>
      )}
      {canControl && (
        <SettingsSection
          title={
            <span className="flex items-center gap-2">
              <SlidersHorizontal className="h-5 w-5" aria-hidden />
              {t("billingControl.title")}
            </span>
          }
          description={t("billingControl.description")}
        >
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground text-sm">
            <li>{t("billingControl.revisions")}</li>
            <li>{t("billingControl.ownersOnly")}</li>
            <li>{t("billingControl.noCommunity")}</li>
          </ul>
          {billing?.control ? (
            <Button onClick={() => void open("control")} disabled={opening !== null}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              {opening === "control" ? t("billingInsights.opening") : t("billingControl.open")}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("billingInsights.notConfigured")}</p>
          )}
        </SettingsSection>
      )}
    </div>
  );
};
