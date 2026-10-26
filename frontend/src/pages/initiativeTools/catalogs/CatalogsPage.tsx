import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type CatalogsViewProps = {
  /** The initiative this list belongs to. Required: catalogs are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's catalogs, as cards led by their covers.
 *
 * The list is the shelf; each catalog is its own wall. Search here reads the
 * index (name and description) — the filter box that finds a picture by its
 * caption is on the catalog's own page, where the pictures are.
 */
export const CatalogsView = (props: CatalogsViewProps) => (
  <ToolIndexPage tool={Tool.catalog} {...props} />
);
