import { PluginSummaryCards } from "@/components/communities/PluginSummaryCards";

import { CommunityBillingPanel } from "./CommunityBillingPanel";
import { CommunityUsagePanel } from "./CommunityUsagePanel";

/** The seat's Usage tab: usage against the caps on every install, where the
 *  community stands with each plug-in that says, and the plan below it where
 *  the deployment has a billing portal (the panel renders nothing without one). */
export const UsagePage = () => (
  <div className="space-y-6">
    <CommunityUsagePanel />
    <PluginSummaryCards />
    <CommunityBillingPanel />
  </div>
);
