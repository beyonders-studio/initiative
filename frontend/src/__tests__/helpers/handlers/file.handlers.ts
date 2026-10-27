import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

export const fileHandlers = [
  communityHttp.get("/files/", () => {
    return HttpResponse.json({
      items: [],
      total_count: 0,
      page: 1,
      page_size: 20,
      has_next: false,
    });
  }),
  // An initiative with no collections, so the Files page shows no strip.
  communityHttp.get("/collections/", () => HttpResponse.json({ items: [] })),
];
