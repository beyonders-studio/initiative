/**
 * Plug-ins installed in the current community.
 *
 * Every member reads this — the sidebar has to know what is there — and no
 * guest does, the plug-ins being the community's rather than shared with them;
 * installing, renaming, disabling and removing are community-admin actions the
 * server enforces. The UI mirrors that by hiding the affordances, not by
 * deciding it.
 */

import type {
  CommunityPluginInstall,
  CommunityPluginListResponse,
  CommunityPluginRead,
  CommunityPluginUpdate,
  ItemKind,
  PluginActionResult,
} from "@/api/generated/initiativeAPI.schemas";
import {
  installCommunityPlugin,
  putCommunityPluginScopes,
  runPluginAction,
  uninstallCommunityPlugin,
  updateCommunityPlugin,
  useListCommunityPlugins,
  useReadUninstallNotice,
} from "@/api/generated/plugins/plugins";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

export const useCommunityPlugins = (options?: QueryOpts<CommunityPluginListResponse>) => {
  const communityId = useActiveCommunityId();
  const communityWide = Boolean(useCommunities().activeCommunity?.can.community_wide);
  const { enabled = true, ...rest } = options ?? {};
  return useListCommunityPlugins(communityId, {
    query: { enabled: enabled && communityWide, ...rest },
  });
};

/**
 * What the removal dialog says about one plug-in beyond the usual: asked when
 * the dialog opens, in the reader's language, and never cached past it.
 */
export const useUninstallNotice = (pluginId: number, locale: string, enabled: boolean) => {
  const communityId = useActiveCommunityId();
  return useReadUninstallNotice(
    communityId,
    pluginId,
    { locale },
    { query: { enabled, staleTime: 0, gcTime: 0, retry: false } }
  );
};

export const useInstallCommunityPlugin = (
  options?: MutationOpts<CommunityPluginRead, CommunityPluginInstall>
) => {
  return useCommunityMutation<CommunityPluginRead, CommunityPluginInstall>(
    {
      mutationFn: (communityId, data) => installCommunityPlugin(communityId, data),
      invalidate: () => invalidate(q.plugins()),
      errorKey: "plugins:error",
    },
    options
  );
};

export const useUpdateCommunityPlugin = (
  pluginId: number,
  options?: MutationOpts<CommunityPluginRead, CommunityPluginUpdate>
) => {
  return useCommunityMutation<CommunityPluginRead, CommunityPluginUpdate>(
    {
      mutationFn: (communityId, data) => updateCommunityPlugin(communityId, pluginId, data),
      invalidate: () => invalidate(q.plugins()),
      errorKey: "plugins:error",
    },
    options
  );
};

export interface UninstallPlugin {
  pluginId: number;
  /** Also ask the plug-in to delete what it holds about the community. */
  erase?: boolean;
}

export const useUninstallCommunityPlugin = (options?: MutationOpts<void, UninstallPlugin>) => {
  return useCommunityMutation<void, UninstallPlugin>(
    {
      mutationFn: (communityId, { pluginId, erase }) =>
        uninstallCommunityPlugin(communityId, pluginId, erase ? { erase: true } : undefined),
      invalidate: () => invalidate(q.plugins()),
      errorKey: "plugins:error",
    },
    options
  );
};

/** Grant the plug-in exactly these scopes; any left out are withdrawn. */
export const useSetPluginScopes = (
  pluginId: number,
  options?: MutationOpts<CommunityPluginRead, string[]>
) => {
  return useCommunityMutation<CommunityPluginRead, string[]>(
    {
      mutationFn: (communityId, granted) =>
        putCommunityPluginScopes(communityId, pluginId, { granted }),
      invalidate: () => invalidate(q.plugins()),
      errorKey: "plugins:scopes.error",
    },
    options
  );
};

/** The reads that show an item of each kind plug-ins draw on. */
const ITEM_READS: Record<ItemKind, (id: number) => Spec[]> = {
  task: (id) => [q.allTasks(), q.task(id)],
  calendar_event: (id) => [q.allCalendarEvents(), q.calendarEvent(id)],
  counter: (id) => [q.allCounterGroups(), q.counter(id)],
  post: (id) => [q.allPosts(), q.post(id)],
};

/** Run one of a plug-in's actions on an item, with what the reader answered
 *  for the parameters it asks for and the list element it was run from. The
 *  plug-in does the work; the item is read again for the values it shows
 *  afterwards. */
export const useRunPluginAction = () =>
  useCommunityMutation<
    PluginActionResult,
    {
      pluginId: number;
      actionId: string;
      kind: ItemKind;
      itemId: number;
      params?: Record<string, unknown>;
      element?: string;
    }
  >({
    mutationFn: (communityId, { pluginId, actionId, kind, itemId, params, element }) =>
      runPluginAction(communityId, pluginId, actionId, {
        entity_type: kind,
        entity_id: itemId,
        ...(params ? { params } : {}),
        ...(element ? { element } : {}),
      }),
    invalidate: (_data, { kind, itemId }) => invalidate(...ITEM_READS[kind](itemId)),
    errorKey: "plugins:error",
  });
