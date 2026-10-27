/**
 * Turning one notification row into a sentence and a destination.
 *
 * Shared by the bell's popover (what is still unread) and the inbox page (the
 * record). One implementation: a line must read the same wherever it is shown,
 * and a second copy is how the two drift apart.
 */

import type { NavigateFn } from "@tanstack/react-router";

import { type NotificationRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { communityPath } from "@/lib/communityUrl";
import {
  entityRefTypeFor,
  isSearchEntityType,
  normalizeLegacyTarget,
  normalizePluginTarget,
} from "@/lib/entityResolver";
import { downloadExportArtifact } from "@/lib/exportDownload";
import { formatDate } from "@/lib/formatDate";
import { storeSellingNow } from "@/lib/storeSelling";
import { entityRefRoute, toolKebabSingular } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

/** Whether plan lines may ask the reader to choose a plan here. Not until a
 *  phone's store has answered (`@/lib/storeSelling`). */
const sellsHere = (): boolean => storeSellingNow() === true;

// Build community-scoped URL directly. Notification rows persist their
// target_path, so one written before tools moved inside their initiative is
// mapped onto the `/go` resolver on the way out.
const buildCommunityPath = (communityId: number, targetPath: string): string => {
  const normalized = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
  return communityPath(communityId, normalizeLegacyTarget(normalized));
};

export const resolveSmartLink = (notification: NotificationRead): string | null => {
  const data = notification.data || {};
  const communityValue = data.community_id;
  const targetValue = data.target_path;

  let communityId: number | null = null;
  if (typeof communityValue === "number") {
    communityId = communityValue;
  } else if (typeof communityValue === "string") {
    const parsed = Number(communityValue);
    communityId = Number.isFinite(parsed) ? parsed : null;
  }

  const targetPath = typeof targetValue === "string" ? targetValue : null;
  if (targetPath) {
    // A `target_path` with a community belongs inside it. One without belongs to
    // the app: an account notice (`/profile/account`) or the cross-community task
    // list is about the person rather than any one community, so the server
    // sends no `community_id` with those. The mobile tap handler has always
    // treated a bare `target_path` as an app-level route; this matches it.
    return communityId !== null
      ? buildCommunityPath(communityId, targetPath)
      : normalizePluginTarget(targetPath);
  }

  if (typeof data.smart_link === "string" && data.smart_link) {
    try {
      const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
      const parsed = new URL(data.smart_link, base);
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      if (data.smart_link.startsWith("/")) {
        return data.smart_link;
      }
    }
  }

  return null;
};

// The `/go` resolver address for a payload that names its parent generically
// (`entity_type` + `entity_id`), or null when it names nothing recognizable.
const entityRefFromData = (data: Record<string, unknown>): string | null => {
  const entityType = typeof data.entity_type === "string" ? data.entity_type : null;
  const entityId = Number(data.entity_id);
  if (!entityType || !Number.isFinite(entityId) || !isSearchEntityType(entityType)) {
    return null;
  }
  const refType = entityRefTypeFor(entityType);
  return refType ? entityRefRoute(refType, entityId) : null;
};

export const notificationLink = (notification: NotificationRead): string | null => {
  const smartLink = resolveSmartLink(notification);
  if (smartLink) {
    return smartLink;
  }
  const data = notification.data || {};
  switch (notification.type) {
    // These hold ids and nothing else, so they address the `/go` resolver,
    // which reads the entity and works out where it lives.
    case "task_assignment":
    case "case_opened":
    case "case_replied": {
      const taskId = Number(data.task_id);
      if (Number.isFinite(taskId) && data.task_id != null) {
        return entityRefRoute("task", taskId);
      }
      if (typeof data.project_id === "number") {
        return entityRefRoute(toolKebabSingular(Tool.project), data.project_id);
      }
      return null;
    }
    case "initiative_added":
      // The initiative list is a section of the community home now.
      return "/";
    case "project_added":
      if (typeof data.project_id === "number") {
        return entityRefRoute(toolKebabSingular(Tool.project), data.project_id);
      }
      return null;
    case "import_ready":
    case "import_failed": {
      // The report lives on the community's Data settings tab (the jobs table's
      // "View report"). Absolute community path — the notification names its community.
      const communityId = Number(data.community_id);
      return Number.isFinite(communityId)
        ? buildCommunityPath(communityId, "/settings/data")
        : null;
    }
    case "direct_message":
      // The page opens the conversation itself: the thread is read out of this
      // device's own store, so there is nothing for a route param to fetch.
      return "/messages";
    // Each lands where it is answered: a message request in the inbox that
    // would carry the conversation, a connection on the contacts page.
    case "message_request_received":
    case "message_request_accepted":
      return "/messages";
    case "connection_requested":
    case "connection_accepted":
      return "/contacts";
    case "mention":
    case "comment_reply":
    case "comment_on_resource":
    case "subscription_activity":
    case "assigned_activity":
      return entityRefFromData(data);
    // A granted request opens what was shared; one asking opens the requests
    // through its `target_path`.
    case "share_granted":
      return entityRefFromData(data);
    case "post_published":
      if (typeof data.post_id === "number") {
        return entityRefRoute(toolKebabSingular(Tool.post), data.post_id);
      }
      return null;
    case "access_grant_requested":
    case "access_grant_approved":
    case "access_grant_denied":
    case "access_grant_revoked":
      // The Access tab serves both requesters (their requests) and approvers
      // (the queue). It's a platform route, not community-scoped.
      return "/settings/operator/access";
    case "event_invitation":
    case "event_cancelled":
    case "event_rsvp":
    case "event_reminder": {
      const eventId = Number(data.event_id);
      return Number.isFinite(eventId) ? entityRefRoute("calendar-event", eventId) : null;
    }
    default:
      return null;
  }
};

// Returns the localized level word, or null when the level is unknown (e.g.
// older notifications written before access_level was included) — callers then
// fall back to a generic, level-less message rather than mislabeling it.
const accessLevelLabel = (
  level: unknown,
  t: (key: string, options?: Record<string, unknown>) => string
): string | null => {
  if (level === "read_write") return t("notifications.accessLevelReadWrite");
  if (level === "read") return t("notifications.accessLevelRead");
  return null;
};

/** The level a share line is about: edit for `write`, view for anything else. */
const shareLevel = (level: unknown): "read" | "write" => (level === "write" ? "write" : "read");

/** How many things a share line covers; one where the row does not say. */
const shareCount = (count: unknown): number => {
  const parsed = Number(count);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
};

// How many distinct emoji a rolled-up reaction line shows before it stops —
// the sentence names the reactors, the chips on the comment itself are the
// full picture.
const MAX_SHOWN_REACTION_EMOJI = 3;

// A reaction notification rolls up every reaction to the same comment, so the
// line names the most recent reactor, how many others joined them, and the
// emoji used. Rows written before the rollup carry their one reaction in the
// top-level `emoji`/`reactor_name` fields, which read here as a rollup of one.
const reactionSummary = (
  data: Record<string, unknown>
): { reactorName: string | null; emoji: string; others: number } => {
  const text = (value: unknown): string | null =>
    typeof value === "string" && value ? value : null;
  const entries = Array.isArray(data.reactions)
    ? (data.reactions as Array<Record<string, unknown>>)
    : [];

  const names = entries
    .map((entry) => text(entry?.reactor_name))
    .filter((name): name is string => name !== null);
  const emoji = entries
    .map((entry) => text(entry?.emoji))
    .filter((value): value is string => value !== null);

  const reactorName = text(data.reactor_name) ?? names[names.length - 1] ?? null;
  const latestEmoji = text(data.emoji);
  if (emoji.length === 0 && latestEmoji) {
    emoji.push(latestEmoji);
  }

  // `reactor_count` counts everyone the line has rolled up, including people
  // whose reactions have since rolled off the detail it keeps — counting the
  // names here would understate the crowd on a busy comment. Rows written
  // before the roster existed only ever had the names, so they use those.
  const rostered = Number(data.reactor_count);
  const others = Number.isFinite(rostered)
    ? Math.max(rostered - 1, 0)
    : new Set(names.filter((name) => name !== reactorName)).size;

  return {
    reactorName,
    emoji: Array.from(new Set(emoji)).slice(0, MAX_SHOWN_REACTION_EMOJI).join(""),
    others,
  };
};

// A comment notification rolls up every comment on the same thing, so the line
// names who and how many rather than repeating per comment. Rows written before
// the rollup carry only ``commenter_name``, which reads here as a rollup of one.
/** What a subscription line can say happened, as the feed names it. */
const SUBSCRIPTION_VERBS = [
  "created",
  "completed",
  "commented",
  "edited",
  "moved",
  "scheduled",
  "published",
  "reacted",
] as const;

export const commentSummary = (
  data: Record<string, unknown>
): { name: string; others: number; count: number } => {
  const roster = Array.isArray(data.commenters)
    ? (data.commenters as Array<Record<string, unknown>>)
    : [];
  const names = roster
    .map((entry) => (typeof entry?.name === "string" ? entry.name : null))
    .filter((name): name is string => name !== null);
  const latest = names[names.length - 1] ?? null;
  const name =
    latest ?? (typeof data.commenter_name === "string" ? data.commenter_name : "Someone");
  // `commenter_count` is everyone the line stands for, including people whose
  // entry has rolled off the roster it carries.
  const people = Number(data.commenter_count);
  const others = Number.isFinite(people) ? Math.max(people - 1, 0) : 0;
  const count = Number(data.comment_count);
  return { name, others, count: Number.isFinite(count) ? count : 1 };
};

export const notificationText = (
  notification: NotificationRead,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
      return t("notifications.taskAssignment", {
        taskTitle: data.task_title ?? t("notifications.plain.task"),
        projectName: data.project_name ?? t("notifications.plain.projectIn"),
        assignedBy: data.assigned_by_name
          ? t("notifications.taskAssignmentBy", { name: data.assigned_by_name })
          : "",
      });
    case "initiative_added":
      return t("notifications.initiativeAdded", {
        initiativeName: data.initiative_name ?? t("notifications.plain.initiative"),
      });
    case "project_added":
      return t("notifications.projectAdded", {
        projectName: data.project_name ?? t("notifications.plain.project"),
        initiativeName: data.initiative_name ?? t("notifications.plain.initiativeIn"),
      });
    case "mention":
      if (data.comment_id) {
        return t("notifications.mentionComment", {
          mentionedBy: data.mentioned_by_name ?? t("notifications.someone"),
          contextTitle: data.context_title ?? t("notifications.plain.item"),
        });
      }
      // A description or a file, named by kind and id. A task's description
      // named its task by `task_id` before that.
      return t("notifications.mentionIn", {
        mentionedBy: data.mentioned_by_name ?? t("notifications.someone"),
        title: data.entity_name ?? data.task_title ?? t("notifications.plain.item"),
      });
    case "comment_on_task": {
      const { name, others, count } = commentSummary(data);
      const taskTitle = data.task_title ?? t("notifications.plain.taskObject");
      if (count > 1) {
        return others > 0
          ? t("notifications.commentsOnTaskMulti", { name, count, others, taskTitle })
          : t("notifications.commentsOnTask", { name, count, taskTitle });
      }
      return t("notifications.commentOnTask", { commenterName: name, taskTitle });
    }
    case "comment_on_resource": {
      const { name, others, count } = commentSummary(data);
      const entityName = data.entity_name ?? t("notifications.plain.item");
      if (count > 1) {
        return others > 0
          ? t("notifications.commentsOnResourceMulti", { name, count, others, entityName })
          : t("notifications.commentsOnResource", { name, count, entityName });
      }
      return t("notifications.commentOnResource", { commenterName: name, entityName });
    }
    case "subscription_activity":
    case "assigned_activity": {
      // One line per subscribed item: who changed it, and how, or how many did.
      const { name, others } = commentSummary(data);
      const entityName = data.entity_name ?? t("notifications.plain.item");
      if (others > 0) {
        return t("notifications.subscriptionMulti", { name, count: others, entityName });
      }
      const verb = SUBSCRIPTION_VERBS.find((each) => each === data.verb) ?? "edited";
      return t(`notifications.subscription.${verb}`, { name, entityName });
    }
    case "post_published":
      return t("notifications.postPublished", {
        authorName: data.author_name ?? t("notifications.someone"),
        postName: data.post_name ?? t("notifications.plain.post"),
      });
    case "comment_reply":
      return t("notifications.commentReply", {
        replierName: data.replier_name ?? t("notifications.someone"),
        contextTitle: data.context_title ?? t("notifications.plain.item"),
      });
    case "direct_message": {
      // Who and how many. There is no preview here and no way to add one --
      // the server has no key to the message it is announcing.
      const count = typeof data.count === "number" ? data.count : 1;
      const senderName = data.sender_name ?? t("notifications.someone");
      // A group thread has no name, so it is named by who is on it -- everybody
      // but the reader. Present only on a group line.
      const members = Array.isArray(data.member_names) ? data.member_names : null;
      if (members?.length) {
        const groupName = members.join(", ");
        return count > 1
          ? t("notifications.directMessageGroupMany", { senderName, groupName, count })
          : t("notifications.directMessageGroup", { senderName, groupName });
      }
      return count > 1
        ? t("notifications.directMessageMany", { senderName, count })
        : t("notifications.directMessage", { senderName });
    }
    // Somebody asking to reach you, and the answer when you asked. Unlike a
    // message these are not opaque to the server, so the line can name who.
    case "connection_requested":
      return t("notifications.connectionRequested", {
        actorName: data.actor_name ?? t("notifications.someone"),
      });
    case "connection_accepted":
      return t("notifications.connectionAccepted", {
        actorName: data.actor_name ?? t("notifications.someone"),
      });
    case "message_request_received":
      return t("notifications.messageRequestReceived", {
        actorName: data.actor_name ?? t("notifications.someone"),
      });
    case "message_request_accepted":
      return t("notifications.messageRequestAccepted", {
        actorName: data.actor_name ?? t("notifications.someone"),
      });
    case "comment_reaction": {
      const { reactorName, emoji, others } = reactionSummary(data);
      const options = {
        reactorName: reactorName ?? t("notifications.someone"),
        emoji,
        contextTitle: data.context_title ?? t("notifications.plain.item"),
      };
      return others > 0
        ? t("notifications.commentReactionMulti", { ...options, count: others })
        : t("notifications.commentReaction", options);
    }
    case "access_grant_requested": {
      const level = accessLevelLabel(data.access_level, t);
      const requester = data.requester_name ?? t("notifications.someone");
      const community = data.community_name ?? "a community";
      return level
        ? t("notifications.accessGrantRequested", { requester, level, community })
        : t("notifications.accessGrantRequestedGeneric", { requester, community });
    }
    case "access_grant_approved": {
      const level = accessLevelLabel(data.access_level, t);
      const community = data.community_name ?? "a community";
      return level
        ? t("notifications.accessGrantApproved", { level, community })
        : t("notifications.accessGrantApprovedGeneric", { community });
    }
    case "access_grant_denied":
      return t("notifications.accessGrantDenied", {
        community: data.community_name ?? "a community",
      });
    case "access_grant_revoked":
      return t("notifications.accessGrantRevoked", {
        community: data.community_name ?? "a community",
      });
    case "event_invitation":
      return t("notifications.eventInvitation", {
        organizer: data.organizer_name ?? t("notifications.someone"),
        eventTitle: data.event_title ?? t("notifications.plain.event"),
      });
    case "event_cancelled":
      return t("notifications.eventCancelled", {
        canceller: data.canceller_name ?? t("notifications.someone"),
        eventTitle: data.event_title ?? t("notifications.plain.event"),
      });
    case "event_rsvp":
      return t("notifications.eventRsvp", {
        responder: data.responder_name ?? t("notifications.someone"),
        status: data.rsvp_status ?? "responded",
        eventTitle: data.event_title ?? t("notifications.plain.event"),
      });
    case "event_reminder":
      return t("notifications.eventReminder", {
        eventTitle: data.event_title ?? t("notifications.plain.event"),
      });
    // A request names what it is for — the thing, or for several files the
    // collection or wiki they are in — and a yes names what was shared.
    // Declined names nothing: its reader cannot open it.
    case "share_requested":
      return t(`notifications.shareRequested.${shareLevel(data.level)}`, {
        requester: data.requester_name ?? t("notifications.someone"),
        title: data.entity_name ?? t("notifications.plain.item"),
        count: shareCount(data.count),
      });
    case "share_granted":
      return t(`notifications.shareGranted.${shareLevel(data.level)}`, {
        answerer: data.answerer_name ?? t("notifications.someone"),
        title: data.entity_name ?? t("notifications.plain.item"),
        count: shareCount(data.count),
      });
    case "share_declined":
      return t("notifications.shareDeclined", {
        answerer: data.answerer_name ?? t("notifications.someone"),
        count: shareCount(data.count),
      });
    case "initiative_join_requested":
      return t("notifications.initiativeJoinRequested", {
        requester: data.requester_name ?? t("notifications.someone"),
        initiativeName: data.initiative_name ?? t("notifications.plain.initiativeIn"),
      });
    case "initiative_join_approved":
      return t("notifications.initiativeJoinApproved", {
        initiativeName: data.initiative_name ?? t("notifications.plain.initiativeIn"),
      });
    case "initiative_join_denied":
      return t("notifications.initiativeJoinDenied", {
        initiativeName: data.initiative_name ?? t("notifications.plain.initiativeIn"),
      });
    case "export_ready":
      return t("notifications.exportReady");
    case "export_failed":
      return t("notifications.exportFailed");
    case "import_ready":
      return t("notifications.importReady");
    case "import_failed":
      return t("notifications.importFailed");
    // What a moderator did to your account. Each says what changed, because
    // the alternative — the generic line — reads as a bug at exactly the
    // moment somebody needs to know what happened to them.
    case "username_changed":
      return t("notifications.usernameChanged", {
        previousHandle: data.previous_handle ?? t("notifications.yourPreviousHandle"),
      });
    case "avatar_removed":
      return t("notifications.avatarRemoved");
    // Names what went, never who took it.
    case "profile_field_cleared": {
      const field = typeof data.field === "string" ? data.field : "other";
      return t(`notifications.profileCleared.${field}`, {
        defaultValue: t("notifications.profileCleared.other"),
      });
    }
    case "account_suspended":
      return typeof data.reason === "string" && data.reason.trim()
        ? t("notifications.accountSuspendedWithReason", { reason: data.reason.trim() })
        : t("notifications.accountSuspended");
    case "account_unsuspended":
      return t("notifications.accountUnsuspended");
    case "plugin_consent_requested":
      // The label is the plug-in's own words, quoted as such by the string.
      return t("notifications.pluginConsentRequested", {
        plugin: typeof data.plugin_name === "string" ? data.plugin_name : "",
        label: typeof data.label === "string" ? data.label : "",
      });
    case "plugin_update_pending":
      return t("notifications.pluginUpdatePending", {
        plugin: typeof data.plugin_name === "string" ? data.plugin_name : "",
        version: typeof data.version === "string" ? data.version : "",
      });
    case "community_on_hold": {
      const community = typeof data.community === "string" ? data.community : "";
      // The day it is deleted, where this deployment deletes a held community.
      const date = formatDate(data.delete_on);
      const contact = typeof data.contact === "string" ? data.contact.trim() : "";
      if (date) {
        return contact
          ? t("notifications.communityOnHoldDeletingWithContact", { community, date, contact })
          : t("notifications.communityOnHoldDeleting", { community, date });
      }
      return contact
        ? t("notifications.communityOnHoldWithContact", { community, contact })
        : t("notifications.communityOnHold", { community });
    }
    // The plan lines ask the reader to choose a plan, which a device that may
    // not sell cannot offer; there each says only what happens to the community.
    case "community_trial_ending":
      return t(
        !sellsHere()
          ? "notifications.communityTrialEndingInApp"
          : "notifications.communityTrialEnding",
        {
          community: typeof data.community === "string" ? data.community : "",
          date: formatDate(data.trial_ends_on),
        }
      );
    case "community_trial_ended":
      return t(
        !sellsHere()
          ? "notifications.communityTrialEndedInApp"
          : "notifications.communityTrialEnded",
        { community: typeof data.community === "string" ? data.community : "" }
      );
    case "community_pause_reminder":
      return t(
        !sellsHere()
          ? "notifications.communityPauseReminderInApp"
          : "notifications.communityPauseReminder",
        {
          community: typeof data.community === "string" ? data.community : "",
          date: formatDate(data.holds_on),
        }
      );
    // Never names the moderator, or who reported it.
    case "moderation_removal": {
      const reason = typeof data.reason === "string" ? data.reason : "";
      return reason === "illegal"
        ? t("notifications.moderationRemovedLegal")
        : t("notifications.moderationRemoved", {
            reason: t(`moderation:removalReasons.${reason}`, { defaultValue: reason }),
          });
    }
    case "moderation_warning":
      return t("notifications.moderationWarned", {
        message: typeof data.message === "string" ? data.message : "",
      });
    // A case's title is read when the line is; the stream is what it names.
    case "case_opened":
      return t("notifications.caseOpened", {
        stream: t(`notifications.caseStreams.${String(data.stream)}`, {
          defaultValue: String(data.stream ?? ""),
        }),
        taskTitle: data.task_title ?? t("notifications.plain.task"),
      });
    case "case_replied": {
      const { name, count } = commentSummary(data);
      const taskTitle = data.task_title ?? t("notifications.plain.taskObject");
      return count > 1
        ? t("notifications.caseRepliedMany", { name, count, taskTitle })
        : t("notifications.caseReplied", { name, taskTitle });
    }
    case "ticket_updated": {
      const subject = typeof data.subject === "string" && data.subject ? data.subject : null;
      const state = typeof data.state === "string" ? data.state : "";
      // Feedback closed is feedback read, whether or not the team wrote.
      if (data.stream === "feedback" && state === "closed") {
        return t("notifications.feedbackRead");
      }
      // A reply is the news where there is one; the state says the rest.
      const key = data.replied
        ? "notifications.ticketReplied"
        : state === "waiting_on_you"
          ? "notifications.ticketWaiting"
          : state === "closed"
            ? "notifications.ticketClosed"
            : "notifications.ticketMoving";
      return t(key, { subject: subject ?? t("notifications.ticketUnnamed") });
    }
    case "community_welcome":
      return t(
        !sellsHere() ? "notifications.communityWelcomeInApp" : "notifications.communityWelcome",
        { community: typeof data.community === "string" ? data.community : "" }
      );
    default:
      return t("notifications.defaultNotification");
  }
};

