import { createFileRoute } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";
import { MyToolsPage } from "@/pages/user/MyToolsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-tools")({
  /** `tool` is a tool's route segment ("projects", "counter-groups", …). It is
   *  passed through as-is; the page resolves it against the tool registry and
   *  falls back to the first tool it actually has a tab for. */
  /** `q`, `sort` and `dir` are the table's search box and its order, and
   *  `made=me` is the "made by me" view. They ride in the address so a
   *  narrowed, re-ordered table is a link someone can send; the page resolves
   *  an unknown value back to its default rather than refusing it. */
  /** `communities` is a comma-separated list of community ids to keep. */
  validateSearch: (
    search: Record<string, unknown>
  ): {
    tool?: string;
    page?: number;
    q?: string;
    sort?: string;
    dir?: string;
    made?: string;
    communities?: string;
  } => ({
    tool: typeof search.tool === "string" ? search.tool : undefined,
    page: validatePage(search.page),
    q: typeof search.q === "string" && search.q ? search.q : undefined,
    sort: typeof search.sort === "string" ? search.sort : undefined,
    dir: search.dir === "asc" || search.dir === "desc" ? search.dir : undefined,
    made: search.made === "me" ? "me" : undefined,
    communities: typeof search.communities === "string" ? search.communities : undefined,
  }),
  component: MyToolsPage,
});
