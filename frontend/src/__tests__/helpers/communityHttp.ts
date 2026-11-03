import { http } from "msw";

/**
 * MSW helper for community-scoped endpoints.
 *
 * Community-scoped requests hit `/api/v1/c/{communityId}/...` (path-based tenancy).
 * Rather than repeating that prefix in every handler, register handlers with a
 * RESOURCE-RELATIVE path here and the `/api/v1/c/:communityId` base is applied in
 * one place. `:communityId` matches any community.
 *
 *   communityHttp.get("/tasks/", resolver)  ->  GET /api/v1/c/:communityId/tasks/
 *
 * Non-community endpoints (/api/v1/me/*, /api/v1/me, /api/v1/auth/*, etc.)
 * keep using `http` directly.
 */
const COMMUNITY_BASE = "/api/v1/c/:communityId";

type GetArgs = Parameters<typeof http.get>;

export const communityHttp = {
  get: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.get(`${COMMUNITY_BASE}${path}`, resolver, options),
  head: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.head(`${COMMUNITY_BASE}${path}`, resolver, options),
  post: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.post(`${COMMUNITY_BASE}${path}`, resolver, options),
  put: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.put(`${COMMUNITY_BASE}${path}`, resolver, options),
  patch: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.patch(`${COMMUNITY_BASE}${path}`, resolver, options),
  delete: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.delete(`${COMMUNITY_BASE}${path}`, resolver, options),
};
