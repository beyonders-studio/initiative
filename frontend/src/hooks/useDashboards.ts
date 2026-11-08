import {
  getReadDashboardQueryKey,
  setViewMode,
  upgradeDashboard,
  useReadInstalledListings,
  useReadWidgetCatalog,
} from "@/api/generated/dashboards/dashboards";
import type {
  DashboardInstalledListings,
  DashboardRead,
  DashboardViewMode,
  WidgetCatalog,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const dashboards = TOOL_HOOKS[Tool.dashboard];
export const useDashboardsList = dashboards.useList;
export const useDashboard = dashboards.useDetail;
export const useCreateDashboard = dashboards.useCreate;
export const useUpdateDashboard = dashboards.useUpdate;
export const useDeleteDashboard = dashboards.useDelete;
export const useSetDashboardGrants = dashboards.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * The widget vocabulary this build supports — size floors, bindable sources,
 * and options per primitive, plus the named presets.
 *
 * Served rather than duplicated: the backend's ``WIDGET_SPECS`` is the authority
 * on which widgets exist and what each may bind to, so the palette and the
 * canvas read it from here instead of carrying a second copy. Static for the
 * life of a deployment, hence the long stale time.
 */
export const useWidgetCatalog = (options?: QueryOpts<WidgetCatalog>) => {
  const communityId = useActiveCommunityId();
  return useReadWidgetCatalog(communityId, {
    query: { staleTime: Number.POSITIVE_INFINITY, ...options },
  });
};

/**
 * Which marketplace listings this community has installed, and how many of each.
 *
 * Keyed by the listing uid an install pins. Separate from the dashboards list on
 * purpose: that list is paginated, and deriving "already installed" from one
 * page would mark some installs and miss the rest.
 */
export const useInstalledListings = (options?: QueryOpts<DashboardInstalledListings>) => {
  const communityId = useActiveCommunityId();
  return useReadInstalledListings(communityId, { query: options });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateDashboardAndList = (dashboardId: number) =>
  invalidate(q.dashboard(dashboardId), q.allDashboards());

/**
 * Take the version a listing currently publishes.
 *
 * Only ever explicit: a new version sits in the catalog until someone with
 * write access on this dashboard asks for it, and applying it re-pins this
 * instance alone.
 */
export const useUpgradeDashboard = (
  dashboardId: number,
  options?: MutationOpts<DashboardRead, void>
) => {
  const communityId = useActiveCommunityId();
  return useCommunityMutation<DashboardRead, void>(
    {
      mutationFn: (communityId) => upgradeDashboard(communityId, dashboardId),
      invalidate: (updated) => {
        queryClient.setQueryData(getReadDashboardQueryKey(communityId, dashboardId), updated);
        return invalidateDashboardAndList(dashboardId);
      },
      errorKey: "marketplace:update.failed",
    },
    options
  );
};

/**
 * Whose access this dashboard's widgets run as: each viewer's own, or full
 * read access to the initiative, the same for everyone.
 */
export const useSetDashboardViewMode = (
  dashboardId: number,
  options?: MutationOpts<DashboardRead, DashboardViewMode>
) =>
  useCommunityMutation<DashboardRead, DashboardViewMode>(
    {
      mutationFn: (communityId, mode) => setViewMode(communityId, dashboardId, { mode }),
      invalidate: () => invalidateDashboardAndList(dashboardId),
      errorKey: "dashboards:error",
    },
    options
  );
