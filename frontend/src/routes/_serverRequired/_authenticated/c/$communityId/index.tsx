import { createFileRoute } from "@tanstack/react-router";

import { validateId } from "@/lib/routeSearch";
import { CommunityHomePage } from "@/pages/CommunityHomePage";
import { CommunityHomeSkeleton } from "@/ui/page-skeletons";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/")({
  /** `node` is the rail's open node; comments is the only one. */
  /** `create=true` opens the new-initiative dialog once on arrival — the deep
   *  link the sidebar uses, and what the retired `/i` list route forwards. */
  /** `plugin` opens that installed plug-in's settings — the deep link a request from
   *  the plug-in to act as the reader points at, answered there. */
  validateSearch: (
    search: Record<string, unknown>
  ): {
    node?: string;
    create?: string;
    plugin?: number;
  } => ({
    node: typeof search.node === "string" ? search.node : undefined,
    create: search.create === "true" ? "true" : undefined,
    plugin: validateId(search.plugin),
  }),
  component: CommunityHomePage,
  // The front page draws its own outline while its code is on the way, rather
  // than the generic one the layout would otherwise show in its place.
  pendingComponent: CommunityHomeSkeleton,
  pendingMs: 0,
  pendingMinMs: 0,
});
