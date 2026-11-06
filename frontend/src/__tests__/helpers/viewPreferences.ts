import { HttpResponse, http } from "msw";

import { server } from "@/__tests__/helpers/msw-server";

/**
 * A server that keeps this reader's view preferences as they save them, the
 * way the real one does, so a list opened again (a fresh query client) finds
 * what they left: the account's, or with `communityId`, that community's,
 * which keeps the views of the lists inside it. Returns what is kept, by key.
 */
export const keepViewPreferences = (communityId?: number): Record<string, unknown> => {
  const kept: Record<string, unknown> = {};
  const map =
    communityId === undefined
      ? "/api/v1/user-view-preferences"
      : `/api/v1/c/${communityId}/view-preferences`;
  server.use(
    http.get(map, () => HttpResponse.json({ items: { ...kept } })),
    http.put(`${map}/:scopeKey`, async ({ params, request }) => {
      kept[String(params.scopeKey)] = ((await request.json()) as { value: unknown }).value;
      return HttpResponse.json({});
    })
  );
  return kept;
};
