import { HttpResponse } from "msw";

import { buildContact } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const contactHandlers = [
  communityHttp.get("/contacts/", () =>
    HttpResponse.json({
      items: [],
      total_count: 0,
      page: 1,
      page_size: 20,
      has_next: false,
      has_prev: false,
    })
  ),
  communityHttp.get("/contacts/:contactId", ({ params }) =>
    HttpResponse.json(buildContact({ id: Number(params.contactId) }))
  ),
];
