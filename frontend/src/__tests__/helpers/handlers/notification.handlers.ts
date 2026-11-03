import { HttpResponse, http } from "msw";

import type {
  Channel,
  NotificationCategoryRead,
  NotificationPreferencesRead,
} from "@/api/generated/initiativeAPI.schemas";

const ALL_ON: Record<Channel, boolean> = {
  in_app: true,
  email: true,
  push: true,
  desktop: true,
};
const EVERY_CHANNEL: Channel[] = ["in_app", "email", "push", "desktop"];
// Being told your account was acted on, or that a queue waits on you, is not
// an opt-in — the bell stays.
const KEEPS_THE_BELL: Channel[] = ["email", "push", "desktop"];
// A digest is a letter and a ping, with no line of its own.
const DIGEST: Channel[] = ["email", "push"];

const category = (
  name: string,
  group: NotificationCategoryRead["group"],
  extras: Partial<NotificationCategoryRead> = {}
): NotificationCategoryRead => ({
  category: name as NotificationCategoryRead["category"],
  group,
  personal: false,
  community_scoped: true,
  per_community: group === "your_communities",
  mutable_channels: EVERY_CHANNEL,
  defaults: ALL_ON,
  ...extras,
});

/** The registry as the backend serves it — the settings grid renders from this. */
export const buildNotificationPreferences = (
  overrides: Partial<NotificationPreferencesRead> = {}
): NotificationPreferencesRead => ({
  categories: [
    category("mentions", "your_communities", { personal: true }),
    category("assignments", "your_communities", { personal: true }),
    category("subscriptions", "your_communities"),
    category("news", "your_communities"),
    category("approvals", "community", {
      personal: true,
      mutable_channels: KEEPS_THE_BELL,
    }),
    category("moderation", "community", {
      personal: true,
      mutable_channels: KEEPS_THE_BELL,
    }),
    // Not a preference: nothing switches it off.
    category("cases", "community", { mutable_channels: [] }),
    category("direct_messages", "account", {
      personal: true,
      community_scoped: false,
    }),
    category("jobs", "account", { personal: true }),
    category("account", "account", {
      personal: true,
      community_scoped: false,
      mutable_channels: KEEPS_THE_BELL,
    }),
    category("overdue", "digests", { community_scoped: false, mutable_channels: DIGEST }),
    category("coming_up", "digests", {
      community_scoped: false,
      mutable_channels: DIGEST,
      defaults: { ...ALL_ON, email: false, push: false },
    }),
  ],
  settings: {},
  quiet_hours: null,
  email: { cadence: "instant", at: "21:00", weekday: 1, personal_instant: true },
  digests: {
    overdue: { cadence: "daily", at: "21:00", weekday: 1 },
    coming_up: { cadence: "daily", at: "07:00", weekday: 1 },
  },
  pause: null,
  respect_presence: true,
  communities: [],
  ...overrides,
});

export const notificationHandlers = [
  http.get("/api/v1/me/notification-preferences", () =>
    HttpResponse.json(buildNotificationPreferences())
  ),
  http.put("/api/v1/me/notification-preferences", () =>
    HttpResponse.json(buildNotificationPreferences())
  ),
  http.get("/api/v1/notifications/unread", () => HttpResponse.json({ places: [] })),
  http.post("/api/v1/notifications/read-subject", () =>
    HttpResponse.json({ comment_ids: [], since: null })
  ),
  http.get("/api/v1/notifications/", () =>
    HttpResponse.json({ notifications: [], unread_count: 0, next_cursor: null })
  ),
];
