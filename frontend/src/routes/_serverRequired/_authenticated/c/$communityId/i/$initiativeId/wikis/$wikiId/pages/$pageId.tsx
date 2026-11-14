import { createFileRoute } from "@tanstack/react-router";

import { PageView } from "@/pages/community/tools/wikis/PageView";

/**
 * One page of a wiki. A sibling route of the wiki's own index rather than a
 * search param, because a page is the thing people link to — a URL that names
 * it is the whole point of writing one.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/pages/$pageId"
)({
  // A wiki is a surface, not a page in the reading column: it puts its
  // own header against the top and scrolls its own middle.
  staticData: { fullBleed: true },
  /**
   * Whether the page is open for writing.
   *
   * In the address rather than in component state because two separate places
   * offer it — the bar over the page and the page's own row in the tree, which
   * are different React trees — and because "this page, being edited" is a
   * thing somebody can then link to or reload back into.
   */
  validateSearch: (search: Record<string, unknown>): { edit?: true } =>
    search.edit === true || search.edit === "true" ? { edit: true } : {},
  component: PageView,
});
