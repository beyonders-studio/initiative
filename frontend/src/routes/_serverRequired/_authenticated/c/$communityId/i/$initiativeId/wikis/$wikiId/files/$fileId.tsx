import { createFileRoute } from "@tanstack/react-router";

import { FileView } from "@/pages/community/tools/wikis/FileView";

/**
 * A file somebody put in this wiki, read as one of its pages.
 *
 * A sibling of the wiki's own pages rather than a redirect to the file,
 * because the point of putting a file in a wiki is that it is read with
 * the wiki's navigation beside it. Editing it goes to the file's own
 * address, where it is edited like any other file.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/files/$fileId"
)({
  staticData: { fullBleed: true },
  component: FileView,
});
