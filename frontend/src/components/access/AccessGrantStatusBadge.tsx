/**
 * Where an access grant stands, as a badge. Shared by the Access tab and the
 * case panel, which lists the grants asked for on a case.
 */
import { useTranslation } from "react-i18next";

import type { AccessGrantRead, AccessGrantStatus } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";

const STATUS_VARIANT: Record<
  AccessGrantStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  pending: "secondary",
  approved: "default",
  denied: "destructive",
  revoked: "destructive",
  expired: "outline",
};

export const AccessGrantStatusBadge = ({ grant }: { grant: Pick<AccessGrantRead, "status"> }) => {
  const { t } = useTranslation("settings");
  return (
    <Badge variant={STATUS_VARIANT[grant.status]}>{t(`accessGrants.status.${grant.status}`)}</Badge>
  );
};
