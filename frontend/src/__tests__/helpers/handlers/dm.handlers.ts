import { HttpResponse, http } from "msw";

import { buildPage } from "@/__tests__/factories/page.factory";

/**
 * The direct-message surfaces, answering empty.
 *
 * Every page that draws a person now reads some of these — the actions menu on
 * a person row asks what it may offer about them — so the default is a quiet,
 * complete answer rather than an unhandled request warning in every unrelated
 * suite. A test about any of it overrides the one handler it cares about.
 */
const noGrants = { accepted: [], incoming: [], outgoing: [] };

export const dmHandlers = [
  // An ordinary account: old enough, and reachable by the communities it is
  // in. Surfaces explain an empty list by the reader's own settings, so a
  // default of `private` would have every unrelated suite reading the panel
  // that says so instead of the page it was testing.
  http.get("/api/v1/me/dm-settings", () =>
    HttpResponse.json({
      dm_policy: "community",
      communities: [],
      age_confirmed_at: "2020-01-01T00:00:00Z",
      age_answer_required: false,
      send_receipts: true,
    })
  ),
  http.get("/api/v1/me/connections", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/message-requests", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/ignored", () => HttpResponse.json(buildPage([]))),
  http.get("/api/v1/users/:userId/dm-permission", () =>
    HttpResponse.json({ permission: "denied", may_connect: false })
  ),
  // The same two answers for a page of people at once, which is what a list
  // asks rather than one question per row.
  http.post("/api/v1/me/dm-permissions", () => HttpResponse.json({ permissions: {} })),
  // The people rosters: the walk of the reader's communities.
  http.get("/api/v1/me/people", () => HttpResponse.json({ sections: [], page: 1, page_size: 20 })),
  // Read by the sidebar's unread badge, so every suite that draws the sidebar
  // asks it — including ones that are not about messages at all.
  http.get("/api/v1/me/dm/conversations", () => HttpResponse.json({ conversations: [] })),
];
