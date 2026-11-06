import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

/**
 * Access requests. By default there is nothing to ask for and nothing to
 * answer, so a page that checks stays as it was unless a test says otherwise.
 */
export const shareHandlers = [
  communityHttp.get("/share-requests/standing", () =>
    HttpResponse.json({ detail: "SHARE_REQUEST_NOT_FOUND" }, { status: 404 })
  ),
  communityHttp.get("/share-requests/", () => HttpResponse.json([])),
];
