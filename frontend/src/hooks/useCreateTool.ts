import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { askForStoreReview } from "@/lib/storeReview";

/** All a tool needs to exist: a name, and where it lives. */
interface NewTool {
  tool: Tool;
  name: string;
  initiativeId: number;
}

/**
 * Making any tool, when which one is only known at the moment it is made.
 *
 * The same create every tool's table entry in `TOOL_HOOKS` carries, and the
 * same lists refreshed afterwards, so this is that path with the tool chosen
 * late rather than a second way in.
 */
export const useCreateTool = () =>
  useCommunityMutation<{ id: number }, NewTool>({
    mutationFn: (communityId, { tool, name, initiativeId }) =>
      TOOL_HOOKS[tool].create(communityId, { name, initiative_id: initiativeId }),
    invalidate: (_made, { tool }) => {
      askForStoreReview();
      return invalidate(q.toolList(tool));
    },
  });