/** Export artifacts are fetched, not navigated to — pull the ids the download
 * call needs, or null when the payload is malformed. */
const exportDownloadTarget = (
  notification: NotificationRead
): { communityId: number; jobId: number; source: string; format: string } | null => {
  if (notification.type !== "export_ready") {
    return null;
  }
  const data = notification.data || {};
  const communityId = Number(data.community_id);
  const jobId = Number(data.export_job_id);
  if (!Number.isFinite(communityId) || !Number.isFinite(jobId)) {
    return null;
  }
  return {
    communityId,
    jobId,
    source: typeof data.source === "string" ? data.source : "tasks",
    format: typeof data.format === "string" ? data.format : "pdf",
  };
};

/**
 * Open a notification: mark it read, then fetch a finished export or go to
 * the line's destination. Returns whether it led anywhere.
 *
 * The bell, the inbox and the desktop app's system notifications all open a
 * line through this. `t` must have the `exports` namespace loaded, for the
 * download's toasts.
 */
export const openNotification = (
  notification: NotificationRead,
  {
    markRead,
    navigate,
    t,
  }: {
    markRead: (id: number) => void;
    navigate: NavigateFn;
    t: TranslateFn;
  }
): boolean => {
  if (!notification.read_at) {
    markRead(notification.id);
  }
  // A finished export is fetched, not navigated to: the artifact lives behind
  // the job-gated download endpoint, so opening it IS the download.
  const exportTarget = exportDownloadTarget(notification);
  if (exportTarget) {
    void downloadExportArtifact(
      exportTarget.communityId,
      exportTarget.jobId,
      t,
      exportTarget.source,
      exportTarget.format
    );
    return true;
  }
  const target = notificationLink(notification);
  if (!target) {
    return false;
  }
  // A target carrying a query string (a plug-in's consent screen opens from
  // `?plugin=`) goes as an href, so the query stays search rather than path.
  void navigate(target.includes("?") ? { href: target } : { to: target });
  return true;
};
