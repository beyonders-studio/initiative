/**
 * A notification has to say what happened and go where it happened.
 *
 * The account notices — a moderator renamed you, took your picture down,
 * suspended you — did neither. They fell past every `case` to the generic
 * "You have a new notification", and their destination was dropped because
 * the resolver only honoured a `target_path` that came with a `community_id`.
 * These notices belong to the person rather than to any community, so the
 * server sends no community with them.
 */
import { describe, expect, it } from "vitest";

import { buildNotification } from "@/__tests__/factories/notification.factory";
import { asPhoneThatMayNotSell } from "@/__tests__/helpers/storeSelling";
import type { NotificationType } from "@/api/generated/initiativeAPI.schemas";

import { notificationLink, notificationText } from "./notificationLine";

// The real strings are asserted through i18n keys rather than English, so a
// reworded translation doesn't fail this; what matters is that a key was
// resolved at all instead of the fallback.
const t = (key: string, options?: Record<string, unknown>) =>
  options && Object.keys(options).length ? `${key}(${JSON.stringify(options)})` : key;

const notice = (type: string, data: Record<string, unknown>) =>
  buildNotification({ type: type as NotificationType, data });

describe("notificationText — account notices", () => {
  it("says which handle a moderator took away", () => {
    const line = notificationText(
      notice("username_changed", {
        previous_handle: "oldname#1234",
        target_path: "/settings/profile",
      }),
      t
    );

    expect(line).toContain("notifications.usernameChanged");
    expect(line).toContain("oldname#1234");
    expect(line).not.toContain("defaultNotification");
  });

  it("still reads as a sentence when the old handle wasn't recorded", () => {
    const line = notificationText(notice("username_changed", {}), t);

    expect(line).toContain("notifications.usernameChanged");
    expect(line).toContain("notifications.yourPreviousHandle");
  });

  it("gives the reason for a suspension when there is one", () => {
    expect(notificationText(notice("account_suspended", { reason: "spam" }), t)).toContain(
      "notifications.accountSuspendedWithReason"
    );
    // A reason that is only whitespace is no reason at all.
    expect(notificationText(notice("account_suspended", { reason: "   " }), t)).toBe(
      "notifications.accountSuspended"
    );
    expect(notificationText(notice("account_suspended", { reason: null }), t)).toBe(
      "notifications.accountSuspended"
    );
  });

  it("names who to contact about a hold when there is somebody", () => {
    const named = notice("community_on_hold", { community: "Acme", contact: "help@example.com" });
    const nobody = notice("community_on_hold", { community: "Acme", contact: null });
    expect(notificationText(named, t)).toContain("notifications.communityOnHoldWithContact");
    expect(notificationText(nobody, t)).toContain("notifications.communityOnHold");
    expect(notificationText(nobody, t)).not.toContain("WithContact");
  });

  it("names the day a held community is deleted, where it is", () => {
    const dated = notice("community_on_hold", {
      community: "Acme",
      contact: "help@example.com",
      delete_on: "2026-10-24",
    });
    const line = notificationText(dated, t);
    expect(line).toContain("notifications.communityOnHoldDeletingWithContact");
    expect(line).toContain("2026");
    expect(
      notificationText(
        notice("community_on_hold", { community: "Acme", delete_on: "2026-10-24" }),
        t
      )
    ).toContain("notifications.communityOnHoldDeleting(");
  });

  it("says when a trial ends, that it has, and that a new community is ready", () => {
    const ending = notificationText(
      notice("community_trial_ending", { community: "Acme", trial_ends_on: "2026-10-08" }),
      t
    );
    expect(ending).toContain("notifications.communityTrialEnding");
    expect(ending).toContain("Acme");
    expect(ending).toContain("2026");
    expect(notificationText(notice("community_trial_ended", { community: "Acme" }), t)).toContain(
      "notifications.communityTrialEnded"
    );
    const paused = notificationText(
      notice("community_pause_reminder", { community: "Acme", holds_on: "2027-04-17" }),
      t
    );
    expect(paused).toContain("notifications.communityPauseReminder(");
    expect(paused).toContain("2027");
    expect(notificationText(notice("community_welcome", { community: "Acme" }), t)).toBe(
      'notifications.communityWelcome({"community":"Acme"})'
    );
  });

  it("asks for no plan in the phone app, which may not sell", () => {
    const native = asPhoneThatMayNotSell();
    try {
      expect(
        notificationText(
          notice("community_trial_ending", { community: "Acme", trial_ends_on: "2026-10-08" }),
          t
        )
      ).toContain("notifications.communityTrialEndingInApp(");
      expect(notificationText(notice("community_trial_ended", { community: "Acme" }), t)).toBe(
        'notifications.communityTrialEndedInApp({"community":"Acme"})'
      );
      expect(
        notificationText(
          notice("community_pause_reminder", { community: "Acme", holds_on: "2027-04-17" }),
          t
        )
      ).toContain("notifications.communityPauseReminderInApp(");
      expect(notificationText(notice("community_welcome", { community: "Acme" }), t)).toBe(
        'notifications.communityWelcomeInApp({"community":"Acme"})'
      );
    } finally {
      native.mockRestore();
    }
  });

  it("takes a trial notice to the community's Plan & usage tab", () => {
    expect(
      notificationLink(
        notice("community_trial_ending", { community_id: 7, target_path: "/settings/usage" })
      )
    ).toBe("/c/7/settings/usage");
  });

  it("covers the rest of the account notices", () => {
    expect(notificationText(notice("avatar_removed", {}), t)).toBe("notifications.avatarRemoved");
    expect(notificationText(notice("account_unsuspended", {}), t)).toBe(
      "notifications.accountUnsuspended"
    );
  });
});

