import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

/** Resumable uploads held by the default handlers: id → bytes arrived. */
const arrived = new Map<string, number>();
let uploads = 0;

export const fileHandlers = [
  // A file sent in pieces (`uploadInPieces`): taken whole, piece by piece.
  communityHttp.post("/resumable-uploads", () => {
    const id = `up-${++uploads}`;
    arrived.set(id, 0);
    return new HttpResponse(null, {
      status: 201,
      headers: { Location: `http://localhost/api/v1/c/1/resumable-uploads/${id}` },
    });
  }),
  communityHttp.patch("/resumable-uploads/:id", async ({ params, request }) => {
    const id = String(params.id);
    const offset = (arrived.get(id) ?? 0) + (await request.arrayBuffer()).byteLength;
    arrived.set(id, offset);
    return new HttpResponse(null, { status: 204, headers: { "Upload-Offset": String(offset) } });
  }),
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
