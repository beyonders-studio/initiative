import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/pages/community/tools/ToolIndexPage";

type CountersViewProps = {
  /** The initiative this list belongs to. Required: counter groups are only
   *  ever browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's counter groups, as cards. */
export const CounterGroupsView = (props: CountersViewProps) => (
  <ToolIndexPage tool={Tool.counter_group} {...props} />
);
