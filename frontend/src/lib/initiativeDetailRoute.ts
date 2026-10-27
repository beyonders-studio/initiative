import { lazyRouteComponent } from "@tanstack/react-router";

/**
 * The one lazy handle every initiative tab route renders through.
 *
 * Each tool tab is its own route, all drawing the same page with a different
 * `tool` prop. Had every route file wrapped the page in its own
 * `lazyRouteComponent`, the first visit to each tab would suspend at the
 * router's boundary — the header and tab strip already on screen would give
 * way to a whole-page placeholder while React resolved a module it already
 * had. Sharing the handle resolves it once, so moving between tabs only ever
 * waits on the tab's own content.
 */
export const LazyInitiativeDetailPage = lazyRouteComponent(() =>
  import("@/pages/InitiativeDetailPage").then((m) => ({ default: m.InitiativeDetailPage }))
);
