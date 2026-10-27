export { buildActivityEntry } from "./activity.factory";
export {
  buildCalendarEvent,
  buildCalendarEventSummary,
  buildEventAttendee,
  resetCounter as resetCalendarEventCounter,
} from "./calendarEvent.factory";
export { ownerCan, readerCan, writerCan } from "./can";
export { buildCollection, buildCollectionFile } from "./collection.factory";
export {
  buildComment,
  buildReactionGroup,
  buildRecentActivityEntry,
  resetCounter as resetCommentCounter,
} from "./comment.factory";
export {
  buildBanner,
  buildCommunity,
  buildCommunityInviteStatus,
  communityCan,
  resetCounter as resetCommunityCounter,
} from "./community.factory";
export {
  buildContactGrant,
  buildIgnoredAccount,
  resetCounter as resetDmCounter,
} from "./dm.factory";
export { buildFileSummary, resetCounter as resetFileCounter } from "./file.factory";
export {
  buildInitiative,
  buildInitiativeDirectoryEntry,
  buildInitiativeJoinRequest,
  buildInitiativeMember,
  buildInitiativeRole,
  initiativeCan,
  resetCounter as resetInitiativeCounter,
} from "./initiative.factory";
export {
  buildMarketplaceListing,
  buildMarketplaceListingDetail,
  buildMarketplaceVersion,
  buildProjectListingEnvelope,
  resetCounter as resetMarketplaceCounter,
} from "./marketplace.factory";
export {
  buildNotification,
  buildNotificationPlace,
  resetCounter as resetNotificationCounter,
} from "./notification.factory";
export { buildPage } from "./page.factory";
export { buildLexicalBody, buildPoll, buildPollOption, buildPost } from "./post.factory";
export {
  buildDefaultTaskStatuses,
  buildProject,
  buildProjectTaskStatus,
  resetCounter as resetProjectCounter,
} from "./project.factory";
export {
  buildPropertyDefinition,
  buildPropertyOption,
  buildPropertySummary,
  resetCounter as resetPropertyCounter,
} from "./properties";
export {
  buildQueue,
  buildQueueItem,
  buildQueueListResponse,
  buildQueueSummary,
  resetCounter as resetQueueCounter,
} from "./queue.factory";
export {
  buildRecentCounterGroupItem,
  buildRecentFileItem,
  buildRecentItem,
  buildRecentProjectItem,
  buildRecentQueueItem,
  resetRecentCounter,
} from "./recent.factory";
export {
  buildSearchHit,
  buildSearchResults,
  buildSearchSuggestion,
  buildTaggedEntity,
  resetCounter as resetSearchCounter,
} from "./search.factory";
export { buildTag, buildTagSummary, resetCounter as resetTagCounter } from "./tag.factory";
export {
  buildTask,
  buildTaskAssignee,
  buildTaskListResponse,
  resetCounter as resetTaskCounter,
  TASK_GROUPINGS,
} from "./task.factory";
export {
  buildDefaultTaskTypes,
  buildTaskType,
  resetCounter as resetTaskTypeCounter,
} from "./taskType.factory";
export { buildSavedLayoutSet, buildToolLayoutSet } from "./toolLayout.factory";
export {
  buildOwnedDecoration,
  buildUser,
  buildUserCommunityMember,
  buildUserEmail,
  buildUserProfile,
  buildUserPublic,
  buildUserSummary,
  resetCounter as resetUserCounter,
} from "./user.factory";
export { buildWiki, buildWikiPage } from "./wiki.factory";

import { resetCounter as resetCalendarEventCounter } from "./calendarEvent.factory";
import { resetCounter as resetCollectionCounter } from "./collection.factory";
import { resetCounter as resetCommentCounter } from "./comment.factory";
import { resetCounter as resetCommunityCounter } from "./community.factory";
import { resetCounter as resetDmCounter } from "./dm.factory";
import { resetCounter as resetFileCounter } from "./file.factory";
import { resetCounter as resetInitiativeCounter } from "./initiative.factory";
import { resetCounter as resetMarketplaceCounter } from "./marketplace.factory";
import { resetCounter as resetNotificationCounter } from "./notification.factory";
import { resetCounter as resetPostCounter } from "./post.factory";
import { resetCounter as resetProjectCounter } from "./project.factory";
import { resetCounter as resetPropertyCounter } from "./properties";
import { resetCounter as resetQueueCounter } from "./queue.factory";
import { resetRecentCounter } from "./recent.factory";
import { resetCounter as resetSearchCounter } from "./search.factory";
import { resetCounter as resetTagCounter } from "./tag.factory";
import { resetCounter as resetTaskCounter } from "./task.factory";
import { resetCounter as resetTaskTypeCounter } from "./taskType.factory";
import { resetCounter as resetUserCounter } from "./user.factory";
import { resetCounter as resetWikiCounter } from "./wiki.factory";

/**
 * Resets all factory counters back to 0.
 * Call this in beforeEach() to ensure deterministic IDs across tests.
 */
export function resetFactories(): void {
  resetUserCounter();
  resetCommunityCounter();
  resetInitiativeCounter();
  resetProjectCounter();
  resetTaskCounter();
  resetTaskTypeCounter();
  resetTagCounter();
  resetFileCounter();
  resetCommentCounter();
  resetNotificationCounter();
  resetQueueCounter();
  resetPropertyCounter();
  resetRecentCounter();
  resetMarketplaceCounter();
  resetSearchCounter();
  resetDmCounter();
  resetPostCounter();
  resetCollectionCounter();
  resetWikiCounter();
  resetCalendarEventCounter();
}