describe("notificationLink — a target_path without a community", () => {
  it("takes an account notice to the account screen", () => {
    expect(notificationLink(notice("username_changed", { target_path: "/profile/account" }))).toBe(
      "/profile/account"
    );
    expect(notificationLink(notice("avatar_removed", { target_path: "/profile" }))).toBe(
      "/profile"
    );
  });

  it("rewrites the route that never existed", () => {
    // Rows already written carry `/settings/profile`, which is not a page.
    // The server stopped minting it; these are the ones already sent.
    expect(notificationLink(notice("username_changed", { target_path: "/settings/profile" }))).toBe(
      "/profile/account"
    );
  });

  it("keeps scoping a path that does name a community", () => {
    expect(
      notificationLink(notice("post_published", { community_id: 7, target_path: "/posts/3" }))
    ).toBe("/c/7/posts/3");
  });

  it("still leads nowhere when the payload names nowhere", () => {
    expect(notificationLink(notice("username_changed", {}))).toBeNull();
  });
});

describe("notificationText — mentions", () => {
  it("names what a description that mentioned you describes", () => {
    const line = notificationText(
      notice("mention", {
        entity_type: "collection",
        entity_id: 7,
        entity_name: "Ship it",
        mentioned_by_name: "ada",
      }),
      t
    );

    expect(line).toContain("notifications.mentionIn");
    expect(line).toContain("Ship it");
  });

  it("still names the task of a description mention sent by its task", () => {
    const line = notificationText(
      notice("mention", { task_id: 7, task_title: "Ship it", mentioned_by_name: "ada" }),
      t
    );

    expect(line).toContain("notifications.mentionIn");
    expect(line).toContain("Ship it");
  });

  it("still reads a mention in a comment on a task as a comment mention", () => {
    const line = notificationText(
      notice("mention", { task_id: 7, comment_id: 3, context_title: "Ship it" }),
      t
    );

    expect(line).toContain("notifications.mentionComment");
  });

  it("names and links the file whose body mentioned you", () => {
    const mention = notice("mention", {
      entity_type: "file",
      entity_id: 9,
      entity_name: "Flight plan",
    });

    expect(notificationText(mention, t)).toContain("Flight plan");
    expect(notificationLink(mention)).toBe("/go/file/9");
  });
});

describe("a plug-in asking to act as the reader", () => {
  const request = notice("plugin_consent_requested", {
    community_id: 4,
    plugin_id: 7,
    plugin_name: "Auto",
    label: "Comment on the linked issue",
    target_path: "/?plugin=7",
  });

  it("names the plug-in and quotes what it asked", () => {
    expect(notificationText(request, t)).toBe(
      `notifications.pluginConsentRequested(${JSON.stringify({
        plugin: "Auto",
        label: "Comment on the linked issue",
      })})`
    );
  });

  it("opens that plug-in's settings in its community", () => {
    expect(notificationLink(request)).toBe("/c/4/?plugin=7");
  });
});

describe("a plug-in version waiting for the seat", () => {
  const waiting = notice("plugin_update_pending", {
    community_id: 4,
    plugin_id: 7,
    plugin_name: "Auto",
    version: "1.2.0",
    target_path: "/settings/integrations",
  });

  it("names the plug-in and the version", () => {
    expect(notificationText(waiting, t)).toBe(
      `notifications.pluginUpdatePending(${JSON.stringify({ plugin: "Auto", version: "1.2.0" })})`
    );
  });

  it("opens the community's integrations settings", () => {
    expect(notificationLink(waiting)).toBe("/c/4/settings/integrations");
  });
});

