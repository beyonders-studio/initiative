/**
 * Archiving, for anything that can be finished with.
 *
 * The backend mounts one pair of routes for every archivable kind, at the
 * kind's own path (`/{kind}/{id}/archive`, `…/unarchive`), so this is one pair
 * of hooks rather than a pair per tool. Pass the kind and the id.
 *
 * Archived content is read-only all the way down, so what a successful call
 * changes is not only the row it named — every list and detail view that could
 * be showing something inside it is stale too, which is why this invalidates
 * broadly rather than by kind.
 */
import {
  archiveCalendar,
  archiveCollection,
  archiveContact,
  archiveCounterGroup,
  archiveDashboard,
  archiveFile,
  archiveInitiative,
  archivePost,
  archiveProject,
  archiveTask,
  archiveWiki,
  unarchiveCalendar,
  unarchiveCollection,
  unarchiveContact,
  unarchiveCounterGroup,
  unarchiveDashboard,
  unarchiveFile,
  unarchiveInitiative,
  unarchivePost,
  unarchiveProject,
  unarchiveTask,
  unarchiveWiki,
} from "@/api/generated/archive/archive";
import type { ArchivableType, ArchiveResponse } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

export type ArchiveTarget = { entityType: ArchivableType; entityId: number };

type ArchiveCall = (communityId: number, id: number) => Promise<ArchiveResponse>;

/** Each kind's `POST /{kind}/{id}/archive`. */
const ARCHIVE: Record<ArchivableType, ArchiveCall> = {
  project: archiveProject,
  file: archiveFile,
  counter_group: archiveCounterGroup,
  calendar: archiveCalendar,
  dashboard: archiveDashboard,
  post: archivePost,
  wiki: archiveWiki,
  contact: archiveContact,
  task: archiveTask,
  collection: archiveCollection,
  initiative: archiveInitiative,
};

/** Each kind's `POST /{kind}/{id}/unarchive`. */
const UNARCHIVE: Record<ArchivableType, ArchiveCall> = {
  project: unarchiveProject,
  file: unarchiveFile,
  counter_group: unarchiveCounterGroup,
  calendar: unarchiveCalendar,
  dashboard: unarchiveDashboard,
  post: unarchivePost,
  wiki: unarchiveWiki,
  contact: unarchiveContact,
  task: unarchiveTask,
  collection: unarchiveCollection,
  initiative: unarchiveInitiative,
};

// Everything the community shows. Not a wide net for its own sake: archiving
// cascades, so an initiative going away takes every tool in it and a project
// takes its tasks, and the row's own detail changes state as well as its list.
// The hand-written four this used to name predated archiving reaching every
// tool, so a wiki kept showing the state it had before the call.
const refresh = () => invalidate(q.communityContent());

export const useArchiveEntity = (options?: MutationOpts<ArchiveResponse, ArchiveTarget>) =>
  useCommunityMutation<ArchiveResponse, ArchiveTarget>(
    {
      mutationFn: (communityId, { entityType, entityId }) =>
        ARCHIVE[entityType](communityId, entityId),
      invalidate: refresh,
      errorKey: "common:archiveError",
    },
    options
  );

export const useUnarchiveEntity = (options?: MutationOpts<ArchiveResponse, ArchiveTarget>) =>
  useCommunityMutation<ArchiveResponse, ArchiveTarget>(
    {
      mutationFn: (communityId, { entityType, entityId }) =>
        UNARCHIVE[entityType](communityId, entityId),
      invalidate: refresh,
      errorKey: "common:unarchiveError",
    },
    options
  );
