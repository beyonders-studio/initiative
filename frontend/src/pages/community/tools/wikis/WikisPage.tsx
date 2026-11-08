import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/pages/community/tools/ToolIndexPage";

type WikisViewProps = {
  /** The initiative this list belongs to. Required: wikis are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's wikis, as cards.
 *
 * The list is the shelf; each wiki is its own body of pages. Search here reads
 * the index (name and description) — finding a page by what is written on it
 * happens inside the wiki, where the pages are.
 */
export const WikisView = (props: WikisViewProps) => <ToolIndexPage tool={Tool.wiki} {...props} />;
