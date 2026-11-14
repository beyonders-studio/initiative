import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/pages/community/tools/ToolIndexPage";

type ProjectsViewProps = {
  /** The initiative this list belongs to. Required: projects are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's projects: cards in the reader's own order, a table, or
 *  browsed by tag. */
export const ProjectsView = (props: ProjectsViewProps) => (
  <ToolIndexPage tool={Tool.project} {...props} />
);
