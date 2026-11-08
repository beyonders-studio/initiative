/**
 * "Run dashboard as": each viewer's own access, or the initiative's.
 *
 * Sits inline in the dashboard's Details form and saves on change. "Initiative"
 * runs the widgets with full read access to the initiative, whoever turned it
 * on. Choosing it takes an initiative role permission that managers always
 * hold; anybody who can edit the dashboard may switch it back.
 */

import { useTranslation } from "react-i18next";

import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";
import { DashboardViewMode } from "@/api/generated/initiativeAPI.schemas";
import { useSetDashboardViewMode } from "@/hooks/useDashboards";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

export function DashboardViewModeField({ dashboard }: { dashboard: DashboardRead }) {
  const { t } = useTranslation("dashboards");
  const setMode = useSetDashboardViewMode(dashboard.id);
  const mode = dashboard.view_mode;
  const canEdit = dashboard.can.edit;
  const mayChooseInitiative = dashboard.can_run_as_initiative;

  return (
    <div className="space-y-2">
      <Label htmlFor="dashboard-view-mode">{t("viewMode.label")}</Label>
      <Select
        value={mode}
        onValueChange={(next) => setMode.mutate(next as DashboardViewMode)}
        disabled={!canEdit || setMode.isPending}
      >
        <SelectTrigger id="dashboard-view-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DashboardViewMode.individual}>{t("viewMode.individual")}</SelectItem>
          <SelectItem value={DashboardViewMode.initiative} disabled={!mayChooseInitiative}>
            {t("viewMode.initiative")}
          </SelectItem>
        </SelectContent>
      </Select>
      <p
        className={
          mode === DashboardViewMode.initiative
            ? "text-amber-700 text-xs dark:text-amber-400"
            : "text-muted-foreground text-xs"
        }
      >
        {mode === DashboardViewMode.initiative
          ? t("viewMode.initiativeHint")
          : t("viewMode.individualHint")}
      </p>
      {canEdit && !mayChooseInitiative && (
        <p className="text-muted-foreground text-xs">{t("viewMode.notAllowed")}</p>
      )}
    </div>
  );
}
