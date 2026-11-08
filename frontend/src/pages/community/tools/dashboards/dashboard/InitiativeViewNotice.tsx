/**
 * That these numbers are the same for everyone.
 *
 * A dashboard that runs as its initiative shows every reader rows they may not
 * reach anywhere else in the app. Saying so keeps a figure they cannot
 * reconcile with what they see elsewhere from reading as a bug.
 */

import { Eye } from "lucide-react";
import { useTranslation } from "react-i18next";

export function InitiativeViewNotice() {
  const { t } = useTranslation("dashboards");
  return (
    <p className="inline-flex items-center gap-1.5 text-muted-foreground text-xs">
      <Eye className="h-3.5 w-3.5" aria-hidden />
      {t("viewMode.notice")}
    </p>
  );
}
