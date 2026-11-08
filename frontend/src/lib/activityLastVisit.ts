/**
 * When the reader last opened a community's front page, or one page in it
 * (``scope``, as `project:12`). Kept on the device, per account: it orders
 * nothing and nobody else needs it, and it is what marks an activity entry as
 * new and where a catch-up starts.
 */
export const activityLastVisitKey = (userId: number, communityId: number, scope?: string) =>
  `activity-last-visit:${userId}:${communityId}${scope ? `:${scope}` : ""}`;