describe("notificationText — a ticket the reader filed", () => {
  const ticket = (data: Record<string, unknown>) =>
    notice("ticket_updated", {
      task_id: 7,
      subject: "Lost my phone",
      target_path: "/my-tickets/7",
      ...data,
    });

  it("leads with a reply where there is one", () => {
    const line = notificationText(ticket({ state: "waiting_on_you", replied: true }), t);
    expect(line).toContain("notifications.ticketReplied");
    expect(line).toContain("Lost my phone");
  });

  it("otherwise says where it stands", () => {
    expect(notificationText(ticket({ state: "waiting_on_you", replied: false }), t)).toContain(
      "notifications.ticketWaiting"
    );
    expect(notificationText(ticket({ state: "closed", replied: false }), t)).toContain(
      "notifications.ticketClosed"
    );
    expect(notificationText(ticket({ state: "in_progress", replied: false }), t)).toContain(
      "notifications.ticketMoving"
    );
  });

  it("says closed feedback was read", () => {
    const line = notificationText(
      ticket({ stream: "feedback", subject: null, state: "closed", replied: true }),
      t
    );
    expect(line).toContain("notifications.feedbackRead");
  });

  it("names an untitled ticket as theirs", () => {
    const line = notificationText(ticket({ subject: null, state: "closed" }), t);
    expect(line).toContain("notifications.ticketUnnamed");
  });

  it("goes to the reader's own view of it, outside any community", () => {
    expect(notificationLink(ticket({ state: "closed" }))).toBe("/my-tickets/7");
  });
});

describe("notificationText — cases", () => {
  it("names the stream and the case that opened", () => {
    const line = notificationText(
      notice("case_opened", { task_id: 4, stream: "security", task_title: "Leaked key" }),
      t
    );
    expect(line).toContain("notifications.caseOpened");
    expect(line).toContain("notifications.caseStreams.security");
    expect(line).toContain("Leaked key");
  });

  it("counts the replies on a case nobody has taken", () => {
    expect(
      notificationText(notice("case_replied", { task_id: 4, commenter_name: "asker" }), t)
    ).toContain("notifications.caseReplied");
    expect(
      notificationText(
        notice("case_replied", {
          task_id: 4,
          commenters: [{ name: "asker" }],
          commenter_count: 1,
          comment_count: 3,
        }),
        t
      )
    ).toContain("notifications.caseRepliedMany");
  });

  it("opens the case", () => {
    expect(notificationLink(notice("case_opened", { task_id: 4 }))).toBe("/go/task/4");
  });
});

describe("notificationText — a profile cleared by staff", () => {
  it("names what went, and still reads for a part it doesn't know", () => {
    expect(notificationText(notice("profile_field_cleared", { field: "custom_status" }), t)).toBe(
      'notifications.profileCleared.custom_status({"defaultValue":"notifications.profileCleared.other"})'
    );
    expect(notificationLink(notice("profile_field_cleared", { target_path: "/profile" }))).toBe(
      "/profile"
    );
  });
});

describe("notificationText — something the reader subscribed to", () => {
  it("names what one person did, and counts the rest once several did", () => {
    const one = notificationText(
      notice("subscription_activity", {
        verb: "completed",
        entity_name: "Book the hall",
        commenters: [{ name: "Ada" }],
        commenter_count: 1,
      }),
      t
    );
    expect(one).toContain("notifications.subscription.completed");
    expect(one).toContain("Book the hall");

    // A verb the line does not know reads as an edit rather than nothing.
    expect(notificationText(notice("subscription_activity", { verb: "teleported" }), t)).toContain(
      "notifications.subscription.edited"
    );

    expect(
      notificationText(
        notice("subscription_activity", {
          verb: "commented",
          commenters: [{ name: "Ada" }, { name: "Bram" }],
          commenter_count: 3,
        }),
        t
      )
    ).toContain("notifications.subscriptionMulti");
  });

  it("reads a change to what the reader is named on as a subscription line", () => {
    const line = notice("assigned_activity", {
      entity_type: "task",
      entity_id: 9,
      verb: "moved",
      commenters: [{ name: "Ada" }],
      commenter_count: 1,
    });
    expect(notificationText(line, t)).toContain("notifications.subscription.moved");
    expect(notificationLink(line)).toBe("/go/task/9");
  });

  it("names a reaction to a post on the post's line", () => {
    const one = notice("subscription_activity", {
      entity_type: "post",
      entity_id: 5,
      verb: "reacted",
      commenters: [{ name: "Ada" }],
      commenter_count: 1,
    });
    expect(notificationText(one, t)).toContain("notifications.subscription.reacted");
    expect(notificationLink(one)).toBe("/go/post/5");
  });
});
