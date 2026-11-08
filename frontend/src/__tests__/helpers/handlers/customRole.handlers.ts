import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

export const customRoleHandlers = [
  // No custom roles, and nobody holding one, unless a test says otherwise.
  communityHttp.get("/custom-roles/", () => HttpResponse.json([])),
  communityHttp.get("/custom-roles/holders", () => HttpResponse.json([])),
  // Unanswered by default, so the reader's rung answers what they hold, as it
  // does while the request is in the air: an admin every part, a member none.
  // A test about custom roles answers it.
  communityHttp.get("/custom-roles/held", () =>
    HttpResponse.json({ detail: "NOT_FOUND" }, { status: 404 })
  ),
];
