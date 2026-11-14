import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";

import { ApprovalQueue } from "./ApprovalQueue";
import { BreakGlassSection } from "./BreakGlassSection";
import { RequestSection } from "./RequestSection";

export const AccessPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const canRequest = hasCapability(user, Capability.accessRequest);
  const canApprove = hasCapability(user, Capability.accessApprove);
  const canBreakGlass = hasCapability(user, Capability.dataBypass);

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground">{t("accessGrants.description")}</p>
      {canApprove && <ApprovalQueue />}
      {canBreakGlass && <BreakGlassSection />}
      {canRequest && <RequestSection />}
    </div>
  );
};
