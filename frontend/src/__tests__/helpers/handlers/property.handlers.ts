import { HttpResponse } from "msw";

import { buildPropertyDefinition } from "@/__tests__/factories/properties";
import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { communityHttp } from "../communityHttp";

/**
 * The definitions list as the server answers it: the initiative's
 * properties, or, asked with `project_id` or `collection_id`, that project's
 * or collection's metadata.
 */
export const definitionsHandler = (
  properties: PropertyDefinitionRead[],
  metadata: { project?: PropertyDefinitionRead[]; collection?: PropertyDefinitionRead[] } = {}
) =>
  communityHttp.get("/property-definitions/", ({ request }) => {
    const asked = new URL(request.url).searchParams;
    if (asked.has("project_id")) return HttpResponse.json(metadata.project ?? []);
    if (asked.has("collection_id")) return HttpResponse.json(metadata.collection ?? []);
    return HttpResponse.json(properties);
  });

/**
 * Default MSW handlers for the property endpoints.
 *
 * These provide permissive defaults so components can render without
 * explicit setup; individual tests override via `server.use(...)` when
 * they need to assert on specific request bodies or inject fixtures.
 */
export const propertyHandlers = [
  // ── Property definitions ──────────────────────────────────────────────────
  definitionsHandler([]),

  communityHttp.post("/property-definitions/", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      buildPropertyDefinition({
        name: (body.name as string) ?? "New property",
        type: (body.type as never) ?? "text",
        initiative_id: typeof body.initiative_id === "number" ? body.initiative_id : 1,
        options: (body.options as never) ?? null,
      })
    );
  }),

  communityHttp.patch("/property-definitions/:definitionId", async ({ params, request }) => {
    const id = Number(params.definitionId);
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      definition: buildPropertyDefinition({
        id,
        ...(body as Partial<ReturnType<typeof buildPropertyDefinition>>),
      }),
      orphaned_value_count: 0,
    });
  }),

  communityHttp.delete("/property-definitions/:definitionId", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ── Set values ────────────────────────────────────────────────────────────
  // One route for every target. Echoes nothing back: the components under
  // test refetch the row rather than read the answer.
  communityHttp.put("/properties/:target/:entityId", () => HttpResponse.json([])),
];
