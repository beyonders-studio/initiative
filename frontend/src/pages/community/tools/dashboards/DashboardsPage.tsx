import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/pages/community/tools/ToolIndexPage";

type DashboardsViewProps = {
  /** The initiative this list belongs to. Required: dashboards are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's dashboards, as cards.
 *
 * A tool with a marketplace shelf of its own, so the list and its empty state
 * both offer browsing it — the other way to end up with a dashboard.
 */
export const DashboardsView = (props: DashboardsViewProps) => (
  <ToolIndexPage tool={Tool.dashboard} {...props} />
);
