/**
 * Plug-ins installed in the current community.
 *
 * Every member reads this — the sidebar has to know what is there — and no
 * guest does, the plug-ins being the community's rather than shared with them;
 * installing, renaming, disabling and removing are community-admin actions the
 * server enforces. The UI mirrors that by hiding the affordances, not by
 * deciding it.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  CommunityPluginInstall,
  CommunityPluginListResponse,
  CommunityPluginRead,
  CommunityPluginUninstallNotice,
  CommunityPluginUpdate,
  ItemKind,
  PluginActionResult,
  PluginPlacementRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListCommunityPluginsQueryKey,
  getReadUninstallNoticeQueryKey,
  installCommunityPlugin,
  listCommunityPlugins,
  putCommunityPluginPlacement,
  putCommunityPluginScopes,
  readUninstallNotice,
  runPluginAction,
  uninstallCommunityPlugin,
  updateCommunityPlugin,
} from "@/api/generated/plugins/plugins";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const pluginsKey = (communityId: number) => getListCommunityPluginsQueryKey(communityId);

export const useCommunityPlugins = (options?: QueryOpts<CommunityPluginListResponse>) => {
  const communityId = useActiveCommunityId();
  const communityWide = Boolean(useCommunities().activeCommunity?.can.community_wide);
  const { enabled = true, ...rest } = options ?? {};
  return useQuery<CommunityPluginListResponse>({
    queryKey: pluginsKey(communityId),
    queryFn: () => listCommunityPlugins(communityId),
    enabled: enabled && communityWide,
    ...rest,
  });
};

/**
 * What the removal dialog says about one plug-in beyond the usual: asked when
 * the dialog opens, in the reader's language, and never cached past it.
 */
export const useUninstallNotice = (pluginId: number, locale: string, enabled: boolean) => {
  const communityId = useActiveCommunityId();
  return useQuery<CommunityPluginUninstallNotice>({
    queryKey: getReadUninstallNoticeQueryKey(communityId, pluginId, { locale }),
    queryFn: () => readUninstallNotice(communityId, pluginId, { locale }),
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
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

export interface PluginPlacementRoles {
  initiativeId: number;
  roleIds: number[];
}

/** Place the plug-in in one initiative with exactly these roles. */
export const useSetPluginPlacementRoles = (
  pluginId: number,
  options?: MutationOpts<PluginPlacementRead, PluginPlacementRoles>
) => {
  return useCommunityMutation<PluginPlacementRead, PluginPlacementRoles>(
    {
      mutationFn: (communityId, { initiativeId, roleIds }) =>
        putCommunityPluginPlacement(communityId, pluginId, initiativeId, { role_ids: roleIds }),
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
  queue_item: (id) => [q.allQueues(), q.queueItem(id)],
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
