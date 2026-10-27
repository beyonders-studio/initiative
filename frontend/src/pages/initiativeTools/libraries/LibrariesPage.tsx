import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type LibrariesViewProps = {
  /** The initiative this list belongs to. Required: libraries are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's libraries, as cards led by their covers.
 *
 * The list is the shelf; each library is its own wall. Search here reads the
 * index (name and description) — the filter box that finds a picture by its
 * description is on the library's own page, where the pictures are.
 */
export const LibrariesView = (props: LibrariesViewProps) => (
  <ToolIndexPage tool={Tool.library} {...props} />
);
