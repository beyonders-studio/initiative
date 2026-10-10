import { HttpResponse, http } from "msw";

import { buildUser } from "@/__tests__/factories";

export const authHandlers = [
  http.post("/api/v1/auth/token", () => {
    return HttpResponse.json({ access_token: "test-token" });
  }),

  http.post("/api/v1/auth/register", () => {
    return HttpResponse.json(buildUser({ status: "active", email_verified: true }));
  }),

  http.get("/api/v1/auth/bootstrap", () => {
    return HttpResponse.json({
      has_users: true,
      public_registration_enabled: true,
      demo: false,
    });
  }),

  http.post("/api/v1/demo/redeem", () => {
    return HttpResponse.json({ access_token: "demo-token", community_id: 7, import_job_id: 1 });
  }),

  http.get("/api/v1/demo/copy", () => {
    return HttpResponse.json({ community_id: 7, ready: true, expires_at: null });
  }),

  http.get("/api/v1/auth/providers", () => {
    return HttpResponse.json({ providers: [] });
  }),
];
