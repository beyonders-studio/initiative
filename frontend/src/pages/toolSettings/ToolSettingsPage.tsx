import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolMutation,
  ToolSettingsLayout,
  type ToolSettingsLayoutProps,
} from "@/components/tools/settings/ToolSettingsLayout";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useRouteId } from "@/hooks/useRouteId";
import { toolCamelSingular, toolViews } from "@/lib/tools";

type ToolSettingsPageProps = {
  tool: Tool;
  /**
   * False drops the name and description form, for a tool whose name is
   * edited on its own page and which has no description: contacts and files.
   */
  detailsForm?: boolean;
} & Pick<ToolSettingsLayoutProps, "detailsExtra" | "detailsInline" | "exportOptions" | "extraTabs">;

/**
 * Every tool's settings. Its data comes from the tool's `TOOL_HOOKS` entry, for
 * the id in the route's `<tool>Id` param; a tool with settings of its own
 * passes them as the layout's extra cards, fields and sections.
 */
export const ToolSettingsPage = ({
  tool,
  detailsForm = true,
  ...extras
}: ToolSettingsPageProps) => {
  const id = useRouteId(`${toolCamelSingular(tool)}Id`);

  const { useDetail, useUpdate, useSetGrants, useDelete } = TOOL_HOOKS[tool];
  const query = useDetail(id);
  const update = useUpdate(id ?? 0);
  const setGrants = useSetGrants(id ?? 0);
  const remove = useDelete();

  return (
    <ToolSettingsLayout
      tool={tool}
      entity={query.data}
      isLoading={query.isLoading}
      isError={id === null || query.isError}
      update={detailsForm ? update : undefined}
      // A tool with templates marks one through its update.
      template={
        toolViews(tool).includes("templates")
          ? (update as ToolMutation<{ is_template: boolean }>)
          : undefined
      }
      setGrants={setGrants}
      remove={remove}
      {...extras}
    />
  );
};
