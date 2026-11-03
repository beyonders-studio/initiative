import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CollectionsStrip } from "@/components/files/collections/CollectionsStrip";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type FilesViewProps = {
  /** The initiative this list belongs to. Required: files are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's files: its collections, then the files themselves as
 *  cards, a table, or browsed by tag. */
export const FilesView = (props: FilesViewProps) => (
  <div className="space-y-6">
    <CollectionsStrip initiativeId={props.fixedInitiativeId} />
    <ToolIndexPage tool={Tool.file} {...props} />
  </div>
);
