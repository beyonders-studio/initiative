import { HttpResponse, http } from "msw";

import { buildUser } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const userHandlers = [
  http.get("/api/v1/me", () => {
    return HttpResponse.json(buildUser());
  }),
  // The settings pages ask whether a change is waiting; usually none is.
  http.get("/api/v1/me/held-change", () => HttpResponse.json(null)),
  // View preference writes are debounced, and flushed again on unmount — which
  // lands during cleanup, after a test's own handlers are gone. Answering the
  // write here keeps that flush from surfacing as an unhandled rejection in
  // whichever test happens to be running at the time.
  http.put("/api/v1/user-view-preferences/:scopeKey", () => {
    return HttpResponse.json({ items: {} });
  }),
  // The same for a community's map, which keeps the views of the lists inside
  // it; it starts empty.
  communityHttp.get("/view-preferences", () => HttpResponse.json({ items: {} })),
  communityHttp.put("/view-preferences/:scopeKey", () => HttpResponse.json({})),
];
